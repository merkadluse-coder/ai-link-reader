"""Read a public Snapchat Spotlight video and its own linked media."""

from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import DESKTOP_UA, Fetcher, FetchResult
from ..models import Extraction, Media
from ..security import validate_url
from .common import ReadOptions, clean_text, dig
from .htmltext import parse_html

VERSION = "snapchat-spotlight-0.1.0"
HOST_SUFFIXES = ("snapchat.com",)
MEDIA_HOSTS = ("sc-cdn.net",)
REFERER = "https://www.snapchat.com/"
_SPOTLIGHT_PATH = re.compile(r"/(?:@[A-Za-z0-9_.-]+/)?spotlight/([A-Za-z0-9_-]{12,120})/?")
_DURATION = re.compile(r"PT(?:(\d{1,3})M)?(\d{1,3}(?:\.\d{1,6})?)S")


def video_id(url: str) -> str | None:
    parts = urlsplit(url)
    match = _SPOTLIGHT_PATH.fullmatch(parts.path)
    return match[1] if match and parts.hostname in {"snapchat.com", "www.snapchat.com"} else None


def _https_url(raw: str | None, hosts: tuple[str, ...]) -> str | None:
    try:
        target = validate_url(raw, hosts)
    except ReaderError:
        return None
    return target.url if target.scheme == "https" and target.port == 443 else None


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None) -> tuple[Extraction, FetchResult]:
    work = video_id(url)
    fetched = fetcher.fetch(f"{REFERER}spotlight/{work}", scope=HOST_SUFFIXES, user_agent=DESKTOP_UA)
    if video_id(fetched.url) != work:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "Snapchat 页面没有返回指定 Spotlight 作品")
    doc = parse_html(fetched.text)
    for item in doc.jsonld:
        try:
            video = json.loads(item)
        except json.JSONDecodeError:
            continue
        if not isinstance(video, dict) or video.get("@type") != "VideoObject":
            continue
        page_url = _https_url(video.get("url"), HOST_SUFFIXES)
        if not page_url or video_id(page_url) != work:
            continue
        title = video.get("name")
        if not isinstance(title, str) or not title.strip():
            continue
        page = urlsplit(page_url)
        canonical = urlunsplit(("https", page.netloc, page.path, "", ""))
        cover = _https_url(video.get("thumbnailUrl"), (*HOST_SUFFIXES, *MEDIA_HOSTS))
        media = _https_url(video.get("contentUrl"), MEDIA_HOSTS)
        seconds = _DURATION.fullmatch(str(video.get("duration") or ""))
        duration = round((int(seconds[1] or 0) * 60 + float(seconds[2])) * 1000) if seconds else 0
        try:
            published = datetime.fromisoformat(str(video.get("uploadDate") or ""))
        except ValueError:
            published = None
        result = Extraction(
            platform="snapchat", type="video", title=clean_text(title),
            body=clean_text(str(video.get("description") or "")),
            author=clean_text(str(dig(video, "creator", "name") or "")), published_at=published,
            media=Media(images=[cover] if cover else [], video_url=media, duration_ms=duration),
            canonical_url=canonical, extractor_version=VERSION, confidence=0.9,
        )
        if not media:
            result.warn("VIDEO_MEDIA_UNAVAILABLE", "Spotlight 页面未提供可用的音视频地址")
        return result, fetched
    raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "Spotlight 页面未公开返回该作品信息")
