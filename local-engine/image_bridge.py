from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from bridge import allowed_origins
from image_download import image_job_status, start_image_download_job

IMAGE_BRIDGE_HOST = "127.0.0.1"
IMAGE_BRIDGE_PORT = int(os.getenv("GALAXY_LOCAL_IMAGE_BRIDGE_PORT", "17837"))
MAX_REQUEST_BYTES = 1024 * 1024


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    return origin.rstrip("/") in allowed_origins()


class ImageBridge:
    def __init__(self, version: str) -> None:
        self.version = version
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self._server is not None:
            return True
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "GalaxyImageBridge/1"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _origin(self) -> str | None:
                return self.headers.get("Origin")

            def _cors(self) -> None:
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
                self._cors()
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
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self._reject_origin():
                    return
                if self.path != "/status":
                    self._json(404, {"ok": False, "error": "Not found"})
                    return
                self._json(
                    200,
                    {
                        "ok": True,
                        "version": bridge.version,
                        "imageDownloads": True,
                        **image_job_status(),
                    },
                )

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
                if self.path != "/download-images":
                    self._json(404, {"ok": False, "error": "Not found"})
                    return
                payload = self._read_json()
                if payload is None:
                    return
                accepted, message = start_image_download_job(payload)
                self._json(
                    202 if accepted else 409,
                    {
                        "ok": accepted,
                        "accepted": accepted,
                        "message": message,
                    },
                )

        try:
            self._server = ThreadingHTTPServer((IMAGE_BRIDGE_HOST, IMAGE_BRIDGE_PORT), Handler)
        except OSError:
            self._server = None
            return False
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="GalaxyImageBridge",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.shutdown()
            server.server_close()
        self._thread = None
