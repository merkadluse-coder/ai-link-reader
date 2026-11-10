"""MCP server (stdio) exposing read_page."""

from __future__ import annotations

from typing import Any, Literal

import anyio
from mcp.server.fastmcp import FastMCP

from .audit import configure_logging
from .config import Settings
from .service import ReaderService

mcp = FastMCP("social-research-reader")
_service: ReaderService | None = None


def _get_service() -> ReaderService:
    global _service
    if _service is None:
        _service = ReaderService(Settings.from_env())
    return _service


@mcp.tool()
async def read_page(
    url: str,
    output: Literal["json", "markdown", "both"] = "both",
    include_media: bool = False,
    include_comments: bool = False,
    include_transcript: bool = False,
    language: str = "zh-CN",
) -> dict[str, Any]:
    """读取用户主动提供的链接（小红书、抖音、头条视频、B站或公开网页），返回带来源的结构化结果。

    - url 可以是链接，也可以是整段 App 分享文字（自动提取第一个链接）。
    - 只读取用户给出的链接；不绕过登录、验证码、付费墙、试看或平台风控。
    - 抖音分享页需要浏览器会话，服务会自动用本机 Chrome 渲染兜底（单条约 10–25 秒，
      结果带 BROWSER_RENDERED）。小红书手机网页对部分笔记提示“仅 App 可看”时，会自动
      改读电脑网页版（结果带 DESKTOP_PAGE）。仍失败时如实告诉用户，不要猜测内容。
    - 成功：ok=true，含标题、作者、发布时间、互动数据、正文、来源 URL、解析器版本、
      置信度和 warnings；output 含 markdown 时附 body_markdown（已注明来源）。
    - 失败：ok=false，error_code 为 INVALID_URL / FETCH_BLOCKED / LOGIN_REQUIRED /
      CONTENT_NOT_FOUND / PARSE_CHANGED / RATE_LIMITED 等，不会伪装成功。
    - 使用结果时：关键事实要引用 source_url；summary 只是正文节选，不是模型结论；
      warnings 里的截断、低置信、视频未转写等提示必须转告用户。
    - 媒体 URL 默认不返回（include_media=true 才返回）；评论不含评论者身份。
    - 安装可选 ASR 组件后，头条、抖音、B站的公开视频可用 include_transcript=true 转写，返回 transcript.status 和带毫秒时间点的
      transcript.segments。status 非 ok 时没有逐字稿；作者简介不能当成口播。
    """
    return await anyio.to_thread.run_sync(
        lambda: _get_service().read_page(
            url, output, include_media, include_comments, include_transcript, language, caller="mcp"
        )
    )


def main() -> None:
    configure_logging(Settings.from_env().log_level)
    mcp.run()  # stdio transport; logs go to stderr


if __name__ == "__main__":
    main()
