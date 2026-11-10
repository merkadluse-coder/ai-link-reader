"""URL validation, SSRF defence, log redaction and rate limiting.

docs/COMPLIANCE_AND_SECURITY.md §5: block private, loopback, link-local and
cloud-metadata targets, re-check every redirect hop, redact tokens in logs.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .errors import ErrorCode, ReaderError

MAX_URL_LENGTH = 2048
ALLOWED_PORTS = {None, 80, 443, 8080, 8443}
BLOCKED_HOST_SUFFIXES = ("localhost", "local", "internal", "intranet", "lan", "home.arpa")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], list[str]]


@dataclass(frozen=True)
class ValidatedUrl:
    url: str  # normalized, fragment removed
    scheme: str
    host: str  # lowercase, IDNA-encoded
    port: int  # effective port

    @property
    def netloc_for_host_header(self) -> str:
        default = 443 if self.scheme == "https" else 80
        host = f"[{self.host}]" if ":" in self.host else self.host
        return host if self.port == default else f"{host}:{self.port}"


def _invalid(message: str) -> ReaderError:
    return ReaderError(ErrorCode.INVALID_URL, message)


def host_matches(host: str, suffixes: Iterable[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == s or host.endswith("." + s) for s in suffixes)


def validate_url(raw: str, allowed_host_suffixes: tuple[str, ...] = ()) -> ValidatedUrl:
    """Syntactic checks only; resolve_public() does the network-level check."""
    if not isinstance(raw, str) or not raw.strip():
        raise _invalid("URL 不能为空")
    raw = raw.strip()
    if len(raw) > MAX_URL_LENGTH:
        raise _invalid("URL 过长")
    if any(ord(c) < 0x20 or c.isspace() for c in raw):
        raise _invalid("URL 含有空白或控制字符")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise _invalid("URL 格式无效") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise _invalid("只支持 http 或 https 链接")
    if parts.username is not None or parts.password is not None:
        raise _invalid("URL 不能包含用户名或密码")
    if not parts.hostname:
        raise _invalid("URL 缺少域名")
    if port not in ALLOWED_PORTS:
        raise _invalid("不支持该端口")
    try:
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise _invalid("域名格式无效") from None
    if host_matches(host, BLOCKED_HOST_SUFFIXES) or "." not in host and ":" not in host:
        raise _invalid("拒绝访问本机或内网主机名")
    literal = _parse_ip(host)
    if literal is not None and not is_public_ip(literal):
        raise _invalid("拒绝访问内网、本机或云元数据地址")
    if allowed_host_suffixes and not host_matches(host, allowed_host_suffixes):
        raise _invalid("该域名不在允许清单内")
    effective_port = port or (443 if scheme == "https" else 80)
    url = urlunsplit((scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))
    return ValidatedUrl(url=url, scheme=scheme, host=host, port=effective_port)


def _parse_ip(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def is_public_ip(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if embedded is not None and not is_public_ip(embedded):
            return False
    # is_global is False for RFC1918, loopback, link-local (169.254.169.254),
    # shared 100.64/10 (Alibaba metadata 100.100.100.200) and ULA (fd00:ec2::254).
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


def resolve_public(
    target: ValidatedUrl,
    resolver: Resolver = system_resolver,
    dev_trusted: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (),
) -> list[str]:
    """Resolve and require EVERY address to be public (defeats mixed DNS answers).

    `dev_trusted` (DEV_TRUSTED_RANGES) admits proxy fake-IP answers such as
    198.18.0.0/15 on a developer machine. The proxy then resolves the real
    target itself, so DNS-level SSRF checks no longer apply: never in production.
    """
    literal = _parse_ip(target.host)
    if literal is not None:
        return [str(literal)]
    try:
        addresses = resolver(target.host, target.port)
    except (OSError, UnicodeError):
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "域名无法解析", retryable=True) from None
    if not addresses:
        raise ReaderError(ErrorCode.CONTENT_NOT_FOUND, "域名无法解析", retryable=True)
    for addr in addresses:
        ip = _parse_ip(addr.split("%", 1)[0])
        if ip is not None and any(ip in net for net in dev_trusted):
            continue
        if ip is None or not is_public_ip(ip):
            raise _invalid("拒绝访问内网、本机或云元数据地址")
    return addresses


# ── Redaction ────────────────────────────────────────────────────────────

_SENSITIVE_PARAM = re.compile(
    r"(token|sign|sig$|secret|key|auth|cookie|session|pass|ticket|bogus|credential|code$"
    # Account/device identifiers carried by share links (Douyin did/iid/u_code, XHS shareRedId).
    r"|^did$|^iid$|uid$|device|openid|unionid|user_?id|share_?did|share_?id|shareredid|apptime)",
    re.IGNORECASE,
)
_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+")
_HEADER_SECRET = re.compile(
    r"(?i)\b(cookie|set-cookie|authorization|x-api-key)\b(\s*[:=]\s*)([^\r\n]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_KEY_LIKE = re.compile(r"\b(sk-[A-Za-z0-9_-]{12,}|gsk_[A-Za-z0-9]{12,})")


def redact_url(url: str, _depth: int = 0) -> str:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "[unparseable-url]"
    netloc = parts.hostname or ""
    if ":" in netloc:
        netloc = f"[{netloc}]"
    if port:
        netloc = f"{netloc}:{port}"
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if _SENSITIVE_PARAM.search(key):
            value = "REDACTED"
        elif _depth < 2 and value.lower().startswith(("http://", "https://")):
            value = redact_url(value, _depth + 1)  # e.g. XHS originalUrl=<url with xsec_token>
        query.append((key, value))
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), ""))


def redact_text(text: str) -> str:
    text = _HEADER_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}REDACTED", text)
    text = _BEARER.sub("Bearer REDACTED", text)
    text = _KEY_LIKE.sub("REDACTED_KEY", text)
    return _URL_IN_TEXT.sub(lambda m: redact_url(m.group(0)), text)


class RedactingFilter(logging.Filter):
    """Attach to handlers so no log line can carry cookies, tokens or keys."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = None
        if record.exc_info:
            record.exc_text = redact_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


# ── Rate limiting ────────────────────────────────────────────────────────


class RateLimiter:
    """Per-caller burst window plus a rolling 24h quota (in-process, P0)."""

    def __init__(self, burst_per_minute: int, daily_quota: int, clock=time.monotonic) -> None:
        self.burst = burst_per_minute
        self.daily = daily_quota
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, caller: str = "default") -> None:
        now = self.clock()
        with self._lock:
            hits = self._hits.setdefault(caller, deque())
            while hits and now - hits[0] >= 86_400:
                hits.popleft()
            if len(hits) >= self.daily:
                raise ReaderError(ErrorCode.RATE_LIMITED, "已达到每日调用配额", retryable=False)
            if sum(1 for t in hits if now - t < 60) >= self.burst:
                raise ReaderError(ErrorCode.RATE_LIMITED, "调用过于频繁，请稍后再试")
            hits.append(now)
