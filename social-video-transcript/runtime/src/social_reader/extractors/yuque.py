"""Read public Yuque documents from the same data used by the document page."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import DESKTOP_UA, Fetcher, FetchResult
from ..models import Extraction, Media
from ..security import host_matches, validate_url
from .common import ReadOptions, clean_text, detect_wall
from .htmltext import parse_html

VERSION = "yuque-doc-0.1.0"
HOST_SUFFIXES = ("yuque.com",)
_APP_DATA = re.compile(r'window\.appData\s*=\s*JSON\.parse\(decodeURIComponent\(("(?:\\.|[^"\\])*")\)\)')
_SLUG = re.compile(r"[A-Za-z0-9_-]{1,120}")


def is_document(url: str) -> bool:
    parts = urlsplit(url)
    return host_matches(parts.hostname or "", HOST_SUFFIXES) and len([p for p in parts.path.split("/") if p]) >= 3


class _Images(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        source = fields.get("src") if tag == "img" else None
        value = fields.get("value")
        if tag == "card" and fields.get("name") == "image" and isinstance(value, str) and value.startswith("data:"):
            try:
                image_data = json.loads(unquote(value[5:]))
            except (TypeError, ValueError):
                return
            source = image_data.get("src") if isinstance(image_data, dict) else None
        if not source:
            return
        try:
            target = validate_url(source)
        except ReaderError:
            return
        if target.scheme == "https" and target.port == 443 and target.url not in self.images:
            self.images.append(target.url)


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None) -> tuple[Extraction, FetchResult]:
    parts = urlsplit(url)
    canonical = urlunsplit(("https", parts.netloc, parts.path, "", ""))
    fetched = fetcher.fetch(canonical, user_agent=DESKTOP_UA, scope=HOST_SUFFIXES)
    if urlsplit(fetched.url).path.rstrip("/") != parts.path.rstrip("/"):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "语雀页面没有返回指定文档")
    match = _APP_DATA.search(fetched.text)
    if not match:
        doc = parse_html(fetched.text)
        if wall := detect_wall(doc.text(), has_password=doc.has_password_input):
            raise wall
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "语雀页面没有返回文档信息")
    try:
        page = json.loads(unquote(json.loads(match[1])))
        info = page["doc"]
        doc_id, book_id = info["id"], info["book_id"]
        slug = info["slug"]
    except (ValueError, KeyError, TypeError):
        raise ReaderError(ErrorCode.PARSE_CHANGED, "语雀文档信息无法解析") from None
    if not isinstance(info, dict) or info.get("abilities", {}).get("read") is not True:
        raise ReaderError(ErrorCode.PERMISSION_REQUIRED, "该语雀文档没有公开读取权限")
    if type(doc_id) is not int or type(book_id) is not int or not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise ReaderError(ErrorCode.PARSE_CHANGED, "语雀文档标识无效")
    if parts.path.rstrip("/").split("/")[-1] != slug:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "语雀文档标识与链接不一致")
    api = urlunsplit(("https", parts.netloc, f"/api/docs/{doc_id}", urlencode({"book_id": book_id}), ""))
    response = fetcher.fetch(api, user_agent=DESKTOP_UA, referer=canonical, scope=HOST_SUFFIXES)
    try:
        data = json.loads(response.text)["data"]
        html = data["content"]
    except (ValueError, KeyError, TypeError):
        raise ReaderError(ErrorCode.PARSE_CHANGED, "语雀正文数据无法解析") from None
    if not isinstance(data, dict) or data.get("id") != doc_id or not isinstance(html, str):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "语雀返回的正文与指定文档不一致")
    body = clean_text(parse_html(html).text())
    images = _Images()
    images.feed(html)
    if not body and not images.images:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "语雀没有返回可读取的正文")
    title = info.get("title")
    return Extraction(
        platform="yuque", type="article", title=clean_text(title) if isinstance(title, str) else "",
        body=body, extractor_version=VERSION, canonical_url=canonical,
        media=Media(images=images.images), confidence=0.9,
    ), fetched
