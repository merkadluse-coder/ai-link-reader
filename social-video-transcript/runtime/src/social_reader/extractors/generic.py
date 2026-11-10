"""Generic web pages: JSON-LD, OpenGraph, <article>/<main> and readable text.

Login walls, captchas and empty SPA shells are reported as errors, never as an
empty success (docs/IMPLEMENTATION_SPEC.md §5.1).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit

from ..errors import ErrorCode, ReaderError
from ..fetcher import DESKTOP_UA, Fetcher
from ..models import Extraction, Media
from .common import ReadOptions, clean_text, detect_wall
from .htmltext import HtmlDoc, parse_html

VERSION = "generic-0.1.0"
_ARTICLE_TYPES = {
    "article", "newsarticle", "blogposting", "report", "scholarlyarticle",
    "techarticle", "socialmediaposting", "videoobject", "analysisnewsarticle",
}
_MIN_CONTAINER_CHARS = 40
_MIN_BODY_CHARS = 200


def read(url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: Any = None) -> tuple[Extraction, Any]:
    result = fetcher.fetch(url, user_agent=DESKTOP_UA)
    return parse(result.text, source_url=result.url, options=options), result


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "mainEntityOfPage"):
            if key in node:
                yield from _walk(node[key])


def _types(node: dict) -> set[str]:
    raw = node.get("@type", [])
    return {t.lower() for t in ([raw] if isinstance(raw, str) else raw) if isinstance(t, str)}


def _jsonld_article(doc: HtmlDoc) -> dict:
    for raw in doc.jsonld:
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            if _types(node) & _ARTICLE_TYPES:
                return node
    return {}


def _names(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return _names(value.get("name"))
    if isinstance(value, list):
        return [n for item in value for n in _names(item)]
    return []


def _keywords(value: Any) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"[,，;；]", value or "")
    seen: list[str] = []
    for item in items:
        word = str(item).strip()
        if word and word not in seen:
            seen.append(word)
    return seen


def _date(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _image_urls(article: dict, doc: HtmlDoc, base: str) -> list[str]:
    raw = article.get("image")
    candidates = [doc.meta("og:image", "twitter:image")]
    for item in raw if isinstance(raw, list) else [raw]:
        if isinstance(item, str):
            candidates.append(item)
        elif isinstance(item, dict):
            candidates.append(str(item.get("url") or ""))
    urls: list[str] = []
    for c in candidates:
        absolute = urljoin(base, c) if c else ""
        if absolute.startswith(("http://", "https://")) and absolute not in urls:
            urls.append(absolute)
    return urls


def _strip_site(title: str, site: str) -> str:
    for sep in (" | ", " - ", " _ ", " – ", " — "):
        if site and title.endswith(sep + site):
            return title[: -len(sep + site)]
    return title


def parse(html: str, *, source_url: str, options: ReadOptions) -> Extraction:
    doc = parse_html(html)
    article = _jsonld_article(doc)
    visible = "\n".join(filter(None, [doc.title, doc.text()]))
    wall = detect_wall(visible, has_password=doc.has_password_input)
    if wall:
        raise wall

    site = doc.meta("og:site_name")
    title = clean_text(
        next((t for t in _names(article.get("headline")) if t), "")
        or doc.meta("og:title", "twitter:title")
        or _strip_site(doc.title, site)
    )

    regions = {
        "article": [p for p in doc.paragraphs if p.region == "article"],
        "main": [p for p in doc.paragraphs if p.region == "main"],
        "body": [p for p in doc.paragraphs if p.region == "body" and len(p.text) >= 20],
    }
    source, paragraphs = "metadata", []
    for name in ("article", "main"):
        if sum(len(p.text) for p in regions[name]) >= _MIN_CONTAINER_CHARS:
            source, paragraphs = name, regions[name]
            break
    else:
        if sum(len(p.text) for p in regions["body"]) >= _MIN_CONTAINER_CHARS:
            source, paragraphs = "body", regions["body"]
    texts = [p.text for p in paragraphs]
    if texts and title and texts[0].strip() == title:
        texts = texts[1:]
    body = clean_text("\n\n".join(texts))
    json_body = clean_text(str(article.get("articleBody") or ""))
    if len(json_body) > len(body):
        body, source = json_body, "jsonld"

    description = clean_text(doc.meta("og:description", "description", "twitter:description"))
    if not body:
        if not description:
            raise ReaderError(
                ErrorCode.CONTENT_NOT_FOUND, "未找到可读正文（页面可能依赖 JavaScript 渲染或为空壳）"
            )
        body = description

    raw_canonical = doc.canonical or doc.meta("og:url")
    canonical = urljoin(source_url, raw_canonical) if raw_canonical else None
    if canonical and urlsplit(canonical).scheme not in ("http", "https"):
        canonical = None

    author = next((n for n in _names(article.get("author")) if n.strip()), "") or doc.meta(
        "author", "article:author", "twitter:creator"
    )
    if author.startswith(("http://", "https://")):
        author = ""

    extraction = Extraction(
        platform="generic",
        type="article" if source in ("article", "main", "jsonld") or article else "page",
        title=title or body[:50],
        body=body,
        extractor_version=VERSION,
        author=clean_text(author),
        published_at=_date(str(article.get("datePublished") or article.get("uploadDate") or ""))
        or _date(doc.meta("article:published_time", "og:published_time", "pubdate", "date")),
        tags=_keywords(article.get("keywords") or doc.meta("keywords")),
        media=Media(images=_image_urls(article, doc, source_url)),
        canonical_url=canonical,
    )
    if source == "metadata":
        extraction.confidence = 0.4
        extraction.warn("METADATA_ONLY", "未读取到正文，仅返回页面元数据描述")
    elif source == "body":
        extraction.confidence = 0.6 if len(body) >= _MIN_BODY_CHARS else 0.5
        extraction.warn("LOW_CONFIDENCE", "未识别到正文容器，正文由全页文本推断，可能混入导航等内容或不完整")
    else:
        extraction.confidence = 0.9 if article else 0.8
    if not extraction.title:
        extraction.warn("NO_TITLE", "页面没有标题")
    return extraction
