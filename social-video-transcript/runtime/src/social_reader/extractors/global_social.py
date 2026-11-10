"""Read public posts rendered by the platforms' normal web pages."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from ..browser import BrowserUnavailable, Renderer
from ..errors import ErrorCode, ReaderError
from ..fetcher import Fetcher, FetchResult
from ..models import Extraction
from .common import ReadOptions, clean_text, detect_wall
from .htmltext import parse_html

VERSION = "global-social-browser-0.1.0"
_PATTERNS = {
    "tiktok": re.compile(r"/@[A-Za-z0-9_.-]+/video/([0-9]{10,25})/?"),
    "instagram": re.compile(r"/(?:p|reel)/([A-Za-z0-9_-]{5,32})/?"),
    "facebook": re.compile(r"/[0-9]+/posts/([0-9]{8,25})/?"),
}
HOSTS = {
    "tiktok": ("tiktok.com",),
    "instagram": ("instagram.com",),
    "facebook": ("facebook.com",),
}


def identify(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    host = parts.hostname or ""
    for platform, pattern in _PATTERNS.items():
        if host in {platform + ".com", "www." + platform + ".com", "m." + platform + ".com"}:
            match = pattern.fullmatch(parts.path)
            if match:
                return platform, match[1]
    return None


class _Content(HTMLParser):
    def __init__(self, platform: str) -> None:
        super().__init__()
        self.platform = platform
        self.depth = 0
        self.body: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        if tag in {"script", "style"}:
            self.hidden += 1
        chosen = (
            self.platform == "tiktok" and tag == "article" and fields.get("data-e2e") == "video-desc"
            or self.platform == "instagram" and tag == "h1"
            or self.platform == "facebook" and tag == "div" and fields.get("class") == "message"
        )
        if self.depth:
            if tag not in {"br", "img", "input", "meta", "link", "source"}:
                self.depth += 1
            if tag == "br":
                self.body.append("\n")
        elif chosen and not self.body:
            self.depth = 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if self.depth and tag not in {"br", "img", "input", "meta", "link", "source"}:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth and not self.hidden:
            self.body.append(data)


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: Renderer | None = None) -> tuple[Extraction, FetchResult]:
    platform, work = identify(url)
    canonical = url.split("?", 1)[0].split("#", 1)[0]
    if renderer is None:
        raise ReaderError(ErrorCode.FETCH_BLOCKED, "该平台需要本机浏览器渲染公开页面")
    try:
        html = renderer.render(canonical, ready=lambda page: (
            'data-e2e="video-desc"' in page if platform == "tiktok" else 'property="og:description"' in page
        ))
    except BrowserUnavailable:
        raise ReaderError(ErrorCode.FETCH_BLOCKED, "未安装可用的浏览器渲染组件") from None
    doc = parse_html(html)
    if wall := detect_wall(doc.text(), has_password=doc.has_password_input):
        raise wall
    if work not in html:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "页面没有返回指定作品")
    if platform in {"instagram", "facebook"} and (not doc.canonical or work not in urlsplit(doc.canonical).path):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "页面未确认所请求的作品")
    content = _Content(platform)
    content.feed(html)
    body = clean_text("".join(content.body))
    if not body:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "页面没有公开返回完整的作品文字")
    kind = "video" if platform == "tiktok" or "/reel/" in canonical else "note"
    result = Extraction(platform=platform, type=kind, title=body.split("\n", 1)[0][:80],
                        body=body, canonical_url=canonical, extractor_version=VERSION, confidence=0.8)
    result.warn("TEXT_MAY_BE_TRUNCATED", "页面显示的文字可能被折叠或截断")
    result.warn("MEDIA_UNAVAILABLE", "已读取公开文字，媒体地址尚未取得")
    return result, FetchResult(url=canonical, status=200, content_type="text/html", text=html)
