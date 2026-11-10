"""Public Toutiao video: mobile RENDER_DATA → signed GetPlayInfo → MP4."""

from __future__ import annotations

import base64
import json
import re
from urllib.parse import parse_qsl, unquote, urlsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import Fetcher, FetchResult
from ..models import Extraction, Media, Stats
from ..security import validate_url
from .common import ReadOptions, clean_text, detect_wall, dig, from_epoch
from .htmltext import visible_text

HOST_SUFFIXES = ("toutiao.com",)
MEDIA_HOSTS = ("toutiaovod.com",)
VOD_HOSTS = ("vod.bytedanceapi.com",)
REFERER = "https://www.toutiao.com/"
VERSION = "toutiao-mobile-0.1.0"
_PATH = re.compile(r"/video/([0-9]{15,22})/?")
_SHORT = re.compile(r"/is/[A-Za-z0-9_-]{3,32}/?")
_RENDER = re.compile(r"""<script\b[^>]*\bid=["']RENDER_DATA["'][^>]*>(.*?)</script>""", re.I | re.S)


def video_id(url: str) -> str | None:
    match = _PATH.fullmatch(urlsplit(url).path)
    return match[1] if match else None


def canonical_video_url(group: str) -> str:
    return f"{REFERER}video/{group}/"


def is_short(url: str) -> bool:
    parts = urlsplit(url)
    return (parts.hostname == "m.toutiao.com" and bool(_SHORT.fullmatch(parts.path))
            or parts.hostname == "open.toutiao.com" and parts.path not in {"", "/"})


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _count(value: object) -> int | None:
    text = str(value) if type(value) in (int, str) else ""
    return int(text) if re.fullmatch(r"[0-9]{1,15}", text) else None


def _media_url(article: dict, fetcher: Fetcher) -> tuple[str | None, bool]:
    """Return (MP4, identity verified); mismatched VOD is never used."""
    play_token = _string(article.get("playAuthTokenV2"))
    expected = _string(article.get("videoId"))
    if not play_token or not expected:
        return None, False
    try:
        token = json.loads(base64.b64decode(play_token, validate=True))
        query = _string(dig(token, "GetPlayInfoToken"))
        items = parse_qsl(query, keep_blank_values=True, max_num_fields=32)
        params = dict(items)
        if (len(params) != len(items) or params.get("Action") != "GetPlayInfo"
                or params.get("video_id") != expected or "#" in query):
            return None, False
        response = fetcher.fetch(
            f"https://{VOD_HOSTS[0]}/?{query}", referer=REFERER, scope=VOD_HOSTS,
        )
        data = dig(json.loads(response.text), "Result", "Data")
    except (ValueError, ReaderError):
        return None, False
    if dig(data, "VideoID") != expected:
        return None, False

    variants = dig(data, "PlayInfoList")
    if not isinstance(variants, list):
        return None, True
    candidates: list[tuple[int, str]] = []
    for variant in variants:
        if dig(variant, "Format") != "mp4":
            continue
        try:
            target = validate_url(_string(dig(variant, "MainPlayUrl")), MEDIA_HOSTS)
        except ReaderError:
            continue
        if target.scheme == "https" and target.port == 443:
            bitrate = _count(dig(variant, "Bitrate"))
            candidates.append((bitrate or 0, target.url))
    # A lower-bitrate rendition keeps audio extraction cheap.
    return (min(candidates)[1] if candidates else None), True


def read(
    url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None,
) -> tuple[Extraction, FetchResult]:
    group = video_id(url)
    if not group and is_short(url):
        landing = fetcher.resolve_redirect(
            url, scope=HOST_SUFFIXES,
            stop_at=lambda u: bool(video_id(u)) or urlsplit(u).path.startswith(("/article/", "/w/")),
        )
        group = video_id(landing)
        if not group:
            code = ErrorCode.CONTENT_NOT_FOUND if is_short(landing) else ErrorCode.UNSUPPORTED_PLATFORM
            raise ReaderError(code, "头条短链未跳转到公开视频（可能已失效，或指向图文）")
    if not group:
        raise ReaderError(ErrorCode.UNSUPPORTED_PLATFORM, "此原型只支持头条 /video/ 作品直链")
    canonical = canonical_video_url(group)
    fetched = fetcher.fetch(
        f"https://m.toutiao.com/video/{group}/", referer=REFERER, scope=HOST_SUFFIXES,
    )
    match = _RENDER.search(fetched.text)
    if not match:
        if "_$jsvmprt" in fetched.text:
            raise ReaderError(ErrorCode.FETCH_BLOCKED, "头条返回访问验证页，已停止读取")
        wall = detect_wall(visible_text(fetched.text))
        if wall:
            raise wall
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "头条移动页没有提供该视频的数据")
    try:
        article = dig(json.loads(unquote(match[1])), "articleInfo")
    except ValueError:
        raise ReaderError(ErrorCode.PARSE_CHANGED, "头条移动页数据无法解析") from None
    if not isinstance(article, dict) or str(article.get("gid")) != group:
        raise ReaderError(ErrorCode.PARSE_CHANGED, "头条页面作品 ID 与链接不一致")
    title = clean_text(_string(article.get("title")))
    if not title:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "头条移动页没有提供该视频的标题")

    seconds = _count(article.get("videoDuration"))
    published = _count(article.get("publishTime"))
    result = Extraction(
        platform="toutiao", type="video", title=title,
        body=visible_text(_string(article.get("content"))) or title,
        extractor_version=VERSION, canonical_url=canonical,
        author=clean_text(_string(dig(article, "mediaUser", "screenName")) or _string(article.get("source"))),
        published_at=from_epoch(published, millis=False) if published and published < 32_503_680_000 else None,
        stats=Stats(*(_count(article.get(key))
                      for key in ("diggCount", "repinCount", "commentCount", "repostCount"))),
        media=Media(duration_ms=(seconds or 0) * 1000),
        confidence=0.95,
    )
    if options.include_media or options.include_transcript:
        result.media.video_url, verified = _media_url(article, fetcher)
        if not result.media.video_url:
            result.warn("MEDIA_UNAVAILABLE", "未取得与该作品匹配的头条 MP4 播放地址"
                        if not verified else "头条未提供可处理的 MP4 播放地址")
    return result, fetched
