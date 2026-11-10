"""Read descriptions from public Xigua video pages."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import Fetcher, FetchResult
from ..models import Extraction, Media
from ..security import validate_url
from .common import ReadOptions, clean_text, detect_wall, dig, from_epoch, load_js_object
from .htmltext import parse_html

VERSION = "xigua-detail-0.1.0"
HOST_SUFFIXES = ("ixigua.com",)
_WORK_PATH = re.compile(r"/(?:(video|dx)/)?([0-9]{19})/?")


def work(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    match = _WORK_PATH.fullmatch(parts.path)
    if match and parts.hostname in {"ixigua.com", "www.ixigua.com", "m.ixigua.com"}:
        return match[1] or "video", match[2]
    return None


def is_video_link(url: str) -> bool:
    return work(url) is not None or urlsplit(url).hostname == "v.ixigua.com"


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None) -> tuple[Extraction, FetchResult]:
    item = work(url)
    if item is None:
        landing = fetcher.resolve_redirect(url, scope=HOST_SUFFIXES, stop_at=lambda link: work(link) is not None)
        item = work(landing)
    if item is None:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "西瓜视频短链未跳转到具体作品，请提供作品直链")
    kind, gid = item
    canonical = f"https://m.ixigua.com/{kind}/{gid}"
    fetched = fetcher.fetch(canonical, scope=HOST_SUFFIXES)
    if work(fetched.url) != item:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "西瓜视频页面没有返回指定作品")
    state = load_js_object(fetched.text, r"window\._SSR_DATA\s*=", what="西瓜视频")
    detail = dig(state, "data", "storeState", "detail")
    if dig(detail, "isForbiden", "result") is True:
        raise ReaderError(ErrorCode.PERMISSION_REQUIRED, "西瓜视频页面限制访问该作品")
    video = dig(detail, "videoData", "result")
    if not isinstance(video, dict) or str(video.get("gid")) != gid or not video.get("title"):
        doc = parse_html(fetched.text)
        if wall := detect_wall(doc.text(), has_password=doc.has_password_input):
            raise wall
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "西瓜视频页面未公开返回该作品信息")
    try:
        cover = validate_url(video.get("cover_image_url"), ("douyinpic.com", "bdxiguaimg.com"))
    except ReaderError:
        images = []
    else:
        images = [cover.url] if cover.scheme == "https" and cover.port == 443 else []
    seconds = video.get("duration")
    duration_ms = round(seconds * 1000) if type(seconds) in (int, float) and 0 < seconds < 86400 else 0
    extraction = Extraction(
        platform="xigua", type="video", title=clean_text(video["title"]),
        body=clean_text(video.get("abstract") or ""), author=clean_text(dig(video, "media_user", "screen_name") or ""),
        published_at=from_epoch(video.get("publish_time"), millis=False),
        media=Media(images=images, duration_ms=duration_ms),
        canonical_url=canonical, extractor_version=VERSION, confidence=0.9,
    )
    extraction.warn("VIDEO_MEDIA_UNAVAILABLE", "已获取作品信息，页面没有公开直出的音视频地址")
    return extraction, fetched
