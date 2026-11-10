"""Read public video descriptions from YouTube's watch page."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import DESKTOP_UA, Fetcher, FetchResult
from ..models import Extraction, Media
from ..security import validate_url
from .common import ReadOptions, clean_text, dig, load_js_object
from .htmltext import parse_html

VERSION = "youtube-watch-0.1.0"
HOST_SUFFIXES = ("youtube.com",)
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def video_id(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.hostname == "youtu.be":
        value = parts.path.strip("/")
    elif parts.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"} and parts.path == "/watch":
        values = parse_qs(parts.query).get("v", [])
        value = values[0] if len(values) == 1 else ""
    else:
        return None
    return value if _VIDEO_ID.fullmatch(value) else None


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None) -> tuple[Extraction, FetchResult]:
    work = video_id(url)
    canonical = f"https://www.youtube.com/watch?v={work}"
    fetched = fetcher.fetch(canonical, scope=HOST_SUFFIXES, user_agent=DESKTOP_UA)
    if video_id(fetched.url) != work:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "YouTube 页面没有返回指定视频")
    state = load_js_object(fetched.text, r"\bytInitialPlayerResponse\s*=", what="YouTube")
    status = dig(state, "playabilityStatus", "status")
    if status == "LOGIN_REQUIRED":
        raise ReaderError(ErrorCode.LOGIN_REQUIRED, "YouTube 要求登录后查看该视频")
    info = dig(state, "videoDetails")
    if status != "OK" or not isinstance(info, dict) or info.get("videoId") != work or not info.get("title"):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "YouTube 页面未公开返回该视频信息")
    doc = parse_html(fetched.text)
    try:
        cover = validate_url(doc.meta("og:image"), ("ytimg.com",))
    except ReaderError:
        images = []
    else:
        images = [cover.url] if cover.scheme == "https" and cover.port == 443 else []
    length = info.get("lengthSeconds")
    duration = int(length) * 1000 if isinstance(length, str) and length.isascii() and length.isdecimal() and len(length) <= 8 else 0
    extraction = Extraction(
        platform="youtube", type="video", title=clean_text(info["title"]),
        body=clean_text(info.get("shortDescription") or ""), author=clean_text(info.get("author") or ""),
        media=Media(images=images, duration_ms=duration), canonical_url=canonical,
        extractor_version=VERSION, confidence=0.9,
    )
    extraction.warn("VIDEO_MEDIA_UNAVAILABLE", "已获取作品信息，当前仅支持读取公开页面中的视频简介和封面")
    return extraction, fetched
