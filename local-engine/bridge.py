from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = int(os.getenv("GALAXY_LOCAL_BRIDGE_PORT", "17836"))
BRIDGE_BASE_URL = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"
BRIDGE_PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 32 * 1024

_DEFAULT_ALLOWED_ORIGINS = {
    "https://galaxy-downloader.guodongbuding66.workers.dev",
    "https://galaxy-downloader.pages.dev",
    "http://localhost:3010",
    "http://127.0.0.1:3010",
}


def allowed_origins() -> set[str]:
    configured = {
        item.strip().rstrip("/")
        for item in os.getenv("GALAXY_ALLOWED_WEB_ORIGINS", "").split(",")
        if item.strip()
    }
    return _DEFAULT_ALLOWED_ORIGINS | configured


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        # Native processes and command-line health checks do not send Origin.
        return True
    return origin.rstrip("/") in allowed_origins()


class LocalBridge:
    def __init__(
        self,
        *,
        status_provider: Callable[[], dict[str, Any]],
        submit_job: Callable[[dict[str, Any]], tuple[bool, str]],
        cancel_job: Callable[[], None],
        open_folder: Callable[[], None],
    ) -> None:
        self._status_provider = status_provider
        self._submit_job = submit_job
        self._cancel_job = cancel_job
        self._open_folder = open_folder
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return

        bridge = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "GalaxyLocalBridge/1"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _origin(self) -> str | None:
                return self.headers.get("Origin")

            def _write_cors_headers(self) -> None:
                origin = self._origin()
                if origin and _origin_allowed(origin):
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Cache-Control", "no-store")

            def _json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self._write_cors_headers()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _reject_origin(self) -> bool:
                if _origin_allowed(self._origin()):
                    return False
                self._json(403, {"ok": False, "error": "Origin is not allowed"})
                return True

            def do_OPTIONS(self) -> None:  # noqa: N802
                if self._reject_origin():
                    return
                self.send_response(204)
                self._write_cors_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self._reject_origin():
                    return
                if self.path not in {"/health", "/status"}:
                    self._json(404, {"ok": False, "error": "Not found"})
                    return
                payload = bridge._status_provider()
                self._json(200, {
                    "ok": True,
                    "bridgeProtocol": BRIDGE_PROTOCOL_VERSION,
                    **payload,
                })

            def _read_json(self) -> dict[str, Any] | None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    self._json(400, {"ok": False, "error": "Invalid request body"})
                    return None
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._json(400, {"ok": False, "error": "Invalid JSON"})
                    return None
                if not isinstance(payload, dict):
                    self._json(400, {"ok": False, "error": "JSON object required"})
                    return None
                return payload

            def do_POST(self) -> None:  # noqa: N802
                if self._reject_origin():
                    return
                if self.path == "/download":
                    payload = self._read_json()
                    if payload is None:
                        return
                    accepted, message = bridge._submit_job(payload)
                    self._json(202 if accepted else 409, {
                        "ok": accepted,
                        "accepted": accepted,
                        "message": message,
                    })
                    return
                if self.path == "/cancel":
                    bridge._cancel_job()
                    self._json(200, {"ok": True})
                    return
                if self.path == "/open-folder":
                    bridge._open_folder()
                    self._json(200, {"ok": True})
                    return
                self._json(404, {"ok": False, "error": "Not found"})

        self._server = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="GalaxyLocalBridge",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.shutdown()
            server.server_close()
        self._thread = None


def bridge_is_running(timeout: float = 0.45) -> bool:
    request = urllib.request.Request(f"{BRIDGE_BASE_URL}/health", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def post_job_to_running_engine(payload: dict[str, Any], timeout: float = 0.8) -> bool:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BRIDGE_BASE_URL}/download",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
