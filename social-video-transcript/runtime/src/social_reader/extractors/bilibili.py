"""Read a public Bilibili video and the selected part's anonymous DASH audio."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import DESKTOP_UA, Fetcher, FetchResult
from ..models import Extraction, Media, Stats
from ..security import validate_url
from .common import ReadOptions, clean_text, dig, from_epoch

HOST_SUFFIXES = ("bilibili.com", "b23.tv")
MEDIA_HOSTS = ("bilivideo.com", "bilivideo.cn")
API_HOSTS = ("api.bilibili.com",)
REFERER = "https://www.bilibili.com/"
VERSION = "bilibili-dash-0.1.0"
_WORK = re.compile(r"/video/(BV[A-Za-z0-9]{10}|av[0-9]{1,18})/?")
_BV = re.compile(r"BV[A-Za-z0-9]{10}")
_SHORT = re.compile(r"/[A-Za-z0-9]{3,30}/?")


def _work(url: str) -> str | None:
    match = _WORK.fullmatch(urlsplit(url).path)
    return match[1] if match else None


def is_video_link(url: str) -> bool:
    parts = urlsplit(url)
    return bool(_work(url) or (parts.hostname == "b23.tv" and _SHORT.fullmatch(parts.path)))


def _int(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _text(value: object) -> str:
    return clean_text(value) if isinstance(value, str) else ""


def _api(fetcher: Fetcher, endpoint: str, params: dict, *, referer: str) -> tuple[dict, FetchResult]:
    result = fetcher.fetch(
        f"https://{API_HOSTS[0]}{endpoint}?{urlencode(params)}",
        referer=referer, user_agent=DESKTOP_UA, scope=API_HOSTS,
    )
    try:
        payload = json.loads(result.text)
    except ValueError:
        raise ReaderError(ErrorCode.PARSE_CHANGED, "B站未返回有效的播放器数据") from None
    code = dig(payload, "code")
    data = dig(payload, "data")
    if code in (-352, -412):
        raise ReaderError(ErrorCode.FETCH_BLOCKED, "B站要求访问验证，已停止读取")
    if code == -101:
        raise ReaderError(ErrorCode.LOGIN_REQUIRED, "B站要求登录后访问")
    if code in (-403, -10403, -10402):
        raise ReaderError(ErrorCode.PERMISSION_REQUIRED, "该 B站视频没有开放所请求的内容")
    if code in (-404, 62002, 62004):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "B站视频不存在或不可公开访问")
    if code != 0 or not isinstance(data, dict):
        raise ReaderError(ErrorCode.PARSE_CHANGED, "B站未提供可用的作品数据")
    return data, result


def _audio(data: dict, duration: int) -> str | None:
    length = _int(data.get("timelength"))
    if data.get("is_preview") or data.get("preview") or (length is not None and length < duration * 1000 - 2500):
        raise ReaderError(ErrorCode.PREVIEW_ONLY, "B站只提供试看，已停止读取音轨")
    variants = dig(data, "dash", "audio")
    if not isinstance(variants, list):
        return None
    candidates = []
    for variant in variants:
        if dig(variant, "mimeType") not in (None, "audio/mp4"):
            continue
        raw = dig(variant, "baseUrl") or dig(variant, "base_url")
        try:
            target = validate_url(raw, MEDIA_HOSTS)
        except ReaderError:
            continue
        if target.scheme == "https" and target.port == 443:
            candidates.append((_int(dig(variant, "bandwidth")) or 10**9, target.url))
    return min(candidates)[1] if candidates else None


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None) -> tuple[Extraction, FetchResult]:
    if urlsplit(url).hostname == "b23.tv":
        url = fetcher.resolve_redirect(url, scope=HOST_SUFFIXES, stop_at=lambda u: bool(_work(u)))
    work = _work(url)
    if not work or urlsplit(url).hostname == "b23.tv":
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "B站链接未指向可识别的公开视频")
    p_values = parse_qs(urlsplit(url).query, keep_blank_values=True).get("p", ["1"])
    if len(p_values) != 1 or not re.fullmatch(r"[1-9][0-9]{0,3}", p_values[0]):
        raise ReaderError(ErrorCode.INVALID_URL, "B站分P编号无效")
    page = int(p_values[0])
    is_av = work.startswith("av")
    data, fetched = _api(
        fetcher, "/x/web-interface/view", {"aid": int(work[2:])} if is_av else {"bvid": work},
        referer=REFERER,
    )
    bvid = _text(data.get("bvid"))
    if not _BV.fullmatch(bvid) or (data.get("aid") != int(work[2:]) if is_av else bvid != work):
        raise ReaderError(ErrorCode.PARSE_CHANGED, "B站返回的作品与链接不一致")
    pages = data.get("pages")
    if not isinstance(pages, list):
        raise ReaderError(ErrorCode.PARSE_CHANGED, "B站未返回作品分P信息")
    part = next((entry for entry in pages if dig(entry, "page") == page), None)
    cid = _int(dig(part, "cid"))
    if not cid:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "没有找到所选的 B站分P")
    duration = _int(dig(part, "duration"))
    if not duration:
        raise ReaderError(ErrorCode.PARSE_CHANGED, "B站未返回所选分P的时长")
    rights = data.get("rights") or {}
    if any(dig(rights, field) for field in ("pay", "ugc_pay", "arc_pay", "bp", "ugc_pay_preview")):
        raise ReaderError(ErrorCode.PERMISSION_REQUIRED, "该 B站作品需要付费或权限，已停止读取")
    if dig(rights, "is_stein_gate"):
        raise ReaderError(ErrorCode.UNSUPPORTED_PLATFORM, "原型不读取 B站互动视频分支")
    canonical = f"{REFERER}video/{bvid}/" + (f"?p={page}" if page != 1 else "")
    title = _text(data.get("title"))
    if len(pages) > 1:
        title = f"{title} · P{page} {_text(dig(part, 'part'))}".strip()
    result = Extraction(
        platform="bilibili", type="video", title=title, body=_text(data.get("desc")),
        extractor_version=VERSION, canonical_url=canonical, confidence=0.95,
        author=_text(dig(data, "owner", "name")),
        published_at=from_epoch(_int(data.get("pubdate")), millis=False),
        stats=Stats(*(_int(dig(data, "stat", key)) for key in ("like", "favorite", "reply", "share"))),
        media=Media(cover_url=data.get("pic"), duration_ms=duration * 1000),
    )
    if options.include_media or options.include_transcript:
        play, _ = _api(
            fetcher, "/x/player/playurl", {"bvid": bvid, "cid": cid, "fnval": 16}, referer=canonical,
        )
        result.media.audio_url = _audio(play, duration)
        if not result.media.audio_url:
            result.warn("MEDIA_UNAVAILABLE", "B站没有提供可处理的公开 DASH 音轨")
    return result, fetched
