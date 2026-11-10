"""Read text shown in public Shimo and WPS document pages."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

from ..browser import BrowserUnavailable, Renderer
from ..errors import ErrorCode, ReaderError
from ..fetcher import Fetcher, FetchResult
from ..models import Extraction
from ..security import host_matches
from .common import ReadOptions, clean_text, detect_wall
from .htmltext import parse_html

VERSION = "chinese-docs-browser-0.1.0"
HOSTS = {"shimo": ("shimo.im",), "wps": ("kdocs.cn", "wps.cn"), "tencent_docs": ("docs.qq.com",)}


def identify(url: str) -> str | None:
    parts = urlsplit(url)
    if host_matches(parts.hostname or "", HOSTS["shimo"]) and re.fullmatch(r"/docs/[A-Za-z0-9]+(?:/read)?/?", parts.path):
        return "shimo"
    if host_matches(parts.hostname or "", ("kdocs.cn",)) and re.fullmatch(r"/l/[A-Za-z0-9]+/?", parts.path):
        return "wps"
    if parts.hostname == "docs.qq.com" and re.fullmatch(r"/doc/(?:p/)?[A-Za-z0-9]+/?", parts.path):
        return "tencent_docs"
    return None


class _Content(HTMLParser):
    def __init__(self, platform: str) -> None:
        super().__init__(convert_charrefs=True)
        self.platform = platform
        self.active = 0
        self.depth = 0
        self.fragments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        start = (
            self.platform == "shimo" and tag == "div" and "hk-editor-content" in (fields.get("class") or "").split()
            or self.platform == "wps" and tag == "g" and fields.get("id") == "main-content"
            or self.platform == "tencent_docs" and tag == "div" and "headline-content" in (fields.get("class") or "").split()
        )
        if start and not self.active:
            self.active = 1
            self.depth = 1
        elif self.active and tag not in {"br", "img", "input", "meta", "link", "source"}:
            self.depth += 1
        if self.active and (tag in {"p", "br"} or self.platform == "wps" and tag == "text"
                            or self.platform == "tencent_docs" and "headline" in (fields.get("class") or "").split()):
            self.fragments.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.active and tag not in {"br", "img", "input", "meta", "link", "source"}:
            self.depth -= 1
            if self.depth == 0:
                self.active = 0

    def handle_data(self, data: str) -> None:
        if self.active:
            self.fragments.append(data)


def _text(html: str, platform: str) -> str:
    parser = _Content(platform)
    parser.feed(html)
    parser.close()
    return clean_text("".join(parser.fragments))


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: Renderer | None = None) -> tuple[Extraction, FetchResult]:
    platform = identify(url)
    parts = urlsplit(url)
    canonical = urlunsplit(("https", parts.netloc, parts.path, parts.query, ""))
    if renderer is None:
        raise ReaderError(ErrorCode.FETCH_BLOCKED, "读取该文档需要安装本机 Chrome 和浏览器组件")
    try:
        html = renderer.render(canonical, ready=lambda page: len(_text(page, platform)) >= 20)
    except BrowserUnavailable:
        raise ReaderError(ErrorCode.FETCH_BLOCKED, "未安装可用的浏览器渲染组件") from None
    doc = parse_html(html)
    body = _text(html, platform)
    if not body:
        if wall := detect_wall(doc.text(), has_password=doc.has_password_input):
            raise wall
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "页面没有公开返回可读取的文档正文")
    result = Extraction(platform=platform, type="article", title=doc.title or body[:50], body=body,
                        extractor_version=VERSION, canonical_url=canonical, confidence=0.7)
    if platform == "tencent_docs":
        result.warn("OUTLINE_ONLY", "仅提取文档当前可见的大纲标题，未获取正文")
    else:
        result.warn("TEXT_MAY_BE_INCOMPLETE", "返回浏览器加载的文档文字，分页、图片和未加载内容可能不完整")
    return result, FetchResult(url=canonical, status=200, content_type="text/html", text=html)
