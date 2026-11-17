"""Read original posts from the public Jike share page."""

from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import DESKTOP_UA, Fetcher, FetchResult
from ..models import Extraction, Media
from ..security import validate_url
from .common import ReadOptions, clean_text, detect_wall, dig
from .htmltext import parse_html

HOST_SUFFIXES = ("m.okjike.com",)
VERSION = "jike-original-post-0.1.0"
_NEXT_DATA = re.compile(r'<script\b[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def post_id(url: str) -> str | None:
    parts = urlsplit(url)
    match = re.fullmatch(r"/originalPosts/([0-9a-f]{24})/?", parts.path)
    return match[1] if parts.hostname == HOST_SUFFIXES[0] and match else None


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None) -> tuple[Extraction, FetchResult]:
    requested_id = post_id(url)
    if not requested_id:
        raise ReaderError(ErrorCode.UNSUPPORTED_PLATFORM, "请提供即刻公开原创动态链接")
    canonical = f"https://m.okjike.com/originalPosts/{requested_id}"
    fetched = fetcher.fetch(canonical, scope=HOST_SUFFIXES, user_agent=DESKTOP_UA)
    if post_id(fetched.url) != requested_id:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "即刻没有返回指定动态")
    match = _NEXT_DATA.search(fetched.text)
    if not match:
        doc = parse_html(fetched.text)
        if wall := detect_wall(doc.text(), has_password=doc.has_password_input):
            raise wall
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "即刻没有公开返回该动态的内容")
    try:
        state = json.loads(match[1])
    except json.JSONDecodeError:
        raise ReaderError(ErrorCode.PARSE_CHANGED, "即刻分享页的动态数据无法解析") from None
    post = dig(state, "props", "pageProps", "post")
    if (not isinstance(post, dict) or post.get("id") != requested_id
            or post.get("type") != "ORIGINAL_POST" or post.get("status") != "NORMAL"):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "即刻没有公开返回指定动态")
    body = clean_text(post["content"]) if isinstance(post.get("content"), str) else ""
    images: list[str] = []
    pictures = post.get("pictures")
    for picture in pictures if isinstance(pictures, list) else []:
        try:
            image = validate_url(dig(picture, "picUrl"), ("ruguoapp.com",))
        except ReaderError:
            continue
        if image.scheme == "https" and image.port == 443 and image.url not in images:
            images.append(image.url)
    if not (body or images):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "该即刻动态没有可读文字或图片")
    nickname = dig(post, "user", "screenName")
    try:
        published_at = datetime.fromisoformat(str(post.get("createdAt")).replace("Z", "+00:00"))
    except ValueError:
        published_at = None
    return Extraction(
        platform="jike", type="note", title=body.split("\n", 1)[0][:80] or "即刻图文",
        body=body, author=clean_text(nickname) if isinstance(nickname, str) else "",
        media=Media(images=images), canonical_url=canonical, published_at=published_at,
        extractor_version=VERSION, confidence=0.9,
    ), fetched
