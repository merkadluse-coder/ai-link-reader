# 安装 social-video-transcript

1. 将 `social-video-transcript` 整个文件夹放入支持 Agent Skills 的客户端配置目录。
2. 准备 Python 3.11 或以上。从 Skill 内的 `runtime/` 目录运行以下命令。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
```

读取一条公开作品。也可以把手机 App 分享文案作为一个完整参数传入。

```bash
.venv/bin/social-reader read --json -- 'https://www.toutiao.com/video/7703939383367680009/'
```

默认返回正文和媒体可用状态。处理器需要媒体地址时，加入 `--include-media`，从 `media.images`、`media.video_url` 或可用时的 `media.audio_url` 取得。视频站点返回的媒体地址可能随时间失效。

部分公开抖音页、TikTok 和 Instagram 页面需要浏览器渲染。石墨、金山和腾讯文档也提供实验性浏览器预览。安装本机 Google Chrome 后，在同一环境安装可选依赖。

```bash
.venv/bin/python -m pip install '.[browser]'
```

文档预览返回 `content_scope`。石墨和金山的 `visible_text` 表示浏览器加载的文字，保存为 `visible-text.txt`。腾讯文档的 `outline` 只返回 `outline_text`，保存为 `outline.txt`。

基础读取不需要 FFmpeg、OCR 或 ASR 模型。逐字稿或画面文字需要可用的独立后处理组件。
