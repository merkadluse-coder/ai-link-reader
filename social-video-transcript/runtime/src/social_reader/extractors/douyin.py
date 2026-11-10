"""Douyin videos and image notes via the public mobile share page.

Reads window._ROUTER_DATA from www.iesdouyin.com/share/{video|note}/{id}/
(spec §5.3). Since 2026-10 the share page only server-renders the work for a
browser that holds a normal web session (set by Douyin's own security script),
so a plain HTTP fetch gets the "抱歉出错了" template. In that case, like the
Android app's WebView, we render the same public share page in the local
Chrome (browser.ChromeRenderer: fresh incognito session, no stealth, stop on
any verification). No private API, signature forging or "WAF bypass" route is
used; the reference doc's jingxuan?modal_id= trick is deliberately NOT ported.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..browser import BrowserUnavailable, Renderer
from ..errors import ErrorCode, ReaderError
from ..fetcher import MOBILE_UA, FetchResult, Fetcher
from ..models import Extraction, Media, Stats
from ..security import host_matches
from .common import (
    ReadOptions, clean_text, detect_wall, dig, from_epoch, load_js_object, parse_count,
)
from .htmltext import parse_html

VERSION = "douyin-0.1.0"
HOST_SUFFIXES = ("douyin.com", "iesdouyin.com")
MEDIA_HOSTS = ("aweme.snssdk.com", "douyinvod.com")
REFERER = "https://www.iesdouyin.com/"
_MARKER = r"window\._ROUTER_DATA\s*="
_ID_PATTERNS = [
    re.compile(r"/(?:video|note|slides)/(\d{10,20})"),
    re.compile(r"/share/(?:video|note|slides)/(\d{10,20})"),
    re.compile(r"[?&](?:modal_id|aweme_id|item_id|vid)=(\d{10,20})"),
]
_HASHTAG = re.compile(r"#([^\s#]+)")
_CHALLENGE_MARKERS = ("__ac_nonce", "__ac_signature", "byted_acrawler", "captcha")
_APP_ONLY_TEXT = ("请尝试在抖音内观看", "抱歉出错了")


class NotServed(ReaderError):
    """The share page rendered, but Douyin chose not to include the work's data.

    Seen live on 2026-10-29: _ROUTER_DATA carries only page config and the body
    says "请尝试在抖音内观看". Not a parser bug, so not PARSE_CHANGED.
    """


def extract_id(url: str) -> str | None:
    for pattern in _ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def _can_try_next(error: ReaderError) -> bool:
    # Anti-bot challenges and other hard stops are never retried around.
    return isinstance(error, NotServed) or error.code in (ErrorCode.PARSE_CHANGED, ErrorCode.CONTENT_NOT_FOUND)


def read(
    url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: Renderer | None = None
) -> tuple[Extraction, FetchResult]:
    errors: list[ReaderError] = []
    tried_paths: set[str] = set()
    aweme_id = extract_id(url)
    if aweme_id is None and host_matches(urlsplit(url).hostname or "", ("v.douyin.com",)):
        # App share short link: read the exact page it lands on first (with its own
        # share parameters), following redirects that are SSRF-checked hop by hop.
        landing = fetcher.fetch(url, user_agent=MOBILE_UA, scope=HOST_SUFFIXES)
        aweme_id = extract_id(landing.url)
        tried_paths.add(urlsplit(landing.url).path.rstrip("/"))
        try:
            return parse(landing.text, source_url=url, options=options, expected_id=aweme_id), landing
        except ReaderError as error:
            if aweme_id is None or not _can_try_next(error):
                raise
            errors.append(error)
    if aweme_id is None:
        raise ReaderError(ErrorCode.INVALID_URL, "无法从链接中识别抖音作品 ID，请使用作品分享链接")

    kinds = ["note", "video"] if "/note/" in url or "/slides/" in url else ["video", "note"]
    for kind in kinds:
        path = f"/share/{kind}/{aweme_id}"
        if path in tried_paths:
            continue
        result = fetcher.fetch(f"https://www.iesdouyin.com{path}/", user_agent=MOBILE_UA, scope=HOST_SUFFIXES)
        try:
            return parse(result.text, source_url=url, options=options, expected_id=aweme_id), result
        except ReaderError as error:
            if not _can_try_next(error):
                raise
            errors.append(error)  # the other share-page kind may still serve it; try once
    if renderer is not None and any(isinstance(e, NotServed) for e in errors):
        try:
            return _read_rendered(url, aweme_id, kinds, renderer, options)
        except BrowserUnavailable:
            pass  # no local browser: report the HTTP result below
    # Report an explicit platform signal over a generic "structure changed".
    raise next((e for e in errors if e.code is not ErrorCode.PARSE_CHANGED), errors[-1])


def _read_rendered(
    url: str, aweme_id: str, kinds: list[str], renderer: Renderer, options: ReadOptions
) -> tuple[Extraction, FetchResult]:
    last: ReaderError | None = None
    for kind in kinds:
        share_url = f"https://www.iesdouyin.com/share/{kind}/{aweme_id}/"
        html = renderer.render(share_url, ready=lambda page: '"videoInfoRes"' in page)
        try:
            extraction = parse(html, source_url=url, options=options, expected_id=aweme_id)
        except NotServed as error:
            last = error
            continue
        extraction.warn(
            "BROWSER_RENDERED",
            "抖音分享页只向有正常网页会话的浏览器直出数据，本次用本机 Chrome 无痕会话渲染读取"
            "（与原 App 的 WebView 方式相同），会话用后即丢弃",
        )
        return extraction, FetchResult(url=share_url, status=200, content_type="text/html", text=html)
    assert last is not None
    raise last


def parse(
    html: str, *, source_url: str, options: ReadOptions, expected_id: str | None = None
) -> Extraction:
    data = load_js_object(html, _MARKER, what="抖音")
    if data is None:
        if re.search(_MARKER, html):
            raise ReaderError(
                ErrorCode.FETCH_BLOCKED, "抖音页面数据不完整（可能被截断），请稍后重试", retryable=True
            )
        if any(marker in html for marker in _CHALLENGE_MARKERS):
            raise ReaderError(ErrorCode.FETCH_BLOCKED, "抖音返回了反爬验证页，已停止读取（不做任何绕过）")
        doc = parse_html(html)
        wall = detect_wall("\n".join(filter(None, [doc.title, doc.text()])), has_password=doc.has_password_input)
        if wall:
            raise wall
        raise ReaderError(ErrorCode.PARSE_CHANGED, "未找到抖音数据 _ROUTER_DATA，页面结构可能已变化")

    loader = data.get("loaderData") if isinstance(data.get("loaderData"), dict) else {}
    info = next(
        (v["videoInfoRes"] for v in loader.values() if isinstance(v, dict) and isinstance(v.get("videoInfoRes"), dict)),
        None,
    )
    if info is None:
        config_only = any(isinstance(v, dict) and "itemId" in v for v in loader.values())
        if "aweme_id" not in html and (config_only or any(t in html for t in _APP_ONLY_TEXT)):
            raise NotServed(
                ErrorCode.FETCH_BLOCKED,
                "抖音分享页未提供作品数据（页面提示“请尝试在抖音内观看”）。"
                "按合规要求不模拟私有接口、不绕过风控，暂时无法读取该作品",
                retryable=False,
            )
        raise ReaderError(ErrorCode.PARSE_CHANGED, "抖音页面结构已变化：未找到 videoInfoRes")
    items = info.get("item_list") or []
    if not items or not isinstance(items[0], dict):
        reason = dig(info, "filter_list", 0, "detail_msg") or dig(info, "filter_list", 0, "filter_reason")
        suffix = f"（{reason}）" if reason else ""
        raise ReaderError(
            ErrorCode.CONTENT_NOT_FOUND, f"作品不可读取{suffix}：可能已删除、设为私密或仅部分用户可见"
        )
    item = items[0]
    found_id = str(item.get("aweme_id") or "")
    if ((expected_id and found_id and found_id != expected_id)
            or (options.include_transcript and (not expected_id or found_id != expected_id))):
        raise ReaderError(ErrorCode.PARSE_CHANGED, "页面返回的作品与链接中的作品 ID 不一致，已停止读取")

    is_note = item.get("aweme_type") == 2
    desc = clean_text(str(item.get("desc") or ""))
    headline = clean_text(_HASHTAG.sub("", desc)).split("\n", 1)[0][:50]
    aweme_id = str(item.get("aweme_id") or "")

    stats_raw = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
    stats = Stats(
        likes=parse_count(stats_raw.get("digg_count"))[0],
        collects=parse_count(stats_raw.get("collect_count"))[0],
        comments=parse_count(stats_raw.get("comment_count"))[0],
        shares=parse_count(stats_raw.get("share_count"))[0],
    )

    tags = [
        str(t["hashtag_name"]).strip()
        for t in item.get("text_extra") or []
        if isinstance(t, dict) and t.get("hashtag_name")
    ] or [m.group(1) for m in _HASHTAG.finditer(desc)]

    images: list[str] = []
    video_url = cover_url = None
    duration = 0
    if is_note:
        for img in item.get("images") or []:
            urls = dig(img, "url_list") or []
            if urls:
                images.append(str(urls[-1]))  # last entry is usually the JPEG variant
    else:
        video_url = dig(item, "video", "play_addr", "url_list", 0) or None
        cover_url = dig(item, "video", "cover", "url_list", 0) or None
        duration = int(dig(item, "video", "duration") or 0)

    extraction = Extraction(
        platform="douyin",
        type="note" if is_note else "video",
        title=headline or (f"抖音作品 {aweme_id}" if aweme_id else "抖音作品"),
        body=desc,
        extractor_version=VERSION,
        author=clean_text(str(dig(item, "author", "nickname") or "")),
        published_at=from_epoch(item.get("create_time"), millis=False),
        stats=stats,
        tags=list(dict.fromkeys(tags)),
        media=Media(images=images, video_url=video_url, cover_url=cover_url, duration_ms=duration),
        canonical_url=f"https://www.douyin.com/{'note' if is_note else 'video'}/{aweme_id}" if aweme_id else None,
        confidence=0.9 if desc and dig(item, "author", "nickname") else 0.7,
    )
    if not desc:
        extraction.warn("EMPTY_TEXT", "作品没有文字描述，正文为空")
    return extraction
