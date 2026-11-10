"""Read public Google Docs, Google Scholar profiles, and Baidu Wenku previews."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import DESKTOP_UA, Fetcher, FetchResult
from ..models import Extraction
from .common import ReadOptions, clean_text, detect_wall
from .htmltext import parse_html

VERSION = "public-documents-0.1.0"
_GOOGLE_DOC = re.compile(r"/document/(?:u/[0-9]+/)?d/(e/)?([A-Za-z0-9_-]{10,200})/(edit|view|pub)/?")


def identify(url: str) -> str | None:
    parts = urlsplit(url)
    host = parts.hostname
    if host == "docs.google.com" and _GOOGLE_DOC.fullmatch(parts.path):
        return "google_docs"
    if host == "scholar.google.com" and parts.path == "/citations" and parse_qs(parts.query).get("user"):
        return "google_scholar"
    if host == "wenku.baidu.com" and re.fullmatch(r"/(?:view|tfview)/[A-Za-z0-9]+\.html", parts.path):
        return "baidu_wenku"
    return None


class _Fragment(HTMLParser):
    def __init__(self, element_id: str) -> None:
        super().__init__(convert_charrefs=False)
        self.element_id = element_id
        self.depth = 0
        self.finished = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.finished:
            return
        if not self.depth:
            if tag == "div" and dict(attrs).get("id") == self.element_id:
                self.depth = 1
            return
        self.parts.append(self.get_starttag_text())
        if tag == "div":
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self.depth:
            return
        if tag == "div":
            self.depth -= 1
            if not self.depth:
                self.finished = True
                return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")


def _fragment(html: str, element_id: str) -> str:
    part = _Fragment(element_id)
    part.feed(html)
    part.close()
    if not part.finished:
        return ""
    return clean_text(parse_html("".join(part.parts)).text())


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None) -> tuple[Extraction, FetchResult]:
    platform = identify(url)
    parts = urlsplit(url)
    if platform == "google_docs":
        match = _GOOGLE_DOC.fullmatch(parts.path)
        resource = parse_qs(parts.query).get("resourcekey", [])
        query = urlencode([("resourcekey", value) for value in resource])
        canonical = urlunsplit(("https", parts.netloc, parts.path, query, ""))
        fetched = fetcher.fetch(canonical, user_agent=DESKTOP_UA, scope=("docs.google.com",))
        if urlsplit(fetched.url).path.rstrip("/") != parts.path.rstrip("/"):
            raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "Google 文档没有返回指定文件")
        doc = parse_html(fetched.text)
        if match[3] == "pub":
            body = _fragment(fetched.text, "contents")
        elif not match[1]:
            export_query = urlencode([("format", "txt"), *[("resourcekey", value) for value in resource]])
            export = f"https://docs.google.com/document/d/{match[2]}/export?{export_query}"
            text = fetcher.fetch(export, user_agent=DESKTOP_UA, scope=("docs.google.com", "googleusercontent.com"))
            if not text.content_type.lower().startswith("text/plain"):
                raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "Google 文档没有返回正文文本")
            body = clean_text(text.text.lstrip("\ufeff"))
            if text.truncated:
                raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "Google 文档正文超过读取上限")
        else:
            body = ""
        title = re.sub(r"\s*[-–]\s*Google (?:Docs|文档)$", "", doc.title).strip()
    else:
        scope = ("scholar.google.com",) if platform == "google_scholar" else ("wenku.baidu.com",)
        canonical = urlunsplit(("https", parts.netloc, parts.path, parts.query if platform == "google_scholar" else "", ""))
        fetched = fetcher.fetch(canonical, user_agent=DESKTOP_UA, scope=scope)
        doc = parse_html(fetched.text)
        body = _fragment(fetched.text, "gsc_a_tw" if platform == "google_scholar" else "ssr-reader-container")
        title = doc.title
    if not body:
        if wall := detect_wall(doc.text(), has_password=doc.has_password_input):
            raise wall
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "页面没有公开返回可读取的正文")
    result = Extraction(platform=platform, type="article", title=title or body[:50], body=body,
                        extractor_version=VERSION, canonical_url=canonical, confidence=0.8)
    if platform == "baidu_wenku":
        result.warn("PREVIEW_ONLY", "返回页面公开显示的文档内容，可能仅为试读部分")
    if platform == "google_scholar":
        result.warn("PROFILE_LIST_ONLY", "返回学者页面当前展示的论文列表，论文全文需打开原文")
    return result, fetched
