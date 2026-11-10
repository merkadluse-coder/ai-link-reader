"""Minimal HTTP API: POST /v1/read_page with `Authorization: Bearer $SOCIAL_READER_API_KEY`.

Refuses to start without an API key; binds to 127.0.0.1 unless told otherwise.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .audit import configure_logging, get_logger
from .config import Settings
from .service import ReaderService

log = get_logger("social_reader.http")
MAX_REQUEST_BYTES = 16 * 1024
_FIELDS = ("url", "output", "include_media", "include_comments", "include_transcript", "language")


def make_handler(service: ReaderService, api_key: str) -> type[BaseHTTPRequestHandler]:
    expected = f"Bearer {api_key}".encode()

    class Handler(BaseHTTPRequestHandler):
        server_version = "social-reader"
        sys_version = ""

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/read_page":
                return self._send(404, {"ok": False, "error_code": "NOT_FOUND"})
            given = self.headers.get("Authorization", "").encode()
            if not hmac.compare_digest(given, expected):
                return self._send(401, {"ok": False, "error_code": "UNAUTHORIZED"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_REQUEST_BYTES:
                return self._send(413, {"ok": False, "error_code": "REQUEST_TOO_LARGE"})
            try:
                body = json.loads(self.rfile.read(length))
                assert isinstance(body, dict) and isinstance(body.get("url"), str)
            except (ValueError, AssertionError):
                return self._send(400, {"ok": False, "error_code": "BAD_REQUEST"})
            args = {k: body[k] for k in _FIELDS if k in body}
            caller = hashlib.sha256(self.client_address[0].encode()).hexdigest()[:12]
            result = service.read_page(**args, caller=caller)
            status = 429 if result.get("error_code") == "RATE_LIMITED" else 200
            self._send(status, result)

        def log_message(self, fmt: str, *args: Any) -> None:
            log.info("http %s", fmt % args)

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    if not settings.api_key:
        raise SystemExit("SOCIAL_READER_API_KEY 未设置：HTTP API 拒绝在无鉴权状态下启动")
    server = ThreadingHTTPServer((host, port), make_handler(ReaderService(settings), settings.api_key))
    log.info("HTTP API listening on %s:%s", host, port)
    server.serve_forever()
