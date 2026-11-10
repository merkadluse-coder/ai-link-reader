"""Optional dynamic rendering with the local Google Chrome (Playwright).

Server equivalent of the Android app's WebView fallback (DouyinWebScraper.kt):
some platforms only server-render a work after their own web security script
has given the browser a normal session (verified 2026-10-29 on Douyin share
pages: no session cookie → "抱歉出错了" template, session cookie → data).

Guardrails, by design:
- a fresh incognito context per render, closed afterwards: cookies are never
  stored, shared between requests or reused across users;
- plain Chrome: no stealth plugins, fingerprint spoofing or captcha solving;
  if the platform shows a verification page we stop and report it;
- main-frame navigation only to the platform's own domains; images, media and
  fonts are never downloaded.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol
from urllib.parse import urlsplit

from .audit import get_logger
from .errors import ErrorCode, ReaderError
from .security import host_matches, validate_url

log = get_logger("social_reader.browser")
_SKIPPED_RESOURCES = {"image", "media", "font"}
_CHALLENGE_TEXT = ("验证码", "安全验证", "滑动验证", "captcha", "verify you are human")


class BrowserUnavailable(Exception):
    """Playwright or a local Chrome is missing: callers fall back to their own error."""


class Renderer(Protocol):
    def render(self, url: str, *, ready: Callable[[str], bool]) -> str: ...


def playwright_installed() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


class ChromeRenderer:
    def __init__(
        self,
        allowed_host_suffixes: tuple[str, ...],
        *,
        timeout_seconds: float = 30.0,
        max_loads: int = 3,
        device: str = "Pixel 7",
        channel: str = "chrome",
        settle_seconds: float = 1.5,
    ) -> None:
        self.allowed = allowed_host_suffixes
        self.timeout = timeout_seconds
        self.max_loads = max_loads
        self.device = device
        self.channel = channel
        self.settle_seconds = settle_seconds

    def _route(self, route) -> None:  # playwright.sync_api.Route
        request = route.request
        if request.resource_type in _SKIPPED_RESOURCES:
            return route.abort()
        host = urlsplit(request.url).hostname or ""
        try:
            main_frame_navigation = request.is_navigation_request() and request.frame.parent_frame is None
        except Exception:  # e.g. service-worker requests have no frame
            main_frame_navigation = False
        if main_frame_navigation and not host_matches(host, self.allowed):
            return route.abort()
        return route.continue_()

    def render(self, url: str, *, ready: Callable[[str], bool]) -> str:
        """Load `url` until `ready(html)` or the load budget runs out; return the last HTML."""
        target = validate_url(url, self.allowed)
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserUnavailable("未安装 playwright") from None

        deadline = time.monotonic() + self.timeout
        started = time.monotonic()
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel=self.channel, headless=True)
            except PlaywrightError:
                raise BrowserUnavailable("无法启动本机 Chrome") from None
            try:
                context = browser.new_context(**p.devices[self.device], locale="zh-CN")
                context.route("**/*", self._route)
                page = context.new_page()
                html = ""
                for load in range(1, self.max_loads + 1):
                    remaining_ms = (deadline - time.monotonic()) * 1000
                    if remaining_ms <= 1000:
                        break
                    page.goto(target.url, wait_until="domcontentloaded", timeout=remaining_ms)
                    page.wait_for_timeout(min(self.settle_seconds * 1000, max(0, (deadline - time.monotonic()) * 1000)))
                    html = page.content()
                    if ready(html):
                        log.info("browser render ok loads=%s ms=%s", load, int((time.monotonic() - started) * 1000))
                        return html
                    body = page.inner_text("body") if page.query_selector("body") else ""
                    if len(body) < 600 and any(w in body.lower() for w in _CHALLENGE_TEXT):
                        raise ReaderError(
                            ErrorCode.FETCH_BLOCKED, "平台要求人机验证，已停止读取（不做任何绕过）", retryable=False
                        )
                return html
            except PlaywrightTimeout:
                raise ReaderError(ErrorCode.FETCH_TIMEOUT, "浏览器渲染超时") from None
            except PlaywrightError:
                raise ReaderError(ErrorCode.FETCH_BLOCKED, "浏览器渲染失败", retryable=True) from None
            finally:
                browser.close()  # discards the incognito context and every cookie in it
