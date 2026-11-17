"""Public article pages on mainland Chinese news and publishing platforms."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from ..errors import ErrorCode, ReaderError, RightsState
from ..fetcher import DESKTOP_UA, Fetcher, FetchResult
from ..models import Extraction
from ..security import host_matches, validate_url
from . import generic
from .common import CN_TZ, ReadOptions

VERSION = "chinese-media-0.1.0"
_HUANQIU_FIELD = re.compile(r'<textarea\s+class="article-([a-z-]+)"[^>]*>(.*?)</textarea>', re.DOTALL)
_HEAD = re.compile(r"<head\b[^>]*>.*?</head>", re.IGNORECASE | re.DOTALL)
_KR36_VISIBLE_DATE = re.compile(
    r'<span\b[^>]*class="[^"]*\bitem-time\b[^"]*"[^>]*>.*?'
    r'(\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2})',
)


@dataclass(frozen=True)
class ArticleSite:
    label: str
    hosts: tuple[str, ...]
    path: str
    containers: tuple[str, ...]

    def contains_article(self, attrs: dict[str, str]) -> bool:
        markers = {
            "#" + attrs.get("id", ""),
            "@" + attrs.get("data-testid", ""),
            *attrs.get("class", "").split(),
        }
        return any(
            any(marker.startswith(container[:-1]) for marker in markers)
            if container.endswith("*") else container in markers
            for container in self.containers
        )


SITES = {
    "xinhua": ArticleSite(
        "新华网", ("news.cn", "xinhuanet.com"), r"/(?:[^/]+/)*[^/]+\.html",
        ("#detail", "#detailContent", "#p-detail"),
    ),
    "people": ArticleSite(
        "人民网 / 人民日报", ("people.com.cn",),
        r"/(?:[^/]+/)*c\d+-\d+\.html|/rmrb/pc/content/\d{6}/\d{2}/content_\d+\.html",
        ("#rm_txt_zw", "article"),
    ),
    "cctv": ArticleSite(
        "央视网", ("cctv.com",), r"/\d{4}/\d{2}/\d{2}/ARTI[\w-]+\.shtml", ("#content_area",),
    ),
    "chinanews": ArticleSite(
        "中新网", ("chinanews.com.cn", "chinanews.com"),
        r"/[^/]+/\d{4}/\d{2}-\d{2}/\d+\.s?html", ("content_maincontent_content", "#zw"),
    ),
    "cnr": ArticleSite(
        "央广网", ("cnr.cn",), r"/(?:[^/]+/)*t\d{8}_\d+\.shtml", ("article-content",),
    ),
    "gmw": ArticleSite(
        "光明网", ("gmw.cn",), r"/\d{4}-\d{2}/\d{2}/content_\d+\.htm", ("u-mainText",),
    ),
    "huanqiu": ArticleSite(
        "环球网", ("huanqiu.com",), r"/article/[A-Za-z0-9]+/?", ("article-content",),
    ),
    "thepaper": ArticleSite(
        "澎湃新闻", ("thepaper.cn",), r"/newsDetail_forward_\d+/?", ("cententWrap__*",),
    ),
    "bjnews": ArticleSite(
        "新京报", ("bjnews.com.cn",), r"/detail/\d+\.html", ("#contentStr",),
    ),
    "nandu": ArticleSite(
        "南方都市报", ("oeeee.com",), r"/a/[A-Za-z0-9]+\.html", ("#docContent",),
    ),
    "sina_news": ArticleSite(
        "新浪新闻", ("news.sina.com.cn", "finance.sina.com.cn", "tech.sina.com.cn", "k.sina.com.cn"),
        r"/(?:[^/]+/)*(?:doc-[\w-]+|article_[\w-]+)\.s?html", ("#artibody", "#article"),
    ),
    "ifeng": ArticleSite("凤凰网", ("ifeng.com",), r"/c/[A-Za-z0-9]+/?", ("index_text_*",)),
    "jiemian": ArticleSite("界面新闻", ("jiemian.com",), r"/article/\d+\.html", ("article-content",)),
    "yicai": ArticleSite("第一财经", ("yicai.com",), r"/news/\d+\.html", ("#multi-text",)),
    "cls": ArticleSite("财联社", ("cls.cn",), r"/detail/\d+/?", ("l-h-34p",)),
    "kr36": ArticleSite("36氪", ("36kr.com",), r"/p/\d+/?", ("articleDetailContent",)),
    "baijiahao": ArticleSite(
        "百家号", ("baijiahao.baidu.com",), r"/s", ("@article",),
    ),
    "zaker": ArticleSite(
        "ZAKER", ("www.myzaker.com", "app.myzaker.com"),
        r"/article/[0-9a-f]{24}/?|/news/article\.php", ("#content",),
    ),
    "caixin": ArticleSite(
        "财新网", ("caixin.com",), r"/\d{4}-\d{2}-\d{2}/\d+\.html", ("#Main_Content_Val",),
    ),
    "tencent_news": ArticleSite("腾讯新闻", ("news.qq.com",), r"/rain/a/\w+/?", ("rich_media_content",)),
    "netease_news": ArticleSite(
        "网易新闻", ("163.com",), r"/(?:dy/article|\d{2}/\d{4}/\d{2})/[\w-]+\.html",
        ("#endText", "post_body"),
    ),
    "sohu_news": ArticleSite("搜狐新闻", ("sohu.com",), r"/a/\d+_\d+/?", ("#mp-editor",)),
}


def _query_id(query: str, name: str, pattern: str) -> str | None:
    ids = parse_qs(query).get(name, [])
    return ids[0] if len(ids) == 1 and re.fullmatch(pattern, ids[0]) else None


def _zaker_id(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.hostname == "app.myzaker.com" and parts.path == "/news/article.php":
        return _query_id(parts.query, "pk", r"[0-9a-f]{24}")
    match = re.fullmatch(r"/article/([0-9a-f]{24})/?", parts.path)
    return match[1] if parts.hostname == "www.myzaker.com" and match else None


def identify(url: str) -> str | None:
    parts = urlsplit(url)
    host = parts.hostname or ""
    for platform, site in SITES.items():
        if host_matches(host, site.hosts) and re.fullmatch(site.path, parts.path):
            if platform == "baijiahao" and not _query_id(parts.query, "id", r"[0-9]{10,24}"):
                return None
            if platform == "zaker" and not _zaker_id(url):
                return None
            return platform
    return None


def _article_url(url: str, platform: str) -> str:
    parts = urlsplit(url)
    query = ""
    if platform == "baijiahao":
        query = urlencode({"id": parse_qs(parts.query)["id"][0]})
    if platform == "zaker" and parts.path == "/news/article.php":
        query = urlencode({"pk": _zaker_id(url)})
    return urlunsplit(("https", parts.netloc, parts.path, query, ""))


def _parse_huanqiu_payload(html: str, url: str, options: ReadOptions) -> Extraction:
    # This is the HTML fragment the public article page passes to its frontend.
    fields = dict(_HUANQIU_FIELD.findall(html))
    work_id = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    if (fields.get("aid", "").strip() != work_id or fields.get("addltype") != "article"
            or not fields.get("content")):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "环球网页面未提供指定文章的公开正文")
    head = _HEAD.search(html)
    document = (head[0] if head else "") + '<div id="public-article">' + fields["content"] + "</div>"
    extraction = generic.parse(
        document, source_url=url, options=options,
        article_container=lambda attrs: attrs.get("id") == "public-article",
    )
    if not extraction.author:
        extraction.author = fields.get("author", "").removeprefix("作者：").strip()
    return extraction


def read(
    url: str, fetcher: Fetcher, options: ReadOptions, *, renderer: object = None,
) -> tuple[Extraction, FetchResult]:
    platform = identify(url)
    if platform is None:
        raise ReaderError(ErrorCode.UNSUPPORTED_PLATFORM, "请提供公开的新闻文章链接")
    site = SITES[platform]
    fetched = fetcher.fetch(_article_url(url, platform), user_agent=DESKTOP_UA, scope=site.hosts)
    if identify(fetched.url) != platform:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "链接未指向该媒体的公开文章页")
    if platform == "zaker" and _zaker_id(fetched.url) != _zaker_id(url):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "ZAKER 没有返回指定文章")
    if platform == "baijiahao" and _article_url(fetched.url, platform) != _article_url(url, platform):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "百家号没有返回指定文章")
    if platform == "tencent_news" and "waf.tencent.com/501page" in fetched.text:
        raise ReaderError(ErrorCode.FETCH_BLOCKED, "腾讯新闻返回访问验证页面")
    canonical = _article_url(fetched.url, platform)
    if platform == "huanqiu" and urlsplit(canonical).path.rstrip("/") != urlsplit(url).path.rstrip("/"):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "环球网没有返回指定文章")
    try:
        extraction = generic.parse(
            fetched.text, source_url=canonical, options=options, article_container=site.contains_article,
        )
    except ReaderError as error:
        if platform != "huanqiu" or error.code != ErrorCode.CONTENT_NOT_FOUND:
            raise
        extraction = _parse_huanqiu_payload(fetched.text, canonical, options)
    extraction.platform = platform
    extraction.extractor_version = VERSION
    extraction.canonical_url = canonical
    extraction.title = re.sub(
        r"\s*[-—_|]\s*(?:新华网|中新网|界面|36氪|光明网|央广网|新京报)$", "", extraction.title,
    )
    if extraction.author.isdecimal() or extraction.author == "chinanews":
        extraction.author = ""
    if platform == "kr36":
        # The page can put its render time in the publication meta tag.
        match = _KR36_VISIBLE_DATE.search(fetched.text)
        extraction.published_at = None
        if match:
            try:
                extraction.published_at = datetime.strptime(match.group(1), "%Y年%m月%d日 %H:%M")
            except ValueError:
                pass
    if extraction.published_at is not None and extraction.published_at.tzinfo is None:
        extraction.published_at = extraction.published_at.replace(tzinfo=CN_TZ)
    # Caixin's shared article template can expose only the subscriber preview.
    if platform == "caixin":
        extraction.rights_state = RightsState.PREVIEW_ONLY
        extraction.warn("PREVIEW_ONLY", "仅返回财新公开显示的文字，全文可读性需查看原站")
    images = []
    for candidate in extraction.media.images:
        try:
            images.append(validate_url(candidate).url)
        except ReaderError:
            continue
    extraction.media.images = list(dict.fromkeys(images))
    return extraction, fetched
