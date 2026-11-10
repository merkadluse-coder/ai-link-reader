"""Read individual posts from Weibo's public post detail page."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import DESKTOP_UA, Fetcher, FetchResult
from ..models import Extraction, Media
from ..security import validate_url
from .common import ReadOptions, clean_text, detect_wall
from .htmltext import parse_html

VERSION = "weibo-detail-0.1.0"
HOST_SUFFIXES = ("weibo.com",)
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_NUMERIC_PATH = re.compile(r"/2/detail/([0-9]{12,20})/?")
_MOBILE_PATH = re.compile(r"/(?:status|detail)/([A-Za-z0-9]{8,20})/?")
_DESKTOP_PATH = re.compile(r"/[0-9]{5,20}/([A-Za-z0-9]{8,20})/?")


def post_id(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.hostname in {"weibo.com", "www.weibo.com"}:
        match = _NUMERIC_PATH.fullmatch(parts.path) or _DESKTOP_PATH.fullmatch(parts.path)
    elif parts.hostname == "m.weibo.cn":
        match = _MOBILE_PATH.fullmatch(parts.path)
    else:
        return None
    if not match:
        return None
    code = match[1]
    if re.fullmatch(r"[0-9]{12,20}", code):
        return code
    if len(code) > 12:
        return None
    # Weibo short post IDs encode each seven decimal digits as up to four base-62 digits.
    groups = []
    for end in range(len(code), 0, -4):
        value = 0
        for char in code[max(0, end - 4):end]:
            value = value * 62 + _ALPHABET.index(char)
        if value >= 10_000_000:
            return None
        groups.append(value)
    mid = str(groups[-1]) + "".join(f"{value:07d}" for value in reversed(groups[:-1]))
    return mid if len(mid) >= 12 else None


class _Post(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[tuple[str, set[str]]] = []
        self.body: list[str] = []
        self.author: list[str] = []
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        classes = {name.rsplit("__", 1)[-1] for name in (fields.get("class") or "").split()}
        if tag == "img":
            if "picImg" in classes and any("cardSingle" in css for _, css in self.stack):
                try:
                    image = validate_url(fields.get("src"), ("sinaimg.cn",))
                except ReaderError:
                    return
                if image.scheme == "https" and image.port == 443 and image.url not in self.images:
                    self.images.append(image.url)
        if self._within_post("htmlText"):
            self.body.append(self.get_starttag_text())
        if tag in {"div", "span", "a", "p", "section", "article"}:
            self.stack.append((tag, classes))

    def _within_post(self, field: str) -> bool:
        in_card = False
        for _, css in self.stack:
            in_card = in_card or "cardSingle" in css
            if in_card and field in css:
                return True
        return False

    def handle_endtag(self, tag: str) -> None:
        if self._within_post("htmlText"):
            self.body.append(f"</{tag}>")
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if self._within_post("htmlText"):
            self.body.append(data)
        elif self._within_post("name"):
            self.author.append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None) -> tuple[Extraction, FetchResult]:
    mid = post_id(url)
    canonical = f"https://weibo.com/2/detail/{mid}"
    fetched = fetcher.fetch(canonical, scope=HOST_SUFFIXES, user_agent=DESKTOP_UA)
    if post_id(fetched.url) != mid:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "微博页面没有返回指定博文")
    post = _Post()
    post.feed(fetched.text)
    post.close()
    text = clean_text(parse_html("".join(post.body)).text())
    if not (text or post.images):
        doc = parse_html(fetched.text)
        if wall := detect_wall(doc.text(), has_password=doc.has_password_input):
            raise wall
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "微博页面未公开返回该博文的正文或图片")
    author = clean_text(parse_html("".join(post.author)).text())
    return Extraction(
        platform="weibo", type="note", title=text.split("\n", 1)[0][:80] or "微博图文",
        body=text, author=author, media=Media(images=post.images), canonical_url=canonical,
        extractor_version=VERSION, confidence=0.9,
    ), fetched
