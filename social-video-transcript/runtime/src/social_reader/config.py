"""Runtime settings, read from environment variables only (never from source)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _suffixes(raw: str) -> tuple[str, ...]:
    return tuple(s.strip().lower().lstrip(".") for s in raw.split(",") if s.strip())


@dataclass(frozen=True)
class Settings:
    api_key: str = ""  # SOCIAL_READER_API_KEY, guards the HTTP API
    allowed_host_suffixes: tuple[str, ...] = ()  # empty = any public host
    request_timeout_seconds: float = 15.0
    max_response_bytes: int = 5 * 1024 * 1024
    max_redirects: int = 5
    max_body_chars: int = 20_000
    daily_quota: int = 500
    burst_per_minute: int = 30
    log_level: str = "INFO"
    # Local development behind a fake-IP proxy (e.g. Clash 198.18.0.0/15). Never in production.
    dev_trusted_ranges: tuple[str, ...] = ()
    # Douyin dynamic rendering with the local Chrome: "auto" (if playwright is installed) | "on" | "off".
    # Programmatic default is off (tests stay offline); from_env() defaults to auto.
    browser_fallback: str = "off"
    browser_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.environ.get("SOCIAL_READER_API_KEY", ""),
            allowed_host_suffixes=_suffixes(os.environ.get("ALLOWED_HOST_SUFFIXES", "")),
            request_timeout_seconds=_float("REQUEST_TIMEOUT_SECONDS", 15.0),
            max_response_bytes=_int("MAX_RESPONSE_BYTES", 5 * 1024 * 1024),
            max_redirects=_int("MAX_REDIRECTS", 5),
            max_body_chars=_int("MAX_BODY_CHARS", 20_000),
            daily_quota=_int("DAILY_QUOTA", 500),
            burst_per_minute=_int("BURST_PER_MINUTE", 30),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            dev_trusted_ranges=tuple(
                r.strip() for r in os.environ.get("DEV_TRUSTED_RANGES", "").split(",") if r.strip()
            ),
            browser_fallback=os.environ.get("BROWSER_FALLBACK", "auto").strip().lower() or "auto",
            browser_timeout_seconds=_float("BROWSER_TIMEOUT_SECONDS", 30.0),
        )
