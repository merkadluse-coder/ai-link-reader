"""Batch reading for pass-rate checks (TEST_PLAN P1: fresh samples per platform).

Paste any mix of share texts and links; every link is read once and the run is
summarised per platform and per access path, with structured-field coverage.
"""

from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .router import PLATFORM_LABELS, route
from .security import redact_url
from .service import ReaderService

PATH_LABELS = {
    "BROWSER_RENDERED": "浏览器渲染",
    "DESKTOP_PAGE": "电脑网页版",
    "PLATFORM_PARSER_PENDING": "通用读取",
}
CORE_FIELDS = ("标题", "作者", "发布时间", "互动数", "正文/标签")


@dataclass
class BatchItem:
    index: int
    url: str
    platform: str
    ok: bool
    path: str
    seconds: float
    title: str = ""
    fields_ok: int = 0
    error_code: str = ""
    message: str = ""


def _path(result: dict[str, Any]) -> str:
    codes = {w["code"] for w in result.get("warnings", [])}
    return next((label for code, label in PATH_LABELS.items() if code in codes), "直接请求")


def _fields(result: dict[str, Any]) -> int:
    checks = (
        bool(result.get("title")),
        bool(result.get("author")),
        result.get("published_at") is not None,
        any(v is not None for v in (result.get("stats") or {}).values()),
        bool(result.get("body_text") or result.get("tags")),
    )
    return sum(checks)


def read_one(service: ReaderService, index: int, url: str) -> BatchItem:
    started = time.monotonic()
    result = service.read_page(url, output="json", caller="batch")
    seconds = round(time.monotonic() - started, 1)
    if result["ok"]:
        return BatchItem(index, url, result["platform"], True, _path(result), seconds,
                         title=result["title"], fields_ok=_fields(result))
    # A failed read has no parsed platform; derive it from the URL itself.
    platform = route(url).platform if url.lower().startswith(("http://", "https://")) else "unknown"
    return BatchItem(index, url, platform, False, "-", seconds,
                     error_code=result["error_code"], message=result["message"])


def run_batch(
    service: ReaderService,
    urls: list[str],
    *,
    workers: int = 3,
    progress: Callable[[BatchItem, int, int], None] | None = None,
) -> list[BatchItem]:
    items: list[BatchItem] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(read_one, service, i, url) for i, url in enumerate(urls, 1)]
        for done, future in enumerate(as_completed(futures), 1):
            item = future.result()
            items.append(item)
            if progress:
                progress(item, done, len(urls))
    return sorted(items, key=lambda it: it.index)


def summarize(items: list[BatchItem]) -> dict[str, Any]:
    total = len(items)
    ok = [it for it in items if it.ok]
    per_platform: dict[str, dict[str, int]] = {}
    for it in items:
        bucket = per_platform.setdefault(it.platform, {"ok": 0, "total": 0})
        bucket["total"] += 1
        bucket["ok"] += int(it.ok)
    return {
        "total": total,
        "ok": len(ok),
        "pass_rate": round(len(ok) / total, 3) if total else 0.0,
        "per_platform": per_platform,
        "per_path": dict(Counter(it.path for it in ok)),
        "errors": dict(Counter(it.error_code for it in items if not it.ok)),
        "field_coverage": round(sum(it.fields_ok for it in ok) / (len(ok) * len(CORE_FIELDS)), 3) if ok else 0.0,
        "avg_seconds": round(sum(it.seconds for it in items) / total, 1) if total else 0.0,
        "max_seconds": max((it.seconds for it in items), default=0.0),
    }


def _cell(text: str, limit: int = 28) -> str:
    text = " ".join(str(text).split()).replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _pct(n: int, d: int) -> str:
    return f"{n}/{d}（{n / d:.0%}）" if d else "0/0"


def format_report(items: list[BatchItem], summary: dict[str, Any]) -> str:
    lines = [
        "| # | 平台 | 结果 | 读取方式 | 字段 | 耗时 | 标题 / 原因 |",
        "|---|---|---|---|---|---|---|",
    ]
    for it in items:
        label = PLATFORM_LABELS.get(it.platform, it.platform)
        if it.ok:
            lines.append(f"| {it.index} | {label} | ✅ | {it.path} | {it.fields_ok}/{len(CORE_FIELDS)} "
                         f"| {it.seconds}s | {_cell(it.title)} |")
        else:
            lines.append(f"| {it.index} | {label} | ❌ {it.error_code} | - | - | {it.seconds}s | {_cell(it.message, 40)} |")
    lines += [
        "",
        f"**通过率：{_pct(summary['ok'], summary['total'])}**",
        "",
        "- 分平台：" + "；".join(
            f"{PLATFORM_LABELS.get(p, p)} {_pct(v['ok'], v['total'])}" for p, v in summary["per_platform"].items()
        ),
        "- 读取方式：" + ("；".join(f"{k} {v}" for k, v in summary["per_path"].items()) or "—"),
        f"- 结构化字段完整率（{'、'.join(CORE_FIELDS)}）：{summary['field_coverage']:.0%}",
        "- 失败原因：" + ("；".join(f"{k} {v}" for k, v in summary["errors"].items()) or "无"),
        f"- 耗时：平均 {summary['avg_seconds']}s，最慢 {summary['max_seconds']}s",
    ]
    return "\n".join(lines) + "\n"


def to_json(items: list[BatchItem], summary: dict[str, Any]) -> dict[str, Any]:
    # Share links carry tokens and device IDs: keep reports safe to forward.
    return {"summary": summary, "items": [{**asdict(it), "url": redact_url(it.url)} for it in items]}
