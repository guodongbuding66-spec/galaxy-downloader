from __future__ import annotations

import mimetypes
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

from media_library import resolve_media_item_path

_PLAYBACK_TTL_SECONDS = 300
_MAX_ACTIVE_TICKETS = 1024
_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_TICKET_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_PLAYABLE_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mkv",
        ".webm",
        ".mov",
        ".m4v",
        ".avi",
        ".ts",
        ".mp3",
        ".m4a",
        ".aac",
        ".flac",
        ".wav",
        ".ogg",
        ".opus",
    }
)


class LearningPlaybackError(RuntimeError):
    def __init__(self, status: int, message: str, code: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class _PlaybackTicket:
    media_id: str
    expires_at: float


class PlaybackTicketRegistry:
    """Process-local, media-scoped tickets for native browser Range requests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tickets: dict[str, _PlaybackTicket] = {}

    def _prune_locked(self, now: float) -> None:
        expired = [token for token, entry in self._tickets.items() if entry.expires_at <= now]
        for token in expired:
            self._tickets.pop(token, None)
        if len(self._tickets) < _MAX_ACTIVE_TICKETS:
            return
        oldest = sorted(self._tickets.items(), key=lambda pair: pair[1].expires_at)
        for token, _entry in oldest[: max(1, len(self._tickets) - _MAX_ACTIVE_TICKETS + 1)]:
            self._tickets.pop(token, None)

    def issue(self, media_id: str, *, now: float | None = None) -> tuple[str, int]:
        current = time.monotonic() if now is None else float(now)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_locked(current)
            self._tickets[token] = _PlaybackTicket(media_id=media_id, expires_at=current + _PLAYBACK_TTL_SECONDS)
        return token, _PLAYBACK_TTL_SECONDS

    def valid(self, token: object, media_id: str, *, now: float | None = None) -> bool:
        candidate = str(token or "").strip()
        if not _TICKET_RE.fullmatch(candidate):
            return False
        current = time.monotonic() if now is None else float(now)
        with self._lock:
            self._prune_locked(current)
            entry = self._tickets.get(candidate)
            return bool(entry and entry.media_id == media_id and entry.expires_at > current)

    def clear(self) -> None:
        with self._lock:
            self._tickets.clear()


_PLAYBACK_TICKETS = PlaybackTicketRegistry()


def _clean_media_id(value: object) -> str:
    media_id = str(value or "").strip().lower()
    if not _MEDIA_ID_RE.fullmatch(media_id):
        raise LearningPlaybackError(400, "invalid media id", "LEARNING_INVALID_MEDIA_ID")
    return media_id


def _playable_source(learning_api, media_id: object) -> tuple[str, Path]:
    clean = _clean_media_id(media_id)
    source = resolve_media_item_path(learning_api.context, clean)
    if source is None:
        raise LearningPlaybackError(404, "media item not found", "LEARNING_MEDIA_NOT_FOUND")
    if source.suffix.lower() not in _PLAYABLE_EXTENSIONS:
        raise LearningPlaybackError(415, "media item is not playable", "LEARNING_MEDIA_NOT_PLAYABLE")
    return clean, source


def _parse_single_range(value: object, size: int) -> tuple[int, int] | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if not raw.startswith("bytes=") or "," in raw or size <= 0:
        raise ValueError("invalid range")
    spec = raw[6:].strip()
    if "-" not in spec:
        raise ValueError("invalid range")
    start_raw, end_raw = spec.split("-", 1)
    if not start_raw:
        try:
            suffix = int(end_raw)
        except ValueError as exc:
            raise ValueError("invalid range") from exc
        if suffix <= 0:
            raise ValueError("invalid range")
        start = max(0, size - suffix)
        return start, size - 1
    try:
        start = int(start_raw)
    except ValueError as exc:
        raise ValueError("invalid range") from exc
    if start < 0 or start >= size:
        raise ValueError("invalid range")
    if not end_raw:
        return start, size - 1
    try:
        end = int(end_raw)
    except ValueError as exc:
        raise ValueError("invalid range") from exc
    if end < start:
        raise ValueError("invalid range")
    return start, min(end, size - 1)


def _copy_bytes(source: BinaryIO, target, count: int) -> None:
    remaining = max(0, int(count))
    while remaining:
        chunk = source.read(min(1024 * 1024, remaining))
        if not chunk:
            break
        target.write(chunk)
        remaining -= len(chunk)


class HeadlessLearningMediaHttpMixin:
    """Issue bounded playback tickets and stream trusted local course media."""

    def _playback_error(self, exc: LearningPlaybackError) -> None:
        self._json(exc.status, {"ok": False, "error": str(exc), "code": exc.code})

    def _stream_learning_media(self, media_id: str, ticket: str) -> None:
        if not self._valid_host_header() or not self._browser_origin_allowed():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        learning_api = getattr(self, "learning_api", None)
        if learning_api is None:
            self._json(503, {"ok": False, "error": "learning api is unavailable"})
            return
        try:
            clean = _clean_media_id(media_id)
        except LearningPlaybackError as exc:
            self._playback_error(exc)
            return
        if not _PLAYBACK_TICKETS.valid(ticket, clean):
            self._json(401, {"ok": False, "error": "invalid or expired playback ticket"})
            return
        try:
            _clean, source = _playable_source(learning_api, clean)
        except LearningPlaybackError as exc:
            self._playback_error(exc)
            return
        try:
            size = source.stat().st_size
            range_header = self.headers.get("Range")
            byte_range = _parse_single_range(range_header, size)
        except (OSError, ValueError):
            try:
                size = max(0, source.stat().st_size)
            except OSError:
                size = 0
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            return

        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        if byte_range is None:
            start, end, status = 0, max(0, size - 1), 200
            length = size
        else:
            start, end = byte_range
            status = 206
            length = end - start + 1

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with source.open("rb") as handle:
                if start:
                    handle.seek(start)
                _copy_bytes(handle, self.wfile, length)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_GET(self) -> None:  # noqa: N802
        parts = [part for part in urlsplit(self.path).path.split("/") if part]
        if len(parts) == 5 and parts[:3] == ["v1", "learning", "playback"]:
            ticket, media_id = parts[3], parts[4]
            self._stream_learning_media(media_id, ticket)
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        parts = [part for part in path.split("/") if part]
        if not (len(parts) == 5 and parts[:3] == ["v1", "learning", "media"] and parts[4] == "playback-ticket"):
            super().do_POST()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        learning_api = getattr(self, "learning_api", None)
        if learning_api is None:
            self._json(503, {"ok": False, "error": "learning api is unavailable"})
            return
        try:
            media_id, _source = _playable_source(learning_api, parts[3])
            ticket, ttl = _PLAYBACK_TICKETS.issue(media_id)
        except LearningPlaybackError as exc:
            self._playback_error(exc)
            return
        self._json(
            200,
            {
                "ok": True,
                "playback": {
                    "mediaId": media_id,
                    "url": f"/v1/learning/playback/{ticket}/{media_id}",
                    "expiresInSeconds": ttl,
                },
            },
        )
