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
