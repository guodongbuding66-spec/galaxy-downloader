from __future__ import annotations

import hmac
import io
import mimetypes
import secrets
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import qrcode

from transfer_center import P2P_DEFAULT_TTL_SECONDS, TransferError, _clean_shared_file, _is_lan_address, _lan_bind_address

QR_MAX_TTL_SECONDS = 60 * 60
QR_TOKEN_BYTES = 24


class _QrHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], session: "QRTransferSession") -> None:
        self.session = session
        super().__init__(address, _QrTransferHandler)


class _QrTransferHandler(BaseHTTPRequestHandler):
    server: _QrHttpServer
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _authorized_path(self) -> bool:
        path = urlsplit(self.path).path
        expected = f"/download/{self.server.session.token}"
        return hmac.compare_digest(path, expected)

    def _peer_is_lan(self) -> bool:
        try:
            return _is_lan_address(str(self.client_address[0]))
        except (IndexError, TypeError):
            return False

    def _send_error(self, status: int, message: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(message)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(message)

    def _serve(self, *, body: bool) -> None:
        session = self.server.session
        if not self._peer_is_lan():
            self._send_error(403, b"LAN access only")
            return
        if session.expired:
            self._send_error(410, b"Transfer expired")
            return
        if session.served:
            self._send_error(410, b"Transfer already used")
            return
        if not self._authorized_path():
            self._send_error(404, b"Not found")
            return

        source = session.source
        try:
            size = source.stat().st_size
        except OSError:
            self._send_error(410, b"File unavailable")
            return
        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        safe_name = quote(source.name, safe="")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{safe_name}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        self.end_headers()
        if not body:
            return

        completed = False
        try:
            with source.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        completed = True
                        break
                    self.wfile.write(chunk)
        except (OSError, BrokenPipeError, ConnectionResetError):
            completed = False
        if completed:
            session._mark_served()

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(body=False)

    def do_GET(self) -> None:  # noqa: N802
        self._serve(body=True)

    def do_POST(self) -> None:  # noqa: N802
        self._send_error(405, b"Method not allowed")


class QRTransferSession:
    """One-use direct LAN HTTP transfer represented by a QR code.

    The URL contains a high-entropy ephemeral token and is bound to a private/local
    interface. No relay, cloud storage, directory listing, upload endpoint or file
    path is exposed to the receiving browser.
    """

    def __init__(self, source_file: Path, *, ttl_seconds: int = P2P_DEFAULT_TTL_SECONDS) -> None:
        self.source = _clean_shared_file(source_file)
        try:
            self.ttl_seconds = max(60, min(int(ttl_seconds), QR_MAX_TTL_SECONDS))
        except (TypeError, ValueError):
            self.ttl_seconds = P2P_DEFAULT_TTL_SECONDS
        self.token = secrets.token_urlsafe(QR_TOKEN_BYTES)
        self.bind_address = ""
        self.port = 0
        self._started_at = 0.0
        self._served = threading.Event()
        self._stopped = threading.Event()
        self._server: _QrHttpServer | None = None
        self._thread: threading.Thread | None = None
        self._expiry_thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        return bool(
            self._thread
            and self._thread.is_alive()
            and not self._stopped.is_set()
            and not self.served
            and not self.expired
        )

    @property
    def served(self) -> bool:
        return self._served.is_set()

    @property
    def expired(self) -> bool:
        return bool(self._started_at and time.monotonic() - self._started_at >= self.ttl_seconds)

    @property
    def url(self) -> str:
        if not self.bind_address or not self.port:
            return ""
        return f"http://{self.bind_address}:{self.port}/download/{self.token}"

    def start(self) -> "QRTransferSession":
        if self._thread is not None:
            return self
        address = _lan_bind_address()
        if not _is_lan_address(address):
            raise TransferError("未找到可用的局域网地址")
        server = _QrHttpServer((address, 0), self)
        self.bind_address = str(server.server_address[0])
        self.port = int(server.server_address[1])
        self._server = server
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=server.serve_forever, name="galaxy-qr-transfer", daemon=True)
        self._thread.start()
        self._expiry_thread = threading.Thread(target=self._expire_after_ttl, name="galaxy-qr-expiry", daemon=True)
        self._expiry_thread.start()
        return self

    def _expire_after_ttl(self) -> None:
        if not self._stopped.wait(self.ttl_seconds):
            self.stop()

    def _mark_served(self) -> None:
        if self._served.is_set():
            return
        self._served.set()
        threading.Thread(target=self.stop, name="galaxy-qr-stop", daemon=True).start()

    def stop(self) -> None:
        if self._stopped.is_set():
            return
        self._stopped.set()
        server = self._server
        if server is not None:
            with suppress(OSError):
                server.shutdown()
            with suppress(OSError):
                server.server_close()

    def qr_png_bytes(self, *, box_size: int = 8, border: int = 4) -> bytes:
        if not self.url:
            raise TransferError("QR Transfer 尚未启动")
        try:
            normalized_box = max(4, min(int(box_size), 16))
            normalized_border = max(2, min(int(border), 8))
        except (TypeError, ValueError) as exc:
            raise TransferError("QR 参数无效") from exc
        image = qrcode.make(self.url, box_size=normalized_box, border=normalized_border)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def public_payload(self) -> dict[str, Any]:
        try:
            size = int(self.source.stat().st_size)
        except OSError:
            size = 0
        remaining = max(0, self.ttl_seconds - int(max(0.0, time.monotonic() - self._started_at))) if self._started_at else self.ttl_seconds
        return {
            "url": self.url,
            "fileName": self.source.name,
            "sizeBytes": size,
            "ttlSeconds": remaining,
            "served": self.served,
            "active": self.active,
        }


def run_qr_transfer_self_test() -> None:
    assert QR_TOKEN_BYTES >= 16
    assert QR_MAX_TTL_SECONDS <= 3600
