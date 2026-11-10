"""read_page: URL → validated fetch → platform extractor → checked, cited result."""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime
from typing import Any

from .audit import audit_event, get_logger
from .browser import ChromeRenderer, Renderer, playwright_installed
from .config import Settings
from .extractors import bilibili, douyin, global_social, kuaishou, snapchat, telegram, toutiao, wechat, weibo, xigua, youtube
from .errors import ErrorCode, ReaderError
from .extractors.common import CN_TZ, ReadOptions
from .fetcher import Fetcher
from .models import Extraction, media_to_dict
from .render import render_markdown
from .router import PLATFORM_LABELS, route
from .security import RateLimiter, redact_url, validate_url

log = get_logger("social_reader.service")
OUTPUTS = ("json", "markdown", "both")
SUMMARY_CHARS = 120
_SHARE_URL = re.compile(r"https?://[^\s<>\"'，。！？、；：（）【】《》「」　]+", re.IGNORECASE)
_TRAILING = ".,;:!?)]}>'\""
_TRANSCRIPT_EXTRACTORS = {adapter.VERSION: adapter for adapter in (bilibili, douyin, toutiao)}


def extract_url(text: Any) -> tuple[Any, bool]:
    """Accept a bare URL or a pasted share text ("【标题】… https://… 复制此链接…").

    Returns (url, extracted). Text without any link is passed through so that
    validate_url reports INVALID_URL.
    """
    if not isinstance(text, str):
        return text, False
    stripped = text.strip()
    if stripped.lower().startswith(("http://", "https://")) and not any(c.isspace() for c in stripped):
        return stripped, False
    match = _SHARE_URL.search(stripped)
    if not match:
        return stripped, False
    return match.group(0).rstrip(_TRAILING), True


def find_urls(text: str) -> list[str]:
    """Every link in a pasted block of share texts / URLs, de-duplicated, in order."""
    return list(dict.fromkeys(m.group(0).rstrip(_TRAILING) for m in _SHARE_URL.finditer(text or "")))


def _excerpt(body: str) -> str:
    first = body.strip().split("\n", 1)[0].strip()
    return first if len(first) <= SUMMARY_CHARS else first[:SUMMARY_CHARS].rstrip() + "…"


class ReaderService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        fetcher: Fetcher | None = None,
        limiter: RateLimiter | None = None,
        renderer: Renderer | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.fetcher = fetcher or Fetcher(self.settings)
        self.limiter = limiter or RateLimiter(self.settings.burst_per_minute, self.settings.daily_quota)
        self.renderer = renderer if renderer is not None else self._default_renderer()

    def _default_renderer(self) -> Renderer | None:
        mode = self.settings.browser_fallback
        if mode == "off" or (mode == "auto" and not playwright_installed()):
            return None
        return ChromeRenderer(douyin.HOST_SUFFIXES, timeout_seconds=self.settings.browser_timeout_seconds)

    def read_page(
        self,
        url: str,
        output: str = "both",
        include_media: bool = False,
        include_comments: bool = False,
        include_transcript: bool = False,
        language: str = "zh-CN",
        *,
        caller: str = "default",
    ) -> dict[str, Any]:
        started = time.monotonic()
        result_id = str(uuid.uuid4())
        fetched_at = datetime.now(CN_TZ).isoformat(timespec="seconds")
        output = output if output in OUTPUTS else "both"
        platform = "unknown"
        url, extracted = extract_url(url)
        try:
            self.limiter.check(caller)
            target = validate_url(url, self.settings.allowed_host_suffixes)
            chosen = route(target.url)
            platform = chosen.platform
            options = ReadOptions(include_media, include_comments, include_transcript, language)
            group = toutiao.video_id(target.url) if chosen.extractor is toutiao else None
            # The verified mobile route only needs the work ID, never device/share tokens.
            url = toutiao.canonical_video_url(group) if group else target.url
            if chosen.extractor is wechat:
                url = wechat.public_url(url)
            renderer = self.renderer
            if chosen.extractor is global_social and isinstance(renderer, ChromeRenderer):
                renderer = ChromeRenderer(global_social.HOSTS[chosen.platform], timeout_seconds=self.settings.browser_timeout_seconds)
            extraction, fetched = chosen.extractor.read(
                url, self.fetcher, options, renderer=renderer
            )
            if chosen.pending:
                extraction.platform = chosen.platform
                extraction.confidence = min(extraction.confidence, 0.6)
                extraction.warn(
                    "PLATFORM_PARSER_PENDING",
                    f"{PLATFORM_LABELS[chosen.platform]}专用解析器尚未上线（P1），当前仅用通用网页读取，字段可能不全",
                )
            if fetched.truncated:
                extraction.warn("RESPONSE_TRUNCATED", "页面超过大小上限，只读取了前一部分")
            if extracted:
                extraction.warn("URL_EXTRACTED", "输入是一段分享文字，已从中提取第一个链接读取")
            canonical_extractors = (toutiao, douyin, bilibili, wechat, kuaishou, weibo, xigua, youtube, telegram, snapchat, global_social)
            cited = extraction.canonical_url if chosen.extractor in canonical_extractors else None
            result = self._success(extraction, cited or url, result_id, fetched_at, options, output)
        except ReaderError as error:
            result = self._failure(error, url, result_id, fetched_at)
        except Exception:  # never leak internals; log is redacted at the source
            log.exception("read_page internal error url=%s", url)
            result = self._failure(
                ReaderError(ErrorCode.INTERNAL_ERROR, "服务内部错误，请稍后重试"), url, result_id, fetched_at
            )
        audit_event(
            event="read_page",
            result_id=result_id,
            caller=caller,
            platform=result.get("platform", platform),
            url=redact_url(url) if isinstance(url, str) else "",
            ok=result["ok"],
            error_code=result.get("error_code"),
            extractor_version=result.get("extractor_version"),
            warnings=[w["code"] for w in result.get("warnings", [])],
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return result

    def _success(
        self,
        ex: Extraction,
        source_url: str,
        result_id: str,
        fetched_at: str,
        options: ReadOptions,
        output: str,
    ) -> dict[str, Any]:
        body = ex.body
        limit = self.settings.max_body_chars
        if len(body) > limit:
            body = body[:limit].rstrip() + "…"
            ex.warn("BODY_TRUNCATED", f"正文超过 {limit} 字，已截断，结论可能不完整")
        transcript: dict[str, Any] | None = None
        adapter = _TRANSCRIPT_EXTRACTORS.get(ex.extractor_version)
        if ex.type == "video" and options.include_transcript and adapter is not None:
            try:
                from social_reader_asr import transcribe_video
            except ModuleNotFoundError as error:
                if error.name != "social_reader_asr":
                    raise
                transcript = {
                    "status": "unavailable", "code": "ASR_NOT_INSTALLED",
                    "message": "未安装可选 ASR 后处理组件", "segments": [],
                }
            else:
                transcript = transcribe_video(
                    ex, self.fetcher, options.language, media_hosts=adapter.MEDIA_HOSTS, referer=adapter.REFERER,
                )
        if ex.type == "video" and (transcript is None or transcript["status"] != "ok"):
            ex.warn("VIDEO_NOT_TRANSCRIBED", "视频的口播内容未转写，正文只是作者的文字描述")
            if options.include_transcript:
                ex.warn("TRANSCRIPT_UNAVAILABLE", transcript["message"] if transcript
                        else "此平台暂未接入语音转写")
        if options.include_comments and not ex.comments:
            ex.warn("COMMENTS_UNAVAILABLE", "该页面没有可公开读取的评论")
        if ex.confidence < 0.6:
            ex.warn("LOW_CONFIDENCE", "解析置信度较低，请核对原文")

        result: dict[str, Any] = {
            "ok": True,
            "result_id": result_id,
            "platform": ex.platform,
            "type": ex.type,
            "title": ex.title,
            "summary": _excerpt(body),
            "summary_kind": "excerpt",
            "author": ex.author,
            "published_at": ex.published_at.isoformat() if ex.published_at else None,
            "stats": ex.stats.to_dict(),
            "tags": ex.tags,
            "media": media_to_dict(ex.media, options.include_media),
            "rights_state": ex.rights_state.value,
            "source_url": source_url,
            "canonical_url": ex.canonical_url,
            "extractor_version": ex.extractor_version,
            "fetched_at": fetched_at,
            "confidence": round(ex.confidence, 2),
            "warnings": [w.to_dict() for w in ex.warnings],
            "body_text": body,
        }
        if options.include_comments:
            result["comments"] = [{"content": c.content, "likes": c.likes} for c in ex.comments]
        if transcript is not None:
            result["transcript"] = transcript
        if output in ("markdown", "both"):
            result["body_markdown"] = render_markdown(result)
        if output == "markdown":
            del result["body_text"]
        return result

    @staticmethod
    def _failure(error: ReaderError, url: Any, result_id: str, fetched_at: str) -> dict[str, Any]:
        return {
            "ok": False,
            "result_id": result_id,
            "error_code": error.code.value,
            "message": error.message,
            "rights_state": error.rights_state.value,
            "source_url": url[:2048] if isinstance(url, str) else "",
            "retryable": error.retryable,
            "fetched_at": fetched_at,
        }
