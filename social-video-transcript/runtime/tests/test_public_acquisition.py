import json

import httpx

from social_reader.config import Settings
from social_reader.fetcher import Fetcher
from social_reader.service import ReaderService


def service_for(handler):
    settings = Settings(browser_fallback="off")
    fetcher = Fetcher(settings, transport=httpx.MockTransport(handler), resolver=lambda *_: ["93.184.216.34"])
    return ReaderService(settings, fetcher=fetcher)


def test_kuaishou_short_link_only_returns_media_for_the_requested_work():
    work = "3xvalidwork"
    expected_media = "https://video.kwimgs.com/correct.mp4?token=synthetic"

    def photo(work_id, media):
        return {"result": 1, "photo": {
            "photoType": "VIDEO", "photoId": "123456", "share_info": f"userId=example&photoId={work_id}",
            "caption": "公开作品", "mainMvUrls": [{"url": media}],
        }}

    state = json.dumps({
        "other": photo("3xwrongwork", "https://video.kwimgs.com/wrong.mp4"),
        "requested": photo(work, expected_media),
    })

    def handle(request):
        host = request.headers["host"]
        if host == "v.kuaishou.com":
            return httpx.Response(302, headers={
                "location": f"https://kph1tf76.m.chenzhongtech.com/fw/photo/{work}?tracking=synthetic",
            })
        assert (host, request.url.path, request.url.query) == ("m.kuaishou.com", f"/fw/photo/{work}", b"")
        return httpx.Response(200, text=f"<script>window.INIT_STATE = {state}</script>",
                              headers={"content-type": "text/html"})

    service = service_for(handle)
    share = "分享 https://v.kuaishou.com/sample"
    plain = service.read_page(share, output="json")
    assert plain["ok"] and plain["media"]["has_video"] and plain["media"]["video_url"] is None
    assert "transcript" not in plain and "synthetic" not in json.dumps(plain)
    with_media = service.read_page(share, output="json", include_media=True)
    assert with_media["media"]["video_url"] == expected_media


def test_wechat_returns_only_the_article_and_its_images():
    article = """
        <meta property="og:title" content="文章标题">
        <div>页面推荐</div>
        <div id="js_content"><div>正文 &amp; 说明</div>
        <img data-src="https://mmbiz.qpic.cn/article.jpg">
        <img src="https://other.example/not-an-article-image.jpg"></div>
        <img src="https://mmbiz.qpic.cn/recommendation.jpg">
    """

    def handle(request):
        assert request.url.query == b""
        return httpx.Response(200, text=article, headers={"content-type": "text/html"})

    result = service_for(handle).read_page("https://mp.weixin.qq.com/s/sample?tracking=synthetic",
                                           output="json", include_media=True)
    assert result["ok"] and result["title"] == "文章标题" and result["body_text"] == "正文 & 说明"
    assert result["canonical_url"] == "https://mp.weixin.qq.com/s/sample"
    assert result["media"]["images"] == ["https://mmbiz.qpic.cn/article.jpg"]


def test_weibo_share_resolves_to_the_public_post_and_excludes_recommendations():
    def handle(request):
        assert request.headers["host"] == "weibo.com"
        assert request.url.path == "/2/detail/5184628856196406"
        assert request.url.query == b""
        return httpx.Response(200, text="""
          <div class="layout__cardSingle">
            <span class="layout__name">博主</span>
            <div class="layout__htmlText">正文<br>第二行 &amp; 示例</div>
            <img class="layout__picImg" src="https://wx1.sinaimg.cn/large/post.jpg">
          </div>
          <div class="layout__recommend">
            <div class="layout__htmlText">推荐内容</div>
            <img class="layout__picImg" src="https://wx1.sinaimg.cn/large/other.jpg">
          </div>
        """, headers={"content-type": "text/html"})

    result = service_for(handle).read_page("转发 https://m.weibo.cn/status/PzvA9pZY2?tracking=synthetic",
                                           output="json", include_media=True)
    assert result["ok"] and result["platform"] == "weibo"
    assert result["author"] == "博主" and result["body_text"] == "正文\n第二行 & 示例"
    assert result["source_url"] == "https://weibo.com/2/detail/5184628856196406"
    assert result["media"]["images"] == ["https://wx1.sinaimg.cn/large/post.jpg"]


def test_xigua_rejects_state_for_a_different_work():
    video = {"gid": "7364960700134851124", "title": "另一件作品"}
    data = {"data": {"storeState": {"detail": {"videoData": {"result": video}}}}}

    def handle(request):
        assert request.headers["host"] == "m.ixigua.com"
        assert request.url.path == "/video/7364960700134851123"
        return httpx.Response(200, text=f"<script>window._SSR_DATA = {json.dumps(data)}</script>",
                              headers={"content-type": "text/html"})

    result = service_for(handle).read_page("https://www.ixigua.com/7364960700134851123", output="json")
    assert not result["ok"] and result["error_code"] == "CONTENT_NOT_FOUND"


def test_youtube_player_embed_is_not_exposed_as_media():
    data = {
        "playabilityStatus": {"status": "OK"},
        "videoDetails": {"videoId": "AAAAAAAAAAA", "title": "视频", "shortDescription": "作者简介"},
        "streamingData": {"serverAbrStreamingUrl": "https://example.com/opaque"},
    }

    def handle(request):
        assert request.headers["host"] == "www.youtube.com"
        assert request.url.query == b"v=AAAAAAAAAAA"
        return httpx.Response(200, text=f"""
          <meta property="og:video:url" content="https://www.youtube.com/embed/AAAAAAAAAAA">
          <script>var ytInitialPlayerResponse = {json.dumps(data)}</script>
        """, headers={"content-type": "text/html"})

    result = service_for(handle).read_page("https://youtu.be/AAAAAAAAAAA?tracking=synthetic",
                                           output="json", include_media=True)
    assert result["ok"] and result["type"] == "video" and result["body_text"] == "作者简介"
    assert result["media"]["video_url"] is None and not result["media"]["has_video"]
    assert "VIDEO_MEDIA_UNAVAILABLE" in {warning["code"] for warning in result["warnings"]}


def test_telegram_reads_one_public_post_and_its_media():
    def handle(request):
        assert request.headers["host"] == "t.me" and request.url.path == "/example/42"
        assert request.url.query == b"embed=1"
        return httpx.Response(200, text="""
          <div data-post="example/41">
            <div class="tgme_widget_message_text">相邻帖子</div>
            <video class="tgme_widget_message_video" src="https://cdn1.telesco.pe/file/other.mp4"></video>
          </div>
          <div data-post="example/42">
            <div class="tgme_widget_message_author"><a>作者</a></div>
            <div class="tgme_widget_message_text">第一行<br>第二行 &amp; 文本</div>
            <video class="tgme_widget_message_video" src="https://cdn1.telesco.pe/file/target.mp4"></video>
          </div>
        """, headers={"content-type": "text/html"})

    result = service_for(handle).read_page("分享 https://t.me/s/example/42", output="json", include_media=True)
    assert result["ok"] and result["body_text"] == "第一行\n第二行 & 文本"
    assert result["author"] == "作者" and result["canonical_url"] == "https://t.me/example/42"
    assert result["media"]["video_url"] == "https://cdn1.telesco.pe/file/target.mp4"


def test_snapchat_uses_the_matching_video_object():
    work = "Spotlight_Requested"
    base = "https://www.snapchat.com"
    canonical = f"{base}/@author/spotlight/{work}"
    state = [
        {"@type": "VideoObject", "url": f"{base}/spotlight/Spotlight_Another", "name": "推荐",
         "contentUrl": "https://bolt-gcdn.sc-cdn.net/other"},
        {"@type": "VideoObject", "url": canonical, "name": "作品",
         "contentUrl": "https://bolt-gcdn.sc-cdn.net/target", "duration": "PT8S"},
    ]

    def handle(request):
        assert request.url.path == f"/spotlight/{work}"
        scripts = "".join(f'<script type="application/ld+json">{json.dumps(item)}</script>' for item in state)
        return httpx.Response(200, text=scripts, headers={"content-type": "text/html"})

    result = service_for(handle).read_page(f"{base}/spotlight/{work}", output="json", include_media=True)
    assert result["ok"] and result["canonical_url"] == canonical
    assert result["media"]["duration_ms"] == 8000
    assert result["media"]["video_url"] == "https://bolt-gcdn.sc-cdn.net/target"


def test_tiktok_visible_caption_skips_css_and_reports_limits():
    from social_reader.extractors import global_social
    from social_reader.extractors.common import ReadOptions

    class Renderer:
        def render(self, url, *, ready):
            return '''<a href="/@example/video/6718335390845095173"></a>
                <article data-e2e="video-desc"><style>.example {color: red}</style>公开描述</article>'''

    result, _ = global_social.read("https://www.tiktok.com/@example/video/6718335390845095173",
                                   None, ReadOptions(), renderer=Renderer())
    assert result.body == "公开描述"
    assert {warning.code for warning in result.warnings} == {"TEXT_MAY_BE_TRUNCATED", "MEDIA_UNAVAILABLE"}


def test_instagram_rejects_a_different_canonical_post():
    from social_reader.errors import ReaderError
    from social_reader.extractors import global_social
    from social_reader.extractors.common import ReadOptions
    import pytest

    class Renderer:
        def render(self, url, *, ready):
            return '''<link rel="canonical" href="https://www.instagram.com/p/another/">
                <span>BsOGulcndj-</span><h1>其他帖子的文字</h1>'''

    with pytest.raises(ReaderError):
        global_social.read("https://www.instagram.com/p/BsOGulcndj-/", None, ReadOptions(), renderer=Renderer())
