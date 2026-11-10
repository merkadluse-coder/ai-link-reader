"""Read one public Telegram channel post through its official widget."""

from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import Fetcher, FetchResult
from ..models import Extraction, Media
from ..security import validate_url
from .common import ReadOptions, clean_text

VERSION = "telegram-widget-0.1.0"
HOST_SUFFIXES = ("t.me",)
MEDIA_HOSTS = ("telesco.pe",)
_POST_PATH = re.compile(r"/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})/([1-9][0-9]{0,15})/?")
_PHOTO_URL = re.compile(r"background-image:\s*url\(['\"]([^'\"]+)['\"]\)")


def post_id(url: str) -> str | None:
    parts = urlsplit(url)
    match = _POST_PATH.fullmatch(parts.path)
    if parts.hostname == "t.me" and match and match[1].lower() not in {"joinchat", "share", "addstickers"}:
        return f"{match[1].lower()}/{match[2]}"
    return None


class _Message(HTMLParser):
    def __init__(self, work: str) -> None:
        super().__init__()
        self.work = work
        self.depth = 0
        self.text_depth = 0
        self.author_depth = 0
        self.body: list[str] = []
        self.author: list[str] = []
        self.images: list[str] = []
        self.video: str | None = None
        self.published = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        classes = (fields.get("class") or "").split()
        if tag == "div":
            if not self.depth and (fields.get("data-post") or "").lower() != self.work:
                return
            self.depth += 1
            if "tgme_widget_message_text" in classes:
                self.text_depth = self.depth
            if "tgme_widget_message_author" in classes:
                self.author_depth = self.depth
        if not self.depth:
            return
        if self.text_depth and tag in {"div", "p", "br", "blockquote", "li"}:
            self.body.append("\n")
        if tag == "time" and fields.get("datetime"):
            self.published = fields["datetime"]
        if tag == "video" and "tgme_widget_message_video" in classes:
            self.video = self.video or _media_url(fields.get("src"))
        if tag == "a" and "tgme_widget_message_photo_wrap" in classes:
            match = _PHOTO_URL.search(fields.get("style") or "")
            image = _media_url(match[1]) if match else None
            if image and image not in self.images:
                self.images.append(image)

    def handle_endtag(self, tag: str) -> None:
        if tag != "div" or not self.depth:
            return
        if self.text_depth == self.depth:
            self.text_depth = 0
        if self.author_depth == self.depth:
            self.author_depth = 0
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.text_depth:
            self.body.append(data)
        elif self.author_depth:
            self.author.append(data)


def _media_url(value: str | None) -> str | None:
    try:
        target = validate_url(value, MEDIA_HOSTS)
    except ReaderError:
        return None
    return target.url if target.scheme == "https" and target.port == 443 else None


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None) -> tuple[Extraction, FetchResult]:
    work = post_id(url)
    canonical = f"https://t.me/{work}"
    fetched = fetcher.fetch(f"{canonical}?embed=1", scope=HOST_SUFFIXES)
    post = _Message(work)
    post.feed(fetched.text)
    post.close()
    body = clean_text("".join(post.body))
    if not (body or post.images or post.video):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "Telegram 没有公开返回该帖子的正文或媒体")
    try:
        published = datetime.fromisoformat(post.published)
    except ValueError:
        published = None
    return Extraction(
        platform="telegram", type="video" if post.video else "note",
        title=body.split("\n", 1)[0][:80] or "Telegram 帖子", body=body,
        author=clean_text("".join(post.author)), published_at=published,
        media=Media(images=post.images, video_url=post.video), canonical_url=canonical,
        extractor_version=VERSION, confidence=0.95,
    ), fetched
