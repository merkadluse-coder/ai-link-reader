"""Platform detection by parsed hostname suffix.

The Android app used url.contains("douyin.com"), which also matches
https://evil.example/?u=douyin.com; here only the real host decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from urllib.parse import urlsplit

from .extractors import bilibili, douyin, generic, global_social, kuaishou, snapchat, telegram, toutiao, wechat, weibo, xigua, xhs, youtube, yuque
from .security import host_matches

# P1 platforms: recognised, but read with the generic reader until their parsers ship.
PENDING_PLATFORMS: dict[str, tuple[str, ...]] = {
    "toutiao": ("toutiao.com", "toutiao.cn"),
    "bilibili": ("bilibili.com", "b23.tv"),
}
PLATFORM_LABELS = {
    "xhs": "小红书", "douyin": "抖音", "kuaishou": "快手", "toutiao": "今日头条",
    "bilibili": "哔哩哔哩", "wechat": "微信公众号", "generic": "网页",
    "weibo": "微博", "xigua": "西瓜视频", "youtube": "YouTube",
    "telegram": "Telegram", "snapchat": "Snapchat", "yuque": "语雀",
}


@dataclass(frozen=True)
class Route:
    platform: str
    extractor: ModuleType
    pending: bool = False


def route(url: str) -> Route:
    host = (urlsplit(url).hostname or "").lower()
    if host_matches(host, xhs.HOST_SUFFIXES):
        return Route("xhs", xhs)
    if host_matches(host, douyin.HOST_SUFFIXES):
        return Route("douyin", douyin)
    if host_matches(host, toutiao.HOST_SUFFIXES) and (toutiao.video_id(url) or toutiao.is_short(url)):
        return Route("toutiao", toutiao)
    if host_matches(host, bilibili.HOST_SUFFIXES) and bilibili.is_video_link(url):
        return Route("bilibili", bilibili)
    if wechat.is_article(url):
        return Route("wechat", wechat)
    if kuaishou.is_video_link(url):
        return Route("kuaishou", kuaishou)
    if weibo.post_id(url):
        return Route("weibo", weibo)
    if xigua.is_video_link(url):
        return Route("xigua", xigua)
    if youtube.video_id(url):
        return Route("youtube", youtube)
    if telegram.post_id(url):
        return Route("telegram", telegram)
    if snapchat.video_id(url):
        return Route("snapchat", snapchat)
    if social := global_social.identify(url):
        return Route(social[0], global_social)
    if yuque.is_document(url):
        return Route("yuque", yuque)
    for platform, suffixes in PENDING_PLATFORMS.items():
        if host_matches(host, suffixes):
            return Route(platform, generic, pending=True)
    return Route("generic", generic)
