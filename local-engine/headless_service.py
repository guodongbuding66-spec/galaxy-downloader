from __future__ import annotations

import argparse
import json
import math
import os
import queue
import re
import secrets
import signal
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from media_format_catalog import (
    build_media_format_catalog,
    exact_format_selector,
    public_media_format_catalog,
    validate_format_id,
)
from url_policy import validated_public_http_url
from yt_dlp import YoutubeDL

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17837
MAX_REQUEST_BYTES = 64 * 1024
MAX_QUEUE_SIZE = 25
MAX_JOBS = 500
MAX_EVENT_SUBSCRIBERS = 32
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class HeadlessServiceError(RuntimeError):
    pass


class HeadlessConflict(HeadlessServiceError):
    pass


class HeadlessCancelled(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_host(value: str) -> str:
    try:
        return str(urlparse(value).hostname or "")[:160]
    except ValueError:
        return ""


def _safe_detail(value: object, limit: int = 1200) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    text = re.sub(r"(?i)(authorization|api[-_ ]?key|token|secret)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)
    return text[:limit]


def _loopback_host(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "::1", "localhost"}


def _download_root(value: object | None = None) -> Path:
    raw = str(value or os.getenv("GALAXY_DOWNLOAD_DIR") or "").strip()
    root = Path(raw).expanduser() if raw else Path.home() / "Downloads" / "Galaxy"
    if root.exists() and root.is_symlink():
        raise HeadlessServiceError("download root cannot be a symbolic link")
    root = root.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def _bounded_float(value: object, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(low, min(parsed, high))


def _set_event() -> threading.Event:
    event = threading.Event()
    event.set()
    return event


def _format_selector(payload: dict[str, Any]) -> str:
    include_audio = bool(payload.get("includeAudio", True))
    video_id = payload.get("videoFormatId")
    audio_id = payload.get("audioFormatId")
    if video_id or audio_id:
        clean_video = validate_format_id(video_id) if video_id else None
        clean_audio = validate_format_id(audio_id) if audio_id else None
        return exact_format_selector(
            video_format_id=clean_video,
            audio_format_id=clean_audio,
            include_audio=include_audio,
            selected_video_has_audio=bool(payload.get("selectedVideoHasAudio", not bool(clean_audio))),
        )
    return "bestvideo+bestaudio/best" if include_audio else "bestvideo/best"


def _download_options(payload: dict[str, Any], root: Path, progress_hook) -> dict[str, Any]:
    options: dict[str, Any] = {
        "ignoreconfig": True,
        "quiet": True,
        "no_warnings": True,
        "continuedl": True,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": _bounded_int(payload.get("concurrentFragments"), 4, 1, 8),
        "format": _format_selector(payload),
        "paths": {"home": str(root)},
        "outtmpl": {"default": "%(title).180B [%(id)s].%(ext)s"},
        "progress_hooks": [progress_hook],
        "noplaylist": str(payload.get("collectionMode") or "single") == "single",
    }
    if bool(payload.get("includeSubtitle", False)):
        options["writesubtitles"] = True
        options["writeautomaticsub"] = True
        options["subtitlesformat"] = "srt/best"
        languages = payload.get("subtitleLanguages")
        if isinstance(languages, list):
            cleaned: list[str] = []
            for item in languages:
                language = str(item or "").strip()[:32]
                if language and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", language) and language not in cleaned:
                    cleaned.append(language)
                if len(cleaned) >= 16:
                    break
            if cleaned:
                options["subtitleslangs"] = cleaned
    if bool(payload.get("includeCover", False)):
        options["writethumbnail"] = True
    rate_mbps = _bounded_int(payload.get("rateLimitMbps"), 0, 0, 10_000)
    if rate_mbps:
        options["ratelimit"] = rate_mbps * 1024 * 1024
    return options


def parse_media(source_url: object) -> dict[str, Any]:
    url = validated_public_http_url(str(source_url or ""))
    options = {
        "ignoreconfig": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 2,
        "extractor_retries": 2,
        "playlistend": 50,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        raise HeadlessServiceError("parser did not return media metadata")
    formats = info.get("formats") if isinstance(info.get("formats"), list) else []
    catalog = public_media_format_catalog(build_media_format_catalog(formats))
    return {
        "success": True,
        "title": str(info.get("title") or info.get("fulltitle") or "")[:300],
        "platform": str(info.get("extractor_key") or info.get("extractor") or "")[:100],
        "durationSeconds": _bounded_int(info.get("duration"), 0, 0, 365 * 24 * 3600),
        "thumbnail": str(info.get("thumbnail") or "")[:2000],
        "formatCatalog": catalog,
    }


@dataclass
class HeadlessJob:
    job_id: str
    source_host: str
    state: str = "queued"
    progress: float = 0.0
    detail: str = ""
    file_name: str = ""
    attempt: int = 1
    generation: int = 1
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    resume_event: threading.Event = field(default_factory=_set_event, repr=False)

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": self.job_id,
            "sourceHost": self.source_host,
            "state": self.state,
            "progress": round(max(0.0, min(float(self.progress), 100.0)), 1),
            "detail": self.detail,
            "fileName": self.file_name,
            "attempt": max(1, int(self.attempt)),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass(frozen=True)
class _DownloadSpec:
    source_url: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class _QueuedDownload:
    job_id: str
    generation: int


class EventBroker:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, queue.Queue[dict[str, Any]]] = {}

    def subscribe(self) -> tuple[str, queue.Queue[dict[str, Any]]]:
        with self._lock:
            if len(self._subscribers) >= MAX_EVENT_SUBSCRIBERS:
                raise HeadlessServiceError("too many event subscribers")
            subscriber_id = uuid.uuid4().hex
            channel: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
            self._subscribers[subscriber_id] = channel
            return subscriber_id, channel

    def unsubscribe(self, subscriber_id: str) -> None:
        with self._lock:
            self._subscribers.pop(subscriber_id, None)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            channels = list(self._subscribers.values())
        for channel in channels:
            try:
                channel.put_nowait(dict(event))
            except queue.Full:
                with suppress(queue.Empty):
                    channel.get_nowait()
                with suppress(queue.Full):
                    channel.put_nowait(dict(event))


class HeadlessRuntime:
    def __init__(self, download_root: Path, *, max_queue_size: int = MAX_QUEUE_SIZE) -> None:
        self.download_root = Path(download_root).resolve(strict=False)
        self.download_root.mkdir(parents=True, exist_ok=True)
        self._capacity = max(1, min(int(max_queue_size), MAX_QUEUE_SIZE))
        self._queue: queue.Queue[_QueuedDownload | None] = queue.Queue(maxsize=self._capacity * 4)
        self._jobs: dict[str, HeadlessJob] = {}
        self._specs: dict[str, _DownloadSpec] = {}
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._active_job: tuple[str, int] | None = None
        self.events = EventBroker()
        self._worker = threading.Thread(target=self._run, name="GalaxyHeadlessWorker", daemon=True)
        self._worker.start()

    def _logical_queued_locked(self) -> int:
        return sum(1 for item in self._jobs.values() if item.state == "queued")

    def _prune_locked(self) -> None:
        if len(self._jobs) <= MAX_JOBS:
            return
        removable = [item for item in self._jobs.values() if item.state in TERMINAL_STATES]
        removable.sort(key=lambda item: item.updated_at)
        for item in removable[: max(0, len(self._jobs) - MAX_JOBS)]:
            self._jobs.pop(item.job_id, None)
            self._specs.pop(item.job_id, None)

    def _put_token_locked(self, job: HeadlessJob) -> None:
        if self._queue.full():
            raise HeadlessServiceError("download queue is temporarily full")
        self._queue.put_nowait(_QueuedDownload(job.job_id, job.generation))

    def _touch_locked(
        self,
        job: HeadlessJob,
        *,
        state: str | None = None,
        detail: str | None = None,
    ) -> dict[str, Any]:
        if state is not None:
            job.state = state
        if detail is not None:
            job.detail = detail
        job.updated_at = _utc_now()
        return job.public_payload()

    def submit(self, payload: dict[str, Any]) -> HeadlessJob:
        if self._stopping.is_set():
            raise HeadlessServiceError("headless service is shutting down")
        if not isinstance(payload, dict):
            raise HeadlessServiceError("download request must be a JSON object")
        source = validated_public_http_url(str(payload.get("sourceUrl") or ""))
        _format_selector(payload)
        job_id = uuid.uuid4().hex
        job = HeadlessJob(job_id=job_id, source_host=_safe_host(source))
        with self._lock:
            if self._logical_queued_locked() >= self._capacity:
                raise HeadlessServiceError("download queue is full")
            self._jobs[job_id] = job
            self._specs[job_id] = _DownloadSpec(source, dict(payload))
            try:
                self._put_token_locked(job)
            except Exception:
                self._jobs.pop(job_id, None)
                self._specs.pop(job_id, None)
                raise
            self._prune_locked()
            snapshot = job.public_payload()
        self.events.publish({"event": "job.queued", "job": snapshot})
        return job

    def get(self, job_id: object) -> HeadlessJob | None:
        clean = str(job_id or "").strip().lower()
        if not _JOB_ID_RE.fullmatch(clean):
            return None
        with self._lock:
            return self._jobs.get(clean)

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        with self._lock:
            rows = [item.public_payload() for item in self._jobs.values()]
        rows.sort(key=lambda item: item["createdAt"], reverse=True)
        return rows[:safe_limit]

    def pause(self, job_id: object) -> HeadlessJob:
        job = self.get(job_id)
        if job is None:
            raise HeadlessServiceError("job not found")
        with self._lock:
            if job.state in {"paused", "pausing"}:
                snapshot = job.public_payload()
            elif job.state == "queued":
                job.generation += 1
                job.resume_event.clear()
                snapshot = self._touch_locked(job, state="paused", detail="paused")
            elif job.state == "running":
                job.resume_event.clear()
                snapshot = self._touch_locked(job, state="pausing", detail="pausing")
            else:
                raise HeadlessConflict(f"job cannot be paused from state {job.state}")
        self.events.publish({"event": "job.pause-requested", "job": snapshot})
        return job

    def resume(self, job_id: object) -> HeadlessJob:
        job = self.get(job_id)
        if job is None:
            raise HeadlessServiceError("job not found")
        with self._lock:
            if job.state not in {"paused", "pausing"}:
                raise HeadlessConflict(f"job cannot be resumed from state {job.state}")
            active = self._active_job == (job.job_id, job.generation)
            if active:
                job.resume_event.set()
                snapshot = self._touch_locked(job, state="running", detail="downloading")
            else:
                if self._logical_queued_locked() >= self._capacity:
                    raise HeadlessServiceError("download queue is full")
                if self._queue.full():
                    raise HeadlessServiceError("download queue is temporarily full")
                job.resume_event.set()
                snapshot = self._touch_locked(job, state="queued", detail="queued")
                self._put_token_locked(job)
        self.events.publish({"event": "job.resumed", "job": snapshot})
        return job

    def cancel(self, job_id: object) -> HeadlessJob:
        job = self.get(job_id)
        if job is None:
            raise HeadlessServiceError("job not found")
        with self._lock:
            if job.state in TERMINAL_STATES:
                return job
            active = self._active_job == (job.job_id, job.generation)
            job.cancel_event.set()
            job.resume_event.set()
            if active:
                snapshot = self._touch_locked(job, state="cancelling", detail="cancelling")
            else:
                job.generation += 1
                snapshot = self._touch_locked(job, state="cancelled", detail="cancelled")
        self.events.publish({"event": "job.cancel-requested", "job": snapshot})
        return job

    def retry(self, job_id: object) -> HeadlessJob:
        job = self.get(job_id)
        if job is None:
            raise HeadlessServiceError("job not found")
        with self._lock:
            if job.state not in {"failed", "cancelled"}:
                raise HeadlessConflict(f"job cannot be retried from state {job.state}")
            if job.job_id not in self._specs:
                raise HeadlessServiceError("job retry metadata is unavailable")
            if self._logical_queued_locked() >= self._capacity:
                raise HeadlessServiceError("download queue is full")
            if self._queue.full():
                raise HeadlessServiceError("download queue is temporarily full")
            job.generation += 1
            job.attempt = min(job.attempt + 1, 1_000_000)
            job.progress = 0.0
            job.file_name = ""
            job.cancel_event = threading.Event()
            job.resume_event = _set_event()
            snapshot = self._touch_locked(job, state="queued", detail="queued")
            self._put_token_locked(job)
        self.events.publish({"event": "job.retried", "job": snapshot})
        return job

    def status(self) -> dict[str, Any]:
        rows = self.list_jobs(limit=50)
        with self._lock:
            active = 1 if self._active_job is not None else 0
        queued = sum(1 for item in rows if item["state"] == "queued")
        paused = sum(1 for item in rows if item["state"] in {"paused", "pausing"})
        return {
            "service": "Galaxy Headless API",
            "protocol": 2,
            "active": active,
            "queued": queued,
            "paused": paused,
            "capacity": self._capacity,
            "jobs": rows,
        }

    def _update(self, job_id: str, **changes: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in changes.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = _utc_now()
            snapshot = job.public_payload()
        self.events.publish({"event": "job.updated", "job": snapshot})

    def _wait_if_paused(self, job_id: str, generation: int) -> bool:
        while not self._stopping.is_set():
            transition: dict[str, Any] | None = None
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job.generation != generation:
                    return False
                if job.cancel_event.is_set():
                    raise HeadlessCancelled("download cancelled")
                if job.resume_event.is_set():
                    return True
                if job.state != "paused":
                    transition = self._touch_locked(job, state="paused", detail="paused")
                resume_event = job.resume_event
            if transition is not None:
                self.events.publish({"event": "job.paused", "job": transition})
            resume_event.wait(timeout=0.2)
        raise HeadlessCancelled("headless service is shutting down")

    def _execute(self, task: _QueuedDownload) -> None:
        with self._lock:
            job = self._jobs.get(task.job_id)
            spec = self._specs.get(task.job_id)
            if job is None or spec is None or job.generation != task.generation:
                return
            if job.cancel_event.is_set() or job.state == "cancelled":
                return
        if not self._wait_if_paused(task.job_id, task.generation):
            return
        self._update(task.job_id, state="running", detail="downloading")
        last_name = ""

        def progress_hook(event: dict[str, Any]) -> None:
            nonlocal last_name
            if not self._wait_if_paused(task.job_id, task.generation):
                raise HeadlessCancelled("download superseded")
            current = self.get(task.job_id)
            if current is None or current.cancel_event.is_set():
                raise HeadlessCancelled("download cancelled")
            status = str(event.get("status") or "")
            filename = str(event.get("filename") or "")
            if filename:
                with suppress(OSError, RuntimeError, ValueError):
                    path = Path(filename).resolve(strict=False)
                    path.relative_to(self.download_root)
                    last_name = path.name[:240]
            total = _bounded_float(
                event.get("total_bytes") or event.get("total_bytes_estimate"),
                0.0,
                0.0,
                10**15,
            )
            downloaded = _bounded_float(event.get("downloaded_bytes"), 0.0, 0.0, 10**15)
            progress = downloaded * 100.0 / total if total > 0 else 0.0
            detail = "merging" if status == "finished" else "downloading"
            self._update(task.job_id, progress=progress, detail=detail, file_name=last_name)

        try:
            options = _download_options(spec.payload, self.download_root, progress_hook)
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(spec.source_url, download=True)
                if isinstance(info, dict):
                    with suppress(OSError, RuntimeError, ValueError):
                        prepared = ydl.prepare_filename(info)
                        if prepared:
                            path = Path(prepared).resolve(strict=False)
                            path.relative_to(self.download_root)
                            last_name = path.name[:240]
            if not self._wait_if_paused(task.job_id, task.generation):
                return
            current = self.get(task.job_id)
            if current is not None and current.cancel_event.is_set():
                self._update(task.job_id, state="cancelled", detail="cancelled", file_name="")
            else:
                self._update(
                    task.job_id,
                    state="completed",
                    progress=100.0,
                    detail="completed",
                    file_name=last_name,
                )
        except HeadlessCancelled:
            current = self.get(task.job_id)
            if current is not None and current.generation == task.generation:
                self._update(task.job_id, state="cancelled", detail="cancelled", file_name="")
        except Exception as exc:
            current = self.get(task.job_id)
            if current is not None and current.generation == task.generation:
                if current.cancel_event.is_set():
                    self._update(task.job_id, state="cancelled", detail="cancelled", file_name="")
                else:
                    self._update(task.job_id, state="failed", detail=_safe_detail(exc), file_name="")

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if item is None:
                    return
                with self._lock:
                    job = self._jobs.get(item.job_id)
                    if job is None or job.generation != item.generation or job.state != "queued":
                        continue
                    self._active_job = (item.job_id, item.generation)
                try:
                    self._execute(item)
                finally:
                    with self._lock:
                        if self._active_job == (item.job_id, item.generation):
                            self._active_job = None
            finally:
                self._queue.task_done()

    def stop(self) -> None:
        self._stopping.set()
        with self._lock:
            if self._active_job is not None:
                job = self._jobs.get(self._active_job[0])
                if job is not None:
                    job.cancel_event.set()
                    job.resume_event.set()
        with suppress(queue.Full):
            self._queue.put_nowait(None)
        if self._worker.is_alive():
            self._worker.join(timeout=3.0)


def _job_action_id(path: str, action: str) -> str | None:
    prefix = "/v1/jobs/"
    suffix = f"/{action}"
    if not path.startswith(prefix) or not path.endswith(suffix):
        return None
    job_id = path[len(prefix) : -len(suffix)].strip("/")
    return job_id or None


class HeadlessRequestHandler(BaseHTTPRequestHandler):
    server_version = "GalaxyHeadless/2"

    @property
    def runtime(self) -> HeadlessRuntime:
        return self.server.runtime  # type: ignore[attr-defined]

    @property
    def auth_token(self) -> str:
        return self.server.auth_token  # type: ignore[attr-defined]

    @property
    def bound_host(self) -> str:
        return self.server.bound_host  # type: ignore[attr-defined]

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _browser_origin_allowed(self) -> bool:
        origin = str(self.headers.get("Origin") or "").strip()
        return not origin

    def _valid_host_header(self) -> bool:
        raw = str(self.headers.get("Host") or "").strip()
        if not raw:
            return False
        candidate = raw
        if candidate.startswith("[") and "]" in candidate:
            candidate = candidate[1 : candidate.index("]")]
        elif ":" in candidate:
            candidate = candidate.rsplit(":", 1)[0]
        candidate = candidate.strip().lower()
        if _loopback_host(self.bound_host):
            return _loopback_host(candidate)
        return candidate == self.bound_host.lower() or _loopback_host(candidate)

    def _authorized(self) -> bool:
        if not self._valid_host_header() or not self._browser_origin_allowed():
            return False
        if not self.auth_token:
            return True
        header = str(self.headers.get("Authorization") or "")
        if not header.startswith("Bearer "):
            return False
        return secrets.compare_digest(header[7:].strip(), self.auth_token)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise HeadlessServiceError("invalid Content-Length") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise HeadlessServiceError("request body is empty or too large")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise HeadlessServiceError("request body is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise HeadlessServiceError("request JSON must be an object")
        return payload

    def _sse(self) -> None:
        try:
            subscriber_id, channel = self.runtime.events.subscribe()
        except HeadlessServiceError as exc:
            self._json(429, {"ok": False, "error": str(exc)})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        deadline = time.monotonic() + 60
        try:
            initial = json.dumps(
                {"event": "status", "status": self.runtime.status()},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            self.wfile.write(f"data:{initial}\n\n".encode("utf-8"))
            self.wfile.flush()
            while time.monotonic() < deadline:
                try:
                    event = channel.get(timeout=10)
                    encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(f"data:{encoded}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b":keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            self.runtime.events.unsubscribe(subscriber_id)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in {"/health", "/v1/health"}:
            self._json(200, {"ok": True, "service": "Galaxy Headless API", "protocol": 2})
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        if path == "/v1/status":
            self._json(200, {"ok": True, **self.runtime.status()})
            return
        if path == "/v1/jobs":
            self._json(200, {"ok": True, "jobs": self.runtime.list_jobs()})
            return
        if path == "/v1/events":
            self._sse()
            return
        if path.startswith("/v1/jobs/"):
            job = self.runtime.get(path.split("/", 3)[-1])
            if job is None:
                self._json(404, {"ok": False, "error": "job not found"})
            else:
                self._json(200, {"ok": True, "job": job.public_payload()})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            for action in ("cancel", "pause", "resume", "retry"):
                job_id = _job_action_id(path, action)
                if job_id is None:
                    continue
                if action == "cancel":
                    job = self.runtime.cancel(job_id)
                    status = 200
                elif action == "pause":
                    job = self.runtime.pause(job_id)
                    status = 200
                elif action == "resume":
                    job = self.runtime.resume(job_id)
                    status = 200
                else:
                    job = self.runtime.retry(job_id)
                    status = 202
                self._json(status, {"ok": True, "job": job.public_payload()})
                return

            payload = self._read_json()
            if path == "/v1/parse":
                result = parse_media(payload.get("sourceUrl"))
                self._json(200, {"ok": True, "result": result})
                return
            if path == "/v1/download":
                job = self.runtime.submit(payload)
                self._json(202, {"ok": True, "job": job.public_payload()})
                return
            self._json(404, {"ok": False, "error": "not found"})
        except HeadlessConflict as exc:
            self._json(409, {"ok": False, "error": _safe_detail(exc)})
        except HeadlessServiceError as exc:
            detail = _safe_detail(exc)
            status = 404 if detail == "job not found" else 429 if "queue" in detail and "full" in detail else 400
            self._json(status, {"ok": False, "error": detail})
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})


class GalaxyHeadlessServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, runtime: HeadlessRuntime, auth_token: str, bound_host: str) -> None:
        self.runtime = runtime
        self.auth_token = auth_token
        self.bound_host = bound_host
        super().__init__(address, HeadlessRequestHandler)


def run_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    download_root: Path | None = None,
    auth_token: str = "",
) -> int:
    clean_host = str(host or DEFAULT_HOST).strip()
    clean_port = _bounded_int(port, DEFAULT_PORT, 1, 65535)
    token = str(auth_token or "").strip()
    if not _loopback_host(clean_host) and len(token) < 24:
        raise HeadlessServiceError("a bearer token with at least 24 characters is required for non-loopback binding")
    runtime = HeadlessRuntime(download_root or _download_root())
    server = GalaxyHeadlessServer((clean_host, clean_port), runtime, token, clean_host)
    stopping = threading.Event()

    def stop_handler(_signum, _frame) -> None:
        if stopping.is_set():
            return
        stopping.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    for signal_name in ("SIGINT", "SIGTERM"):
        value = getattr(signal, signal_name, None)
        if value is not None:
            with suppress(OSError, RuntimeError, ValueError):
                signal.signal(value, stop_handler)
    try:
        print(f"Galaxy Headless API listening on {clean_host}:{clean_port}", flush=True)
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        runtime.stop()
    return 0


def run_headless_service_self_test() -> None:
    from unittest.mock import patch

    assert _loopback_host("127.0.0.1") is True
    assert _loopback_host("::1") is True
    assert _loopback_host("example.com") is False
    assert _bounded_int("99", 4, 1, 8) == 8
    assert _format_selector({"includeAudio": True}) == "bestvideo+bestaudio/best"
    assert _format_selector({"includeAudio": False}) == "bestvideo/best"
    assert _format_selector(
        {"includeAudio": True, "videoFormatId": "399", "audioFormatId": "251", "selectedVideoHasAudio": False}
    ) == "399+251"
    unsafe_rejected = False
    try:
        _format_selector({"videoFormatId": "137+251"})
    except Exception:
        unsafe_rejected = True
    assert unsafe_rejected, "unsafe exact format selector was accepted"
    assert _job_action_id("/v1/jobs/" + "a" * 32 + "/pause", "pause") == "a" * 32

    with patch("headless_service.validated_public_http_url", side_effect=str):
        class FakeYdl:
            def __init__(self, _options) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def extract_info(self, _url, download=False):
                assert download is False
                return {"title": "Demo", "duration": 10, "formats": []}

        with patch("headless_service.YoutubeDL", FakeYdl):
            parsed = parse_media("https://example.com/video")
            assert parsed["title"] == "Demo" and parsed["durationSeconds"] == 10

    runtime = HeadlessRuntime(Path.cwd(), max_queue_size=1)
    try:
        with patch("headless_service.validated_public_http_url", side_effect=str):
            job = runtime.submit({"sourceUrl": "https://example.com/video"})
            cancelled = runtime.cancel(job.job_id)
            assert cancelled.state in {"cancelled", "cancelling"}
            assert runtime.get("../bad") is None
    finally:
        runtime.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="galaxy-headless", description="Galaxy Local Engine headless API")
    parser.add_argument("--host", default=os.getenv("GALAXY_HEADLESS_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("GALAXY_HEADLESS_PORT", str(DEFAULT_PORT))))
    parser.add_argument("--download-dir", default=os.getenv("GALAXY_DOWNLOAD_DIR", ""))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        run_headless_service_self_test()
        print("Headless service self-test passed")
        return 0
    token = os.getenv("GALAXY_HEADLESS_TOKEN", "")
    root = _download_root(args.download_dir)
    return run_server(host=args.host, port=args.port, download_root=root, auth_token=token)


if __name__ == "__main__":
    raise SystemExit(main())
