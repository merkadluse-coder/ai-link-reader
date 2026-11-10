"""Xiaohongshu (RED) notes via window.__INITIAL_STATE__.

Supports the mobile share layout (noteData.data.noteData, as used by the
Android app) and the desktop web layout (note.noteDetailMap[id].note).

Verified 2026-10-29: for some notes the mobile web page is redirected to
/404/sec_* ("当前内容仅支持在小红书 APP 内查看") while the desktop web page shows
the same note to any visitor without login. In that case we read the desktop
page, a plain public request with a desktop browser UA; nothing is bypassed.
"""

from __future__ import annotations

import re
from typing import Any

from ..errors import ErrorCode, ReaderError
from ..fetcher import DESKTOP_UA, MOBILE_UA, FetchResult, Fetcher
from ..models import Comment, Extraction, Media, Stats
from .common import (
    ReadOptions, clean_text, detect_wall, dig, from_epoch, load_js_object, parse_count,
)
from .htmltext import parse_html

VERSION = "xhs-0.1.0"
HOST_SUFFIXES = ("xiaohongshu.com", "xhslink.com")
_MARKER = r"window\.__INITIAL_STATE__\s*="
_TOPIC = re.compile(r"#([^#\[\]\n]+)\[话题\]#")
MAX_COMMENTS = 20
_APP_ONLY_TEXT = ("仅支持在小红书 APP 内查看", "仅支持在小红书APP内查看", "请在小红书App内查看")


def _app_only(state: dict | None, html: str) -> bool:
    """Seen live 2026-10-29: web requests redirected to /404/sec_* (xhs_sec_server)."""
    return any(t in html for t in _APP_ONLY_TEXT) or (
        dig(state, "noteData", "routeQuery", "source") == "xhs_sec_server"
    )


class AppOnly(ReaderError):
    """Mobile web says the note is App-only; the desktop page may still show it."""


_NOTE_ID = re.compile(r"/(?:explore|discovery/item)/([0-9a-fA-F]{24})")


def note_id_from(url: str) -> str | None:
    match = _NOTE_ID.search(url)
    return match.group(1) if match else None


def _app_only_error() -> ReaderError:
    return AppOnly(
        ErrorCode.FETCH_BLOCKED,
        "小红书未向网页端提供该笔记（页面提示“当前内容仅支持在小红书 APP 内查看”）。"
        "按合规要求不绕过平台限制，暂时无法读取；重新分享通常也无法解决",
        retryable=False,
    )


def read(
    url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None
) -> tuple[Extraction, FetchResult]:
    # xhslink.com short links are followed by the fetcher, re-validating every hop.
    result = fetcher.fetch(url, user_agent=MOBILE_UA)
    note_url = next((u for u in [url, *result.redirects, result.url] if note_id_from(u)), url)
    expected = note_id_from(note_url)
    try:
        return parse(result.text, source_url=url, options=options, expected_id=expected), result
    except AppOnly as app_only:
        desktop = fetcher.fetch(note_url, user_agent=DESKTOP_UA)
        try:
            extraction = parse(desktop.text, source_url=url, options=options, expected_id=expected)
        except ReaderError as desktop_error:
            # A clear desktop-side reason (e.g. login required) beats a generic one.
            raise app_only if desktop_error.code is ErrorCode.PARSE_CHANGED else desktop_error
        extraction.warn("DESKTOP_PAGE", "小红书手机网页提示“仅支持在 App 内查看”，已改读同一笔记的电脑网页版")
        if options.include_comments and not extraction.comments:
            extraction.warn("COMMENTS_UNAVAILABLE", "电脑网页版不直接返回评论（需登录后由页面加载），本次未包含评论")
        return extraction, desktop


def _unavailable() -> ReaderError:
    return ReaderError(
        ErrorCode.CONTENT_NOT_FOUND,
        "笔记无法读取：链接可能已过期（xsec_token 失效）或笔记已删除，请在小红书重新分享获取新链接",
    )


def _locate(state: dict) -> tuple[dict, list]:
    mobile_note = dig(state, "noteData", "data", "noteData")
    if isinstance(mobile_note, dict) and mobile_note:
        return mobile_note, dig(state, "noteData", "data", "commentData", "comments") or []
    detail_map = dig(state, "note", "noteDetailMap")
    if isinstance(detail_map, dict) and detail_map:
        current = dig(state, "note", "currentNoteId")
        entry = detail_map.get(current) if isinstance(current, str) else None
        if entry is None:
            entry = next(iter(detail_map.values()))
        note = dig(entry, "note")
        if isinstance(note, dict) and note:
            return note, dig(entry, "comments", "list") or []
    if isinstance(state.get("noteData"), dict) or isinstance(state.get("note"), dict):
        raise _unavailable()
    raise ReaderError(ErrorCode.PARSE_CHANGED, "小红书页面结构已变化：未找到笔记数据")


def _https(url: Any) -> str:
    url = str(url or "")
    return "https://" + url[len("http://"):] if url.startswith("http://") else url


def _image(img: Any) -> str:
    if not isinstance(img, dict):
        return ""
    return _https(img.get("url") or img.get("urlDefault") or dig(img, "infoList", -1, "url"))


def parse(
    html: str, *, source_url: str, options: ReadOptions, expected_id: str | None = None
) -> Extraction:
    state = load_js_object(html, _MARKER, what="小红书")
    if state is None:
        if _app_only(None, html):
            raise _app_only_error()
        doc = parse_html(html)
        wall = detect_wall(
            "\n".join(filter(None, [doc.title, doc.text()])), has_password=doc.has_password_input
        )
        if wall:
            raise wall
        raise ReaderError(ErrorCode.PARSE_CHANGED, "未找到小红书数据 __INITIAL_STATE__，页面结构可能已变化")

    try:
        note, raw_comments = _locate(state)
    except ReaderError as error:
        if error.code is ErrorCode.CONTENT_NOT_FOUND and _app_only(state, html):
            raise _app_only_error() from None
        raise
    found_id = str(note.get("noteId") or "")
    if expected_id and found_id and found_id != expected_id:
        raise ReaderError(ErrorCode.PARSE_CHANGED, "页面返回的笔记与链接中的笔记 ID 不一致，已停止读取")
    is_video = note.get("type") == "video"
    desc = str(note.get("desc") or "")
    body = clean_text(_TOPIC.sub(lambda m: "#" + m.group(1).strip(), desc))
    title = clean_text(str(note.get("title") or "")) or body.split("\n", 1)[0][:50]
    user = note.get("user") if isinstance(note.get("user"), dict) else {}

    interact = note.get("interactInfo") if isinstance(note.get("interactInfo"), dict) else {}
    parsed = {
        key: parse_count(interact.get(field))
        for key, field in (
            ("likes", "likedCount"), ("collects", "collectedCount"),
            ("comments", "commentCount"), ("shares", "shareCount"),
        )
    }

    images = [u for u in (_image(i) for i in note.get("imageList") or []) if u]
    stream = dig(note, "video", "media", "stream", "h264", 0)
    video_url = _https(dig(stream, "masterUrl")) or None if is_video else None
    duration = dig(stream, "duration") if is_video else 0

    tags = [str(t.get("name")).strip() for t in note.get("tagList") or [] if isinstance(t, dict) and t.get("name")]
    if not tags:
        tags = [m.group(1).strip() for m in _TOPIC.finditer(desc)]

    comments: list[Comment] = []
    if options.include_comments:
        for c in raw_comments[:MAX_COMMENTS]:
            content = clean_text(str(dig(c, "content") or ""))
            if content:
                # Live pages carry both: exact likeCount (int) and display likeViewCount ("1.2万").
                exact = dig(c, "likeCount")
                likes, _ = parse_count(exact if isinstance(exact, int) else dig(c, "likeViewCount"))
                comments.append(Comment(content=content, likes=likes))

    note_id = str(note.get("noteId") or "")
    extraction = Extraction(
        platform="xhs",
        type="video" if is_video else "note",
        title=title,
        body=body,
        extractor_version=VERSION,
        author=clean_text(str(user.get("nickName") or user.get("nickname") or "")),
        published_at=from_epoch(note.get("time"), millis=True),
        stats=Stats(**{k: v for k, (v, _) in parsed.items()}),
        tags=list(dict.fromkeys(tags)),
        media=Media(
            images=images,
            video_url=video_url,
            cover_url=images[0] if is_video and images else None,
            duration_ms=int(duration or 0),
        ),
        comments=comments,
        canonical_url=f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else None,
        confidence=0.9 if body and user else 0.7,
    )
    if any(approx for _, approx in parsed.values()):
        extraction.warn("STATS_APPROXIMATE", "互动数据为平台展示的约数（如“1.2万”“10+”），非精确值")
    if options.include_comments and raw_comments:
        extraction.warn("COMMENTS_PARTIAL", "仅包含页面直出的部分热门评论，不含评论者身份信息")
    return extraction
