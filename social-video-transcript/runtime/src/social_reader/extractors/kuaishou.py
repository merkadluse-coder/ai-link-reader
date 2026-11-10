"""Read public Kuaishou videos through the mobile share page."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import Fetcher, FetchResult
from ..models import Extraction, Media, Stats
from ..security import validate_url
from .common import ReadOptions, clean_text, detect_wall, from_epoch, load_js_object, parse_count
from .htmltext import parse_html

HOST_SUFFIXES = ("kuaishou.com", "gifshow.com")
MEDIA_HOSTS = ("kwimgs.com",)
VERSION = "kuaishou-mobile-0.1.0"
REFERER = "https://m.kuaishou.com/"
_VIDEO_PATH = re.compile(r"/(?:short-video|fw/photo)/([a-zA-Z0-9]{6,32})/?")
_SHORT_HOSTS = {"v.kuaishou.com", "s.kuaishou.com"}
_SHARE_REDIRECT_HOST = "kph1tf76.m.chenzhongtech.com"


def video_id(url: str) -> str | None:
    parts = urlsplit(url)
    match = _VIDEO_PATH.fullmatch(parts.path)
    if match and parts.hostname in {"kuaishou.com", "www.kuaishou.com", "m.kuaishou.com", "m.gifshow.com"}:
        return match[1]
    return None


def is_video_link(url: str) -> bool:
    return video_id(url) is not None or urlsplit(url).hostname in _SHORT_HOSTS


def _cdn_url(items: object) -> str | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            target = validate_url(item.get("url"), MEDIA_HOSTS)
        except ReaderError:
            continue
        if target.scheme == "https" and target.port == 443:
            return target.url
    return None


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None) -> tuple[Extraction, FetchResult]:
    work = video_id(url)
    if work is None:
        # This share redirect carries the public work ID. Read the work on the main site.
        landing = fetcher.resolve_redirect(
            url, scope=(*HOST_SUFFIXES, _SHARE_REDIRECT_HOST),
            stop_at=lambda link: video_id(link) is not None or urlsplit(link).hostname == _SHARE_REDIRECT_HOST,
        )
        work = video_id(landing)
        if work is None and urlsplit(landing).hostname == _SHARE_REDIRECT_HOST:
            match = _VIDEO_PATH.fullmatch(urlsplit(landing).path)
            work = match[1] if match else None
    if work is None:
        raise ReaderError(ErrorCode.UNSUPPORTED_PLATFORM, "快手分享链接没有跳转到公开视频作品")

    fetched = fetcher.fetch(f"{REFERER}fw/photo/{work}", referer=REFERER, scope=HOST_SUFFIXES)
    if video_id(fetched.url) != work:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "快手页面没有保留所请求的作品")
    state = load_js_object(fetched.text, r"window\.INIT_STATE\s*=", what="快手") or {}
    doc = parse_html(fetched.text)
    for record in state.values():
        if not isinstance(record, dict) or record.get("result") != 1:
            continue
        photo = record.get("photo")
        if not isinstance(photo, dict) or photo.get("photoType") != "VIDEO":
            continue
        share = photo.get("share_info")
        share_ids = parse_qs(share).get("photoId", []) if isinstance(share, str) else []
        if work != photo.get("photoId") and share_ids != [work]:
            continue
        video = _cdn_url(photo.get("mainMvUrls"))
        if not video:
            continue
        caption = clean_text(photo["caption"]) if isinstance(photo.get("caption"), str) else ""
        duration = photo.get("duration")
        return Extraction(
            platform="kuaishou", type="video", title=caption.split("\n", 1)[0] or doc.title or "快手视频",
            body=caption, author=str(photo.get("userName") or ""), extractor_version=VERSION,
            published_at=from_epoch(photo.get("timestamp"), millis=True),
            stats=Stats(likes=parse_count(photo.get("likeCount"))[0],
                        comments=parse_count(photo.get("commentCount"))[0],
                        shares=parse_count(photo.get("shareCount"))[0]),
            media=Media(video_url=video, cover_url=_cdn_url(photo.get("coverUrls")),
                        duration_ms=duration if type(duration) is int and duration > 0 else 0),
            canonical_url=f"https://www.kuaishou.com/short-video/{work}", confidence=0.95,
        ), fetched
    wall = detect_wall(doc.text(), has_password=doc.has_password_input)
    if wall:
        raise wall
    raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "快手页面没有所请求作品的公开视频地址")
