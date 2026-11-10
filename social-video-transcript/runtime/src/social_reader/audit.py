"""Logging with redaction at the source, plus one structured audit line per call."""

from __future__ import annotations

import json
import logging
import sys

from .security import RedactingFilter

_FILTER = RedactingFilter()


def get_logger(name: str) -> logging.Logger:
    """Logger whose records are redacted before ANY handler (or test capture) sees them."""
    logger = logging.getLogger(name)
    if _FILTER not in logger.filters:
        logger.addFilter(_FILTER)
    return logger


def configure_logging(level: str = "INFO") -> None:
    """Send logs to stderr (stdout is reserved for the MCP stdio protocol)."""
    # FastMCP enables the root logger; HTTPX otherwise prints signed playback URLs.
    for name in ("httpx", "httpcore"):
        get_logger(name).setLevel(logging.WARNING)
    root = logging.getLogger("social_reader")
    root.setLevel(level)
    if not any(getattr(h, "_social_reader", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.addFilter(_FILTER)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler._social_reader = True  # type: ignore[attr-defined]
        root.addHandler(handler)


_audit = get_logger("social_reader.audit")


def audit_event(**fields: object) -> None:
    _audit.info(json.dumps(fields, ensure_ascii=False, default=str))
