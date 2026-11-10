"""Read the public article container used by WeChat Official Accounts."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import DESKTOP_UA, Fetcher, FetchResult
from ..models import Extraction, Media
from ..security import validate_url
from .common import ReadOptions, clean_text, detect_wall
from .htmltext import parse_html

HOST_SUFFIXES = ("mp.weixin.qq.com",)
VERSION = "wechat-article-0.1.0"
_ARTICLE_QUERY = {"__biz", "mid", "idx", "sn", "chksm"}
_IMAGE_HOSTS = ("qpic.cn",)


def is_article(url: str) -> bool:
    parts = urlsplit(url)
    return parts.hostname == HOST_SUFFIXES[0] and (parts.path == "/s" or parts.path.startswith("/s/"))


def public_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k in _ARTICLE_QUERY]) if parts.path == "/s" else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


class _Body(HTMLParser):
    """Keep only the complete js_content subtree and its public image references."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.root = ""
        self.depth = 0
        self.parts: list[str] = []
        self.images: list[str] = []
        self.finished = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.finished:
            return
        fields = dict(attrs)
        if not self.depth:
            if tag in {"div", "section", "article"} and fields.get("id") == "js_content":
                self.root, self.depth = tag, 1
            return
        if tag == self.root:
            self.depth += 1
        self.parts.append(self.get_starttag_text())
        if tag == "img":
            raw = fields.get("data-src") or fields.get("src")
            try:
                img = validate_url(raw, _IMAGE_HOSTS)
            except ReaderError:
                return
            if img.scheme == "https" and img.port == 443 and img.url not in self.images:
                self.images.append(img.url)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag == self.root:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.depth:
            return
        if tag == self.root:
            self.depth -= 1
            if self.depth == 0:
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


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None) -> tuple[Extraction, FetchResult]:
    fetched = fetcher.fetch(url, user_agent=DESKTOP_UA, scope=HOST_SUFFIXES)
    body = _Body()
    body.feed(fetched.text)
    body.close()
    if not body.finished:
        if any(s in fetched.text for s in ("环境异常", "完成验证")) or "appmsgcaptcha" in fetched.url:
            raise ReaderError(ErrorCode.FETCH_BLOCKED, "微信要求环境验证，已停止读取")
        doc = parse_html(fetched.text)
        wall = detect_wall(doc.text(), has_password=doc.has_password_input)
        if wall:
            raise wall
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "公众号页面没有完整的文章正文")
    text = clean_text(parse_html("".join(body.parts)).text("body", "article", "main"))
    doc = parse_html(fetched.text)
    title = clean_text(doc.meta("og:title", "twitter:title") or doc.title)
    if not (title and (text or body.images)):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "公众号文章标题或正文为空")
    return Extraction(
        platform="wechat", type="article", title=title, body=text,
        author=clean_text(doc.meta("author", "article:author", "og:article:author")),
        extractor_version=VERSION, canonical_url=public_url(fetched.url if is_article(fetched.url) else url),
        media=Media(images=body.images), confidence=0.95,
    ), fetched
