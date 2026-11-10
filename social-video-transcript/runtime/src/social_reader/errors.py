"""Error codes from docs/IMPLEMENTATION_SPEC.md §3.3.

Every failure path raises ReaderError so callers always get a diagnosable
error instead of an empty "success".
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    INVALID_URL = "INVALID_URL"
    UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"
    FETCH_TIMEOUT = "FETCH_TIMEOUT"
    FETCH_BLOCKED = "FETCH_BLOCKED"
    PARSE_CHANGED = "PARSE_CHANGED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    PREVIEW_ONLY = "PREVIEW_ONLY"
    PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
    CONTENT_NOT_FOUND = "CONTENT_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class RightsState(str, Enum):
    PUBLIC = "public"
    LOGIN_REQUIRED = "login_required"
    PREVIEW_ONLY = "preview_only"
    PERMISSION_REQUIRED = "permission_required"
    BLOCKED = "blocked"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


# Default rights_state and retryability per error code.
_DEFAULTS: dict[ErrorCode, tuple[RightsState, bool]] = {
    ErrorCode.INVALID_URL: (RightsState.UNKNOWN, False),
    ErrorCode.UNSUPPORTED_PLATFORM: (RightsState.UNKNOWN, False),
    ErrorCode.FETCH_TIMEOUT: (RightsState.UNKNOWN, True),
    ErrorCode.FETCH_BLOCKED: (RightsState.BLOCKED, True),
    ErrorCode.PARSE_CHANGED: (RightsState.UNKNOWN, False),
    ErrorCode.LOGIN_REQUIRED: (RightsState.LOGIN_REQUIRED, False),
    ErrorCode.PREVIEW_ONLY: (RightsState.PREVIEW_ONLY, False),
    ErrorCode.PERMISSION_REQUIRED: (RightsState.PERMISSION_REQUIRED, False),
    ErrorCode.CONTENT_NOT_FOUND: (RightsState.NOT_FOUND, False),
    ErrorCode.RATE_LIMITED: (RightsState.UNKNOWN, True),
    ErrorCode.INTERNAL_ERROR: (RightsState.UNKNOWN, True),
}


class ReaderError(Exception):
    """A user-facing failure. `message` must never contain secrets or raw HTML."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        rights_state: RightsState | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        default_rights, default_retry = _DEFAULTS[code]
        self.code = code
        self.message = message
        self.rights_state = rights_state or default_rights
        self.retryable = default_retry if retryable is None else retryable
