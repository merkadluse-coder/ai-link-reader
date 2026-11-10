# Social Content Reader

[English](#english) | [中文](#中文)

## 中文

社媒与文档链接读取 Skill

把公开的社媒、视频和在线文档链接交给 AI 助手，读取正文并按需保存文字和可获取的图片、音视频。

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

- **Google 文档** · 公开的文档编辑、查看及网页发布链接，读取正文文本。
- **Google 学术** · 公开学者主页，读取当前页论文列表。检索页可能要求会话验证，论文全文需访问原文。
- **百度文库** · `wenku.baidu.com/view/…` 和 `/tfview/…`，读取页面公开显示的试读文字并标记可能不完整。
- **石墨文档** · 通过 Chrome 读取已验证的公开文档页面文字。
- **金山文档** · 通过 Chrome 读取已验证页面加载的文字，分页内容可能不完整。
- **腾讯文档** · 通过 Chrome 读取已验证文档的可见大纲，正文待接入。
- **语雀** · 公开文档链接，已验证正文和图片引用。表格单元格以文本顺序返回。
- **TikTok** · `tiktok.com/@作者/video/<作品ID>` 公开视频页。使用本机 Chrome 读取页面显示的描述，文字可能折叠或截断，媒体地址待接入。
- **Instagram** · `instagram.com/p/<作品ID>/` 公开图文页。使用本机 Chrome 读取页面显示的文字，文字可能折叠或截断，媒体地址待接入。
- **Telegram** · `t.me/<公开频道>/<帖子ID>` 分享直链和 `t.me/s/<公开频道>/<帖子ID>` 网页入口。已验证公开帖子的正文、配图和视频，按链接读取单条帖子。
- **Snapchat** · `snapchat.com/spotlight/<作品ID>` 分享直链和含 `/@作者/spotlight/` 的网页直链。已验证公开 Spotlight 的简介、封面及 MP4 音视频轨。

微博视频、短链 `t.cn`、西瓜视频 App 短链 `v.ixigua.com`、知乎和微信视频号还没有通过对应内容的实测。西瓜视频和 YouTube 目前覆盖作品信息，音视频地址与字幕另行验证。Facebook、WhatsApp 频道更新、LinkedIn 和飞书等入口继续收集可复验的公开单条样本。

只读取可公开访问的内容。入口能否读取取决于作品状态和平台要求。视频描述是作者提供的文字，图片文字和视频口播可分别交由外部 OCR 和 ASR 服务处理。基础读取无需模型或云端识别账户。

## 保存文字和媒体

在 Skill 的 `runtime/` 目录执行以下命令。首次安装见上方安装说明。

```bash
.venv/bin/social-reader read --save-dir ./saved-example --download-media -- 'https://t.me/telegram/393'
```

正文保存在 `body.txt`，媒体按类型编号保存。提取过程会剔除可识别的页面导航等杂项，正文中的推广内容可能保留。图片和视频使用平台返回的可用地址，能否取得原图或完整媒体取决于平台；当前不保证原图。单个媒体上限为 250 MiB，已有同名文件不会被覆盖。只保存文字时省略 `--download-media`。

## 提交平台需求

欢迎提交想读的平台及真实样例。请注明链接来自 PC 网页、iOS App 还是 Android App，以及希望读取的内容类型。提交可公开访问、未附带账号信息、设备参数或临时签名的链接。

[提交平台支持需求或分享链接](https://github.com/merkadluse-coder/social-content-reader/issues/new?template=platform-request.md)

## 许可证

本仓库采用 [MIT 许可证](LICENSE)。


## English

Social Content Reader is an Agent Skill for reading public social-media posts, videos, articles, and document links. It extracts available text and media references from web URLs and app share text. The core reader runs locally without an OCR or ASR model.

### Install and use

Copy the `social-video-transcript/` folder into your client's Skills directory and follow the [setup guide](social-video-transcript/references/setup.md). Paste a public link or app share text into your assistant. The existing folder and skill name are retained for compatibility.

### Tested coverage

- **Toutiao, Douyin, Bilibili and Kuaishou** — public video pages and selected app share links. Available media differs by work and platform.
- **Xiaohongshu** — public notes, images and selected video references, including tested `xhslink.com/o/` shares.
- **WeChat Official Accounts** — public `mp.weixin.qq.com/s/` articles and images.
- **Weibo** — public post text and images from tested desktop and mobile post links.
- **Xigua and YouTube** — video title, description, cover and duration from tested public links. Media streams and subtitles remain under investigation.
- **TikTok and Instagram** — visible post text from tested public pages via local Chrome. Text may be collapsed or truncated, and media extraction remains under investigation.
- **Telegram and Snapchat** — public Telegram channel posts and Snapchat Spotlight pages. Text and video references have been verified on samples.
- **Shimo** — visible text from a tested public document in Chrome.
- **WPS / KDocs** — text loaded from a tested public document in Chrome; paginated content may be incomplete.
- **Tencent Docs** — the visible outline from a tested public document in Chrome; body extraction remains under investigation.
- **Yuque** — public document text and image references. Table cells are returned in reading order.
- **Google Docs** — text from tested public edit, view and published document URLs.
- **Google Scholar** — the current publication list on public author profile pages. Search may require session verification, and full papers must be read at their sources.
- **Baidu Wenku** — visible text from tested document pages, marked as a potentially incomplete preview.

Access depends on each document or post and its sharing settings. OCR and ASR can be supplied by separate processors. The repository's [MIT license](LICENSE) covers the open-source reader.

### Save text and media

From the Skill's `runtime/` directory, run:

```bash
.venv/bin/social-reader read --save-dir ./saved-example --download-media -- 'https://t.me/telegram/393'
```

The reader saves extracted text to `body.txt` and numbers available media files. Extraction removes recognizable navigation and page clutter. Promotional content within the source may remain. Files use the available source URLs, so original-image quality depends on the platform. Each media file is limited to 250 MiB and existing filenames are preserved. Omit `--download-media` to save text only.

### Request a platform

Use the [platform request template](https://github.com/merkadluse-coder/social-content-reader/issues/new?template=platform-request.md) to share a publicly accessible example. Tell us whether it came from a desktop page, iOS, Android, or a desktop client, and which content you want to read.
