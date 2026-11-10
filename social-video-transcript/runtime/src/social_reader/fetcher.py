"""SSRF-safe HTTP fetching.

Every hop (including each redirect) is validated and DNS-resolved by
security.resolve_public(); the connection is then pinned to that vetted IP so
a DNS rebind between check and connect cannot reach an internal address.
TLS still verifies the certificate against the real hostname (SNI).
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from urllib.parse import urljoin

import httpx

from .audit import get_logger
from .config import Settings
from .errors import ErrorCode, ReaderError
from .security import Resolver, ValidatedUrl, host_matches, resolve_public, system_resolver, validate_url

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/json")
_REDIRECTS = (301, 302, 303, 307, 308)
_META_CHARSET = re.compile(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE)


@dataclass
class FetchResult:
    url: str  # final URL after redirects
    status: int
    content_type: str
    text: str
    truncated: bool = False
    redirects: list[str] = field(default_factory=list)


class PinnedTransport(httpx.BaseTransport):
    """Connects only to IPs the fetcher has vetted for the request's host."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner
        self.pins: dict[str, str] = {}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        ip = self.pins.get(host)
        if ip is None:  # defence in depth: never connect to an unvetted host
            raise ReaderError(ErrorCode.INVALID_URL, "连接目标未通过安全校验")
        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            extensions["sni_hostname"] = host
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=ip),
            headers=request.headers,  # keeps the original Host header
            stream=request.stream,
            extensions=extensions,
        )
        return self.inner.handle_request(pinned)

    def close(self) -> None:
        self.inner.close()


def _status_error(status: int) -> ReaderError | None:
    if status == 401:
        return ReaderError(ErrorCode.LOGIN_REQUIRED, "该页面需要登录后才能读取")
    if status == 403:
        return ReaderError(ErrorCode.FETCH_BLOCKED, "目标站点拒绝访问（403），未做任何绕过")
    if status in (404, 410):
        return ReaderError(ErrorCode.CONTENT_NOT_FOUND, "页面不存在或已删除")
    if status == 429:
        return ReaderError(ErrorCode.RATE_LIMITED, "目标站点限流（429），请稍后再试")
    if status == 451:
        return ReaderError(ErrorCode.PERMISSION_REQUIRED, "该内容因法律原因不可访问")
    if status >= 500:
        return ReaderError(ErrorCode.FETCH_BLOCKED, f"目标站点错误（{status}）", retryable=True)
    if status >= 400:
        return ReaderError(ErrorCode.FETCH_BLOCKED, f"请求失败（{status}）")
    return None


def _decode(body: bytes, content_type: str) -> str:
    match = re.search(r"charset=([A-Za-z0-9_-]+)", content_type, re.IGNORECASE)
    charset = match.group(1) if match else None
    if charset is None:
        meta = _META_CHARSET.search(body[:4096])
        charset = meta.group(1).decode("ascii") if meta else "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


class Fetcher:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver = system_resolver,
    ) -> None:
        self.settings = settings
        self.resolver = resolver
        self.dev_trusted = tuple(ipaddress.ip_network(r, strict=False) for r in settings.dev_trusted_ranges)
        if self.dev_trusted:
            get_logger("social_reader.fetcher").warning(
                "DEV_TRUSTED_RANGES=%s 已开启：DNS 级 SSRF 检查对这些地址失效，仅限本机开发，生产环境禁止",
                ",".join(settings.dev_trusted_ranges),
            )
        self._transport_factory = (lambda: transport) if transport else (
            # keep-alive off: a TLS connection made for one hostname is never reused for another
            lambda: httpx.HTTPTransport(limits=httpx.Limits(max_keepalive_connections=0))
        )

    def fetch(
        self, url: str, *, user_agent: str = MOBILE_UA, referer: str | None = None,
        scope: tuple[str, ...] = (),
    ) -> FetchResult:
        with self._stream(url, user_agent=user_agent, referer=referer, scope=scope) as (target, response, hops):
            return self._finish(target, response, hops)

    def resolve_redirect(
        self, url: str, *, scope: tuple[str, ...], stop_at: Callable[[str], bool],
    ) -> str:
        """Expand a short link; stop on a checked work URL before fetching its page."""
        if not scope:
            raise ValueError("short-link resolution requires a host scope")
        with self._stream(url, referer=None, scope=scope, stop_at=stop_at) as (target, response, _):
            if response is not None and (error := _status_error(response.status_code)):
                raise error
            return target.url

    def download_mp4(self, url: str, path: Path, *, referer: str, scope: tuple[str, ...], limit: int) -> None:
        if not scope:
            raise ValueError("media download requires a host scope")
        deadline = monotonic() + 30
        with self._stream(url, referer=referer, scope=scope) as (_, response, _):
            error = _status_error(response.status_code)
            if error:
                raise error
            if response.status_code != 200:
                raise ReaderError(ErrorCode.FETCH_BLOCKED, "媒体没有返回完整文件")
            mime = response.headers.get("content-type", "").partition(";")[0].strip().lower()
            if mime not in {"video/mp4", "audio/mp4", "audio/m4a", "audio/x-m4a", "application/octet-stream"}:
                raise ReaderError(ErrorCode.UNSUPPORTED_PLATFORM, "媒体没有返回 MP4")
            length = response.headers.get("content-length", "")
            if length.isdecimal() and int(length) > limit:
                raise ReaderError(ErrorCode.UNSUPPORTED_PLATFORM, "媒体超过转写大小上限")
            size = 0
            try:
                with path.open("xb") as stream:
                    for chunk in response.iter_bytes(chunk_size=64 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise ReaderError(ErrorCode.UNSUPPORTED_PLATFORM, "媒体超过转写大小上限")
                        if monotonic() > deadline:
                            raise ReaderError(ErrorCode.FETCH_TIMEOUT, "媒体下载超时")
                        stream.write(chunk)
            except httpx.TimeoutException:
                raise ReaderError(ErrorCode.FETCH_TIMEOUT, "媒体下载超时") from None
            except httpx.HTTPError:
                raise ReaderError(ErrorCode.FETCH_BLOCKED, "媒体下载失败") from None

    @contextmanager
    def _stream(
        self, url: str, *, user_agent: str = MOBILE_UA, referer: str | None, scope: tuple[str, ...],
        stop_at: Callable[[str], bool] | None = None,
    ):
        def checked(raw: str) -> ValidatedUrl:
            target = validate_url(raw, self.settings.allowed_host_suffixes)
            if scope and (target.scheme != "https" or target.port != 443 or not host_matches(target.host, scope)):
                raise ReaderError(ErrorCode.INVALID_URL, "目标不在该平台的 HTTPS 允许清单内")
            return target

        target = checked(url)
        transport = PinnedTransport(self._transport_factory())
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        # A fresh client per fetch: cookies never leak between requests or users.
        with httpx.Client(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(self.settings.request_timeout_seconds),
            headers=headers,
        ) as client:
            hops: list[str] = []
            for _ in range(self.settings.max_redirects + 1):
                transport.pins[target.host] = resolve_public(target, self.resolver, self.dev_trusted)[0]
                response = self._send(client, target)
                try:
                    if response.status_code in _REDIRECTS:
                        location = response.headers.get("location")
                        if not location:
                            raise ReaderError(ErrorCode.FETCH_BLOCKED, "重定向缺少目标地址")
                        target = checked(urljoin(target.url, location))
                        hops.append(target.url)
                        if stop_at is not None and stop_at(target.url):
                            yield target, None, hops
                            return
                        continue
                    yield target, response, hops
                    return
                finally:
                    response.close()
        raise ReaderError(ErrorCode.FETCH_BLOCKED, "重定向次数过多")

    def _send(self, client: httpx.Client, target: ValidatedUrl) -> httpx.Response:
        try:
            return client.send(client.build_request("GET", target.url), stream=True)
        except ReaderError:
            raise
        except httpx.TimeoutException:
            raise ReaderError(ErrorCode.FETCH_TIMEOUT, "请求超时") from None
        except httpx.HTTPError:
            raise ReaderError(ErrorCode.FETCH_BLOCKED, "无法连接目标站点", retryable=True) from None

    def _finish(self, target: ValidatedUrl, response: httpx.Response, hops: list[str]) -> FetchResult:
        error = _status_error(response.status_code)
        if error:
            raise error
        content_type = response.headers.get("content-type", "").lower()
        if content_type and not content_type.startswith(_TEXT_TYPES):
            raise ReaderError(
                ErrorCode.UNSUPPORTED_PLATFORM, f"暂不支持该内容类型：{content_type.split(';')[0]}"
            )
        limit = self.settings.max_response_bytes
        chunks: list[bytes] = []
        size = 0
        truncated = False
        try:
            for chunk in response.iter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    truncated = True
                    break
        except httpx.TimeoutException:
            raise ReaderError(ErrorCode.FETCH_TIMEOUT, "读取页面超时") from None
        except httpx.HTTPError:
            raise ReaderError(ErrorCode.FETCH_BLOCKED, "读取页面失败", retryable=True) from None
        body = b"".join(chunks)[:limit]
        return FetchResult(
            url=target.url,
            status=response.status_code,
            content_type=content_type,
            text=_decode(body, content_type),
            truncated=truncated,
            redirects=hops,
        )
