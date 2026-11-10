# 社媒内容读取 Skill

把公开的社媒链接或 App 分享文案交给 AI 助手，读取网页正文、作者描述和可用的媒体信息。需要交给其他工具处理时，可以显式返回媒体地址。基础读取只需要 Python 和网络。

## 安装和使用

将 `social-video-transcript/` 放入客户端的 Skills 目录，按[安装说明](social-video-transcript/references/setup.md)安装本地读取器。然后在助手里粘贴链接，例如“读取这篇公众号文章，概括正文”或“看看这条视频链接能否取到媒体”。

## 实测入口

- **今日头条** · `toutiao.com/video/<作品ID>/` 网页直链、App 分享直链和 `m.toutiao.com/is/…` 短链。已验证公开视频媒体。
- **抖音** · `douyin.com/video/<作品ID>` 网页直链和 `v.douyin.com/…` App 短链。部分分享页需要本机 Chrome 渲染。
- **哔哩哔哩** · `bilibili.com/video/BV…/` 网页直链和 `b23.tv/…` App 短链。支持 `?p=N` 选分 P，默认读取 P1。
- **小红书** · `xiaohongshu.com` 公开笔记网页链接和 `xhslink.com/o/…` App 短链。已验证笔记正文、配图和部分视频笔记的媒体地址。请保留平台原始分享链接。
- **微信公众号** · `mp.weixin.qq.com/s/…` 文章直链及带该链接的分享文案。已验证正文和配图。
- **快手** · `kuaishou.com/short-video/<作品ID>` 网页直链和 `v.kuaishou.com/…` App 短链。已验证公开视频地址及 MP4 内的音视频轨。
- **微博** · `weibo.com/2/detail/<博文ID>` 网页直链，以及 `m.weibo.cn/status/…` 手机分享链接。读取公开博文正文、作者和配图。
- **西瓜视频** · `www.ixigua.com/<作品ID>` 网页直链，以及 `m.ixigua.com/video/…` 和 `m.ixigua.com/dx/…` 手机作品页。读取标题、作者、简介、封面和时长。
- **YouTube** · `youtube.com/watch?v=…` 网页直链和 `youtu.be/…` 分享短链。读取标题、频道、简介、封面和时长。

- **TikTok** · `tiktok.com/@作者/video/<作品ID>` 公开视频页。使用本机 Chrome 读取页面显示的描述，文字可能折叠或截断，媒体地址待接入。
- **Instagram** · `instagram.com/p/<作品ID>/` 公开图文页。使用本机 Chrome 读取页面显示的文字，文字可能折叠或截断，媒体地址待接入。
- **Telegram** · `t.me/<公开频道>/<帖子ID>` 分享直链和 `t.me/s/<公开频道>/<帖子ID>` 网页入口。已验证公开帖子的正文、配图和视频，按链接读取单条帖子。
- **Snapchat** · `snapchat.com/spotlight/<作品ID>` 分享直链和含 `/@作者/spotlight/` 的网页直链。已验证公开 Spotlight 的简介、封面及 MP4 音视频轨。

微博视频、短链 `t.cn`、西瓜视频 App 短链 `v.ixigua.com`、知乎和微信视频号还没有通过对应内容的实测。西瓜视频和 YouTube 目前覆盖作品信息，音视频地址与字幕另行验证。Facebook、WhatsApp 频道更新和 LinkedIn 等入口继续收集可复验的公开单条样本。

只读取可公开访问的内容。入口能否读取取决于作品状态和平台要求。视频描述是作者提供的文字，图片文字和视频口播可分别交由外部 OCR 和 ASR 服务处理。基础读取无需模型或云端识别账户。

## 提交平台需求

欢迎提交想读的平台及真实样例。请注明链接来自 PC 网页、iOS App 还是 Android App，以及希望读取的内容类型。提交可公开访问、未附带账号信息、设备参数或临时签名的链接。

[提交平台支持需求或分享链接](https://github.com/merkadluse-coder/social-video-transcript/issues/new?template=platform-request.md)

## 许可证

本仓库采用 [MIT 许可证](LICENSE)。
