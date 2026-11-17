# AI Link Reader

[English](#english) | [中文](#中文)

## 中文

社媒与文档链接读取 Skill

把公开的社媒、视频和在线文档链接交给 AI 助手，读取正文并按需保存文字和可获取的图片、音视频。

## 国内社媒与新闻 MCP

`ai-link-reader-cn-mcp` 可接入 AnythingLLM Desktop 和其他支持 stdio 的 MCP 客户端。它接收一条公开作品链接或 App 分享文字，返回正文、来源、读取提示，以及按需提供的图片或音视频地址。

- **社媒与视频**：沿用小红书、微信公众号、微博、抖音、快手、B 站、今日头条和西瓜视频的现有入口。即刻的公开原创动态已验证正文、作者和单帖配图地址。
- **新闻文章**：已用公开文章跑通新华网、人民网（含人民日报电子版）、央视网、中新网、央广网、光明网、环球网、澎湃新闻、新京报、南方都市报、新浪新闻、凤凰网、腾讯新闻、网易新闻、搜狐新闻、ZAKER、界面新闻、第一财经、财联社和 36 氪。
- **受限样本**：财新返回可见预览并标记 `PREVIEW_ONLY`。百家号样本在普通网页请求中返回正文，MCP 实测跳转到访问验证页，因此列为受限入口。

在 `social-video-transcript/runtime` 目录安装，然后打开 AnythingLLM 的 **Settings → Agent Skills**。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[browser]'
```

在 AnythingLLM 的 `plugins/anythingllm_mcp_servers.json` 中加入以下条目。把 `command` 改为本机虚拟环境的绝对路径，并在 Agent Skills 页面点 **Refresh**。如果已有其他 MCP 服务，把新条目加进已有的 `mcpServers`。

```json
{
  "mcpServers": {
    "ai-link-reader-cn": {
      "command": "/absolute/path/to/ai-link-reader/social-video-transcript/runtime/.venv/bin/ai-link-reader-cn-mcp",
      "args": []
    }
  }
}
```

试用时可以在 Agent 对话里粘贴一条[新华网文章](https://www.news.cn/politics/20260819/edfbbc89e3034c9e840ebb5dcbe19a33/c.html)或[腾讯新闻文章](https://news.qq.com/rain/a/20250515A047NG00)，请它读取正文并标注来源。配置说明见 [AnythingLLM Desktop MCP 文档](https://docs.anythingllm.com/mcp-compatibility/desktop)。

也可以用这些已测入口复验。[环球网正文](https://china.huanqiu.com/article/4MPB5rzPsd8)、[即刻图文](https://m.okjike.com/originalPosts/64d4d47baac630c848fc643c)、[ZAKER 网页直链](https://www.myzaker.com/article/6afbd00432ce401a68000003)、[ZAKER App 分享页](https://app.myzaker.com/news/article.php?pk=6afbd00432ce401a68000003)。

默认使用系统 DNS。如果本机代理以 Fake-IP 方式返回占位地址，可在此 MCP 条目的 `env` 加入 `SOCIAL_READER_DOH_URL`，值为可访问的 [HTTPS JSON DNS 地址](https://developers.google.com/speed/public-dns/docs/doh/json)（例如 `https://dns.google/resolve`）。该解析器会收到请求中的域名。如果 DNS 服务本身需经 HTTP 代理才能访问，在此 MCP 条目的 `env` 中为它设置 `HTTPS_PROXY`。读取器会验证解析结果和每次跳转。

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
- **语雀** · 公开文档链接，已验证正文和图片引用。表格单元格以文本顺序返回。
- **TikTok** · `tiktok.com/@作者/video/<作品ID>` 公开视频页。使用本机 Chrome 读取页面显示的描述，文字可能折叠或截断，媒体地址待接入。
- **Instagram** · `instagram.com/p/<作品ID>/` 公开图文页。使用本机 Chrome 读取页面显示的文字，文字可能折叠或截断，媒体地址待接入。
- **Telegram** · `t.me/<公开频道>/<帖子ID>` 分享直链和 `t.me/s/<公开频道>/<帖子ID>` 网页入口。已验证公开帖子的正文、配图和视频，按链接读取单条帖子。
- **Snapchat** · `snapchat.com/spotlight/<作品ID>` 分享直链和含 `/@作者/spotlight/` 的网页直链。已验证公开 Spotlight 的简介、封面及 MP4 音视频轨。

微博视频、短链 `t.cn`、西瓜视频 App 短链 `v.ixigua.com`、知乎和微信视频号还没有通过对应内容的实测。西瓜视频和 YouTube 目前覆盖作品信息，音视频地址与字幕另行验证。Facebook、WhatsApp 频道更新、LinkedIn 和飞书等入口继续收集可复验的公开单条样本。

只读取可公开访问的内容。入口能否读取取决于作品状态和平台要求。视频描述是作者提供的文字，图片文字和视频口播可分别交由外部 OCR 和 ASR 服务处理。基础读取无需模型或云端识别账户。

### 实验性文档预览

以下入口需要运行读取器的机器安装 Chrome 和 Playwright。CLI 和通用 MCP 的 `read_page` 可以试读，国内媒体 MCP 的 `read_public_media` 面向社媒与新闻。

- **石墨文档** · 公开 `shimo.im/docs/…` 样本曾读到编辑区文字，部分样本可能读不到。返回成功时标记 `content_scope: visible_text`。
- **金山文档** · 公开 `kdocs.cn/l/…` 分享页有机会返回浏览器当前加载的文字，标记 `content_scope: visible_text`。同一链接复测可能失败，分页和未加载内容也可能缺失。
- **腾讯文档** · 公开 `docs.qq.com/doc/…` 样本只验证了可见大纲。结果标记 `content_scope: outline`，大纲放在 `outline_text`，正文为空。

## 保存文字和媒体

在 Skill 的 `runtime/` 目录执行以下命令。首次安装见上方安装说明。

```bash
.venv/bin/social-reader read --save-dir ./saved-example --download-media -- 'https://t.me/telegram/393'
```

正文保存在 `body.txt`，实验性文档预览根据类型保存为 `visible-text.txt` 或 `outline.txt`。媒体按类型编号保存。提取过程会剔除可识别的页面导航等杂项，正文中的推广内容可能保留。图片和视频使用平台返回的可用地址，能否取得原图或完整媒体取决于平台；当前不保证原图。单个媒体上限为 250 MiB，已有同名文件不会被覆盖。只保存文字时省略 `--download-media`。

## 提交平台需求

欢迎提交想读的平台及真实样例。请注明链接来自 PC 网页、iOS App 还是 Android App，以及希望读取的内容类型。提交可公开访问、未附带账号信息、设备参数或临时签名的链接。

[提交平台支持需求或分享链接](https://github.com/merkadluse-coder/ai-link-reader/issues/new?template=platform-request.md)

## 许可证

本仓库采用 [MIT 许可证](LICENSE)。


## English

AI Link Reader is an Agent Skill for reading public social-media posts, videos, articles, and document links. It extracts available text and media references from web URLs and app share text.

## Chinese media MCP

The `ai-link-reader-cn-mcp` stdio server works with MCP clients such as AnythingLLM Desktop. Its `read_public_media` tool accepts a public Chinese social or news link, including a URL pasted inside app share text. It returns readable text, the source URL, and retrieval notices. Set `include_media` to request available media URLs.

The domestic server includes the existing Xiaohongshu, WeChat Official Accounts, Weibo, Douyin, Kuaishou, Bilibili, Toutiao and Xigua routes. A public Jike original post returned text, the author and image URLs. Live article samples passed for Xinhua, People's Daily (including the digital newspaper), CCTV, China News Service, CNR, Guangming, Huanqiu, The Paper, Beijing News, Southern Metropolis Daily, Sina, Ifeng, Tencent News, NetEase, Sohu, ZAKER, Jiemian, Yicai, CLS and 36Kr. Caixin is marked as a preview. Baijiahao served the article through a regular web request and redirected the MCP request to an access check.

Use the [installation and example configuration above](#国内社媒与新闻-mcp). AnythingLLM Desktop reads the server configuration from `plugins/anythingllm_mcp_servers.json`. Refresh **Settings → Agent Skills** to load it. [AnythingLLM Desktop MCP documentation](https://docs.anythingllm.com/mcp-compatibility/desktop)

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
- **Yuque** — public document text and image references. Table cells are returned in reading order.
- **Google Docs** — text from tested public edit, view and published document URLs.
- **Google Scholar** — the current publication list on public author profile pages. Search may require session verification, and full papers must be read at their sources.
- **Baidu Wenku** — visible text from tested document pages, marked as a potentially incomplete preview.

Access depends on each document or post and its sharing settings. OCR and ASR can be supplied by separate processors. The repository's [MIT license](LICENSE) covers the open-source reader.

### Experimental document previews

These previews require Chrome and Playwright on the machine running the reader. Use the CLI or the general MCP `read_page` tool. The domestic media MCP tool covers social and news links.

- **Shimo** — public `shimo.im/docs/…` links may return loaded editor text as `content_scope: visible_text`. Some samples return no text.
- **WPS / KDocs** — public `kdocs.cn/l/…` share pages may return loaded text as `content_scope: visible_text`. The same link can fail on repeat attempts, and unloaded pages can be missing.
- **Tencent Docs** — tested public `docs.qq.com/doc/…` links returned the visible outline. Results have `content_scope: outline` and `outline_text`, with an empty body.

### Save text and media

From the Skill's `runtime/` directory, run:

```bash
.venv/bin/social-reader read --save-dir ./saved-example --download-media -- 'https://t.me/telegram/393'
```

The reader saves body text to `body.txt` and experimental document previews to `visible-text.txt` or `outline.txt`. It numbers available media files. Extraction removes recognizable navigation and page clutter. Promotional content within the source may remain. Files use the available source URLs, so original-image quality depends on the platform. Each media file is limited to 250 MiB and existing filenames are preserved. Omit `--download-media` to save text only.

### Request a platform

Use the [platform request template](https://github.com/merkadluse-coder/ai-link-reader/issues/new?template=platform-request.md) to share a publicly accessible example. Tell us whether it came from a desktop page, iOS, Android, or a desktop client, and which content you want to read.
