"""Command line: `read URL` for demos, `batch` for pass-rate checks, `serve-http` for the API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audit import configure_logging
from .config import Settings
from .errors import ReaderError
from .security import RateLimiter
from .service import ReaderService, find_urls


def _batch(args: argparse.Namespace, settings: Settings) -> int:
    from .batch import format_report, run_batch, summarize, to_json

    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    urls = find_urls(text)
    if not urls:
        print("没有找到链接：请粘贴分享文字或链接，每段之间换行即可", file=sys.stderr)
        return 2
    # A local batch is one deliberate run: let it through the per-minute limit.
    limiter = RateLimiter(max(settings.burst_per_minute, len(urls)), max(settings.daily_quota, len(urls)))
    service = ReaderService(settings, limiter=limiter)
    print(f"共 {len(urls)} 条链接，开始读取（并发 {args.workers}）…", file=sys.stderr)

    def progress(item, done: int, total: int) -> None:
        status = "✅" if item.ok else f"❌ {item.error_code}"
        print(f"[{done}/{total}] #{item.index} {status} {item.seconds}s", file=sys.stderr)

    items = run_batch(service, urls, workers=args.workers, progress=progress)
    summary = summarize(items)
    report = format_report(items, summary)
    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text(report, encoding="utf-8")
        print(f"报告已保存：{args.save}", file=sys.stderr)
    print(json.dumps(to_json(items, summary), ensure_ascii=False, indent=2) if args.json else report)
    return 0 if summary["ok"] == summary["total"] else 1



def _save(result: dict, directory: Path, service: ReaderService, download_media: bool) -> list[dict]:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "body.txt").open("x", encoding="utf-8") as stream:
        stream.write(result["body_text"])
        stream.write("\n")
    saved = [{"kind": "text", "file": "body.txt"}]
    if not download_media:
        return saved
    media = result["media"]
    items = [("image", value) for value in media.get("images", [])]
    items.extend((kind, media.get(kind + "_url")) for kind in ("video", "audio"))
    if not any(url for _, url in items):
        saved.append({"kind": "media", "error": "页面未提供可下载的媒体地址"})
    for index, (kind, url) in enumerate(items, 1):
        if not url:
            continue
        try:
            path, size = service.fetcher.download_media(
                url, directory, f"{kind}-{index:03d}", referer=result["canonical_url"] or result["source_url"],
            )
        except (ReaderError, OSError) as error:
            saved.append({"kind": kind, "error": error.message if isinstance(error, ReaderError) else str(error)})
        else:
            saved.append({"kind": kind, "file": path.name, "bytes": size, "quality": "source_url"})
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="social-reader")
    sub = parser.add_subparsers(dest="command", required=True)

    read = sub.add_parser("read", help="读取一个链接（或一段分享文字）")
    read.add_argument("url")
    read.add_argument("--json", action="store_true", help="输出完整 JSON 结果")
    read.add_argument("--include-media", action="store_true")
    read.add_argument("--include-comments", action="store_true")
    read.add_argument("--save-dir", help="将正文保存到指定目录")
    read.add_argument("--download-media", action="store_true", help="同时下载可取得的图片和音视频，需要 --save-dir")
    read.add_argument("--include-transcript", action="store_true", help="可选 ASR 组件已安装时，转写支持的视频并标记时间点")
    read.add_argument("--language", default="zh-CN", help="转写语种（默认 zh-CN；可用 auto）")

    batch = sub.add_parser("batch", help="批量读取并统计通过率（任意粘贴分享文字或链接）")
    batch.add_argument("file", nargs="?", default="-", help="含链接或分享文字的文本文件；省略则从标准输入读取")
    batch.add_argument("--workers", type=int, default=3, help="并发数（默认 3）")
    batch.add_argument("--json", action="store_true", help="输出 JSON（汇总 + 每条明细）")
    batch.add_argument("--save", help="把 Markdown 报告另存到这个文件")

    http = sub.add_parser("serve-http", help="启动 HTTP API（需要 SOCIAL_READER_API_KEY）")
    http.add_argument("--host", default="127.0.0.1")
    http.add_argument("--port", type=int, default=8787)

    args = parser.parse_args(argv)
    if args.command == "read" and args.download_media and not args.save_dir:
        parser.error("--download-media 需要 --save-dir")
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    if args.command == "serve-http":
        from .http_api import serve

        serve(args.host, args.port)
        return 0
    if args.command == "batch":
        return _batch(args, settings)

    service = ReaderService(settings)
    result = service.read_page(
        args.url,
        output="both",
        include_media=args.include_media or args.download_media,
        include_comments=args.include_comments,
        include_transcript=args.include_transcript,
        language=args.language,
        caller="cli",
    )
    if result["ok"] and args.save_dir:
        try:
            result["saved_files"] = _save(result, Path(args.save_dir), service, args.download_media)
        except OSError as error:
            print(f"保存失败：{error}", file=sys.stderr)
            return 1
        if not args.include_media:
            result["media"]["images"] = []
            result["media"]["video_url"] = None
            if "audio_url" in result["media"]:
                result["media"]["audio_url"] = None
    if result["ok"] and args.save_dir and not args.json:
        for item in result["saved_files"]:
            message = item.get("file") or item.get("error", "保存失败")
            print(f"{item['kind']}: {message}", file=sys.stderr)
    if args.json or not result["ok"]:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["body_markdown"])
    if not result["ok"]:
        return 1
    if any("error" in item for item in result.get("saved_files", [])):
        return 2
    if args.include_transcript and result.get("transcript", {}).get("status") != "ok":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
