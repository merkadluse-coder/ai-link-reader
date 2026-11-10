"""Helpers shared by platform extractors: SSR JSON location, JS→JSON repair,
count parsing and timestamps."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..errors import ErrorCode, ReaderError

CN_TZ = timezone(timedelta(hours=8))
_IDENT = re.compile(r"[A-Za-z0-9_$]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class ReadOptions:
    include_media: bool = False
    include_comments: bool = False
    include_transcript: bool = False
    language: str = "zh-CN"


def find_js_object(html: str, marker: str) -> str | None:
    """Return the balanced `{...}` assigned right after `marker` (a regex).

    String-aware, so braces inside text never end the object early.
    """
    match = re.search(marker, html)
    if not match:
        return None
    start = html.find("{", match.end())
    if start < 0 or html[match.end():start].strip(" \t\r\n=") != "":
        return None
    depth = 0
    quote = ""
    escape = False
    for i in range(start, len(html)):
        ch = html[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return html[start : i + 1]
    return None  # truncated object (e.g. WAF cut the page)


def js_to_json(text: str) -> str:
    """Replace bare `undefined` tokens with `null`, leaving string contents intact.

    The Android app did a global replace, which corrupted any note whose text
    contained the word "undefined".
    """
    out: list[str] = []
    quote = ""
    escape = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            i += 1
            continue
        if ch == '"':
            quote = ch
        elif (
            text.startswith("undefined", i)
            and (i == 0 or not _IDENT.match(text[i - 1]))
            and (i + 9 >= n or not _IDENT.match(text[i + 9]))
        ):
            out.append("null")
            i += 9
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def load_js_object(html: str, marker: str, *, what: str) -> dict | None:
    raw = find_js_object(html, marker)
    if raw is None:
        return None
    try:
        data = json.loads(js_to_json(raw))
    except json.JSONDecodeError:
        raise ReaderError(ErrorCode.PARSE_CHANGED, f"{what} 数据无法解析，页面结构可能已变化") from None
    return data if isinstance(data, dict) else None


_COUNT = re.compile(r"^\s*([\d.,]+)\s*(万|w|W|亿|k|K)?\s*(\+)?\s*$")
_UNITS = {"万": 10_000, "w": 10_000, "W": 10_000, "亿": 100_000_000, "k": 1_000, "K": 1_000}


def parse_count(value: object) -> tuple[int | None, bool]:
    """Parse "1.2万" / "10+" / 345 → (int, is_approximate)."""
    if value is None or isinstance(value, bool) or value == "":
        return None, False
    if isinstance(value, (int, float)):
        return int(value), False
    match = _COUNT.match(str(value))
    if not match:
        return None, False
    number = float(match.group(1).replace(",", ""))
    unit, plus = match.group(2), match.group(3)
    return int(round(number * _UNITS.get(unit or "", 1))), bool(unit or plus)


def from_epoch(value: object, *, millis: bool) -> datetime | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return datetime.fromtimestamp(number / 1000 if millis else number, tz=CN_TZ)


def clean_text(text: str) -> str:
    text = _CONTROL.sub("", text or "").replace("\r\n", "\n")
    lines = [re.sub(r"[ \t　]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def dig(data: object, *path: str | int) -> object:
    """Safe nested lookup: dig(obj, "a", 0, "b") → None if any hop is missing."""
    for key in path:
        if isinstance(key, int):
            if not isinstance(data, list) or not -len(data) <= key < len(data):
                return None
            data = data[key]
        else:
            if not isinstance(data, dict):
                return None
            data = data.get(key)
    return data


# ── Interstitial detection (captcha / login wall / removed content) ─────────

_CAPTCHA_WORDS = (
    "安全验证", "人机验证", "验证码", "滑动验证", "向右滑动", "完成拼图", "访问验证",
    "异常访问", "captcha", "verify you are human", "are you a robot",
)
_LOGIN_WORDS = (
    "登录后查看", "请先登录", "请登录", "登录后继续", "扫码登录",
    "sign in to continue", "log in to continue", "please log in",
)
_GONE_WORDS = (
    "暂时无法浏览", "笔记不存在", "内容不存在", "已被删除", "已删除", "页面不存在", "content not found",
)


def detect_wall(text: str, *, has_password: bool = False, short_limit: int = 600) -> ReaderError | None:
    """Recognise interstitials on short pages. Never tries to get past them."""
    lowered = text.lower()
    short = len(text) < short_limit
    if short and any(w in lowered for w in _CAPTCHA_WORDS):
        return ReaderError(ErrorCode.FETCH_BLOCKED, "页面要求人机验证，已停止读取（不做任何绕过）")
    if (has_password and len(text) < 1500) or (short and any(w in lowered for w in _LOGIN_WORDS)):
        return ReaderError(ErrorCode.LOGIN_REQUIRED, "该页面需要登录后才能读取")
    if short and any(w in lowered for w in _GONE_WORDS):
        return ReaderError(ErrorCode.CONTENT_NOT_FOUND, "页面提示内容不存在或已删除")
    return None
