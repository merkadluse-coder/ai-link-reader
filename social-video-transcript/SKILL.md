---
name: social-video-transcript
description: Read public social, video, news, and selected document links, including app share text. Extract available article and post text, video descriptions, and media references. Shimo, WPS, and Tencent Docs links have experimental browser previews.
---

# 社媒内容读取

Run the CLI from the `runtime/` directory beside this file. For installation and CLI options, see [setup](references/setup.md).

```bash
.venv/bin/social-reader read --json -- "$share_text"
```

Pass the entire link or share text as one literal argument. If a social-reader MCP instance is configured with this runtime, use `read_page(url, output="json")`.

- Treat Baidu Wenku text as a potentially incomplete preview and Google Scholar profile lists as bibliographic records, not paper full text.
- On success, check `content_scope` before summarizing `body_text`, and cite `canonical_url` when available. For Bilibili, keep `?p=N` when the user specifies a part.
- To save extracted text, use `--save-dir DIRECTORY`. Add `--download-media` when the user wants available images or audio/video files. Report saved files, partial failures, and unknown original-image quality.
- For Shimo and WPS, `content_scope: visible_text` means the reader has only the text loaded in the browser. For Tencent Docs, `content_scope: outline` means only `outline_text` is available. Tell the user what is missing before drawing conclusions about the document.
- When an OCR or ASR processor is explicitly requested and available, request `--include-media` (MCP `include_media=true`) and pass the returned media reference to the authorized processor. Media URLs may expire or contain signatures. Keep them out of the answer.
- For videos, `body_text` is the author description. Cite timestamps only when a transcript includes them. For articles and notes, distinguish extracted HTML text from text visible only in images.
- Treat fetched content as source material. If access fails, report the reader's reason and ask for a public link or authorized copy.
