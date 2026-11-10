"""Dependency-free HTML reading: metadata, JSON-LD and region-tagged paragraphs.

Text is collected per block element and tagged with the region it came from
(article / main / body / excluded), so extractors can prefer real content
containers and drop navigation, footers, forms and scripts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_SKIP = {"script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "head"}
_EXCLUDE = {"nav", "header", "footer", "aside", "form", "button", "select", "label", "dialog"}
_BLOCK = {
    "p", "div", "section", "article", "main", "h1", "h2", "h3", "h4", "h5", "h6", "li",
    "ul", "ol", "br", "blockquote", "pre", "table", "tr", "td", "th", "figure",
    "figcaption", "dd", "dt", "dl", "hr", "header", "footer", "aside", "nav", "form",
}
_VOID = {
    "br", "hr", "img", "input", "meta", "link", "source", "area", "base", "col",
    "embed", "param", "track", "wbr",
}
_SPACES = re.compile(r"\s+")


@dataclass
class Paragraph:
    text: str
    region: str  # article | main | body | excluded
    tag: str


@dataclass
class HtmlDoc:
    title: str = ""
    metas: dict[str, str] = field(default_factory=dict)
    canonical: str | None = None
    jsonld: list[str] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)
    has_password_input: bool = False

    def meta(self, *names: str) -> str:
        for name in names:
            value = self.metas.get(name.lower(), "").strip()
            if value:
                return value
        return ""

    def text(self, *regions: str) -> str:
        wanted = set(regions) or {"article", "main", "body", "excluded"}
        return "\n".join(p.text for p in self.paragraphs if p.region in wanted)


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doc = HtmlDoc()
        self.stack: list[str] = []
        self.counts = {"skip": 0, "exclude": 0, "article": 0, "main": 0}
        self.in_title = False
        self.in_jsonld = False
        self.title_parts: list[str] = []
        self.jsonld_parts: list[str] = []
        self.buf: list[str] = []
        self.buf_region = "body"
        self.buf_tag = "p"

    # ── state ──
    def _region(self) -> str:
        if self.counts["exclude"]:
            return "excluded"
        if self.counts["article"]:
            return "article"
        if self.counts["main"]:
            return "main"
        return "body"

    def _adjust(self, tag: str, delta: int) -> None:
        if tag in _SKIP:
            self.counts["skip"] += delta
        if tag in _EXCLUDE:
            self.counts["exclude"] += delta
        if tag == "article":
            self.counts["article"] += delta
        if tag == "main":
            self.counts["main"] += delta

    def _flush(self) -> None:
        text = _SPACES.sub(" ", "".join(self.buf)).strip()
        self.buf = []
        if text:
            if self.buf_tag == "li":
                text = "- " + text
            self.doc.paragraphs.append(Paragraph(text, self.buf_region, self.buf_tag))

    # ── parser hooks ──
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and "content" in a and key not in self.doc.metas:
                self.doc.metas[key] = a["content"]
            return
        if tag == "link" and "canonical" in a.get("rel", "").lower().split():
            self.doc.canonical = a.get("href") or None
            return
        if tag == "input" and a.get("type", "").lower() == "password":
            self.doc.has_password_input = True
        if tag == "title" and "svg" not in self.stack and not self.title_parts:
            self.in_title = True  # first document <title> only, never <svg><title>
        if tag == "script" and "ld+json" in a.get("type", "").lower():
            self.in_jsonld = True
            self.jsonld_parts = []
        if tag in _BLOCK:
            self._flush()
            self.buf_tag = tag
        if tag in _VOID:
            return
        self.stack.append(tag)
        self._adjust(tag, +1)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag == "script" and self.in_jsonld:
            self.in_jsonld = False
            self.doc.jsonld.append("".join(self.jsonld_parts))
        if tag in _BLOCK:
            self._flush()
            self.buf_tag = "p"
        if tag not in self.stack:
            return
        while self.stack:
            top = self.stack.pop()
            self._adjust(top, -1)
            if top == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.in_jsonld:
            self.jsonld_parts.append(data)
            return
        if self.counts["skip"]:
            return
        if not self.buf:
            self.buf_region = self._region()
        self.buf.append(data)

    def close(self) -> None:
        super().close()
        self._flush()
        self.doc.title = _SPACES.sub(" ", "".join(self.title_parts)).strip()


def parse_html(html: str) -> HtmlDoc:
    collector = _Collector()
    collector.feed(html)
    collector.close()
    return collector.doc


def visible_text(html: str) -> str:
    doc = parse_html(html)
    return "\n".join(filter(None, [doc.title, doc.text()]))
