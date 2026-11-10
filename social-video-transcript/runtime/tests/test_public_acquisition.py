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
