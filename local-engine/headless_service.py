from __future__ import annotations

import argparse
import json
import os
import queue
import secrets
import signal
import threading
import time
import uuid
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
MAX_JOBS = 200
TERMINAL_STATES = {"completed", "failed", "cancelled"}


class HeadlessServiceError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_host(value: str) -> str:
    try:
        return str(urlparse(value).hostname or "")[:160]
    except ValueError:
        return ""


def _safe_detail(value: object, limit: int = 1200) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()[:limit]


def _loopback_host(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "::1", "localhost"}


def _download_root(value: object | None = None) -> Path:
    raw = str(value or os.getenv("GALAXY_DOWNLOAD_DIR") or "").strip()
    root = Path(raw).expanduser() if raw else Path.home() / "Downloads" / "Galaxy"
    root = root.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


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
            selected_video_has_audio=not bool(clean_audio),
        )
    if include_audio:
        return "bestvideo+bestaudio/best"
    return "bestvideo/best"


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
            cleaned = [str(item).strip()[:32] for item in languages if str(item).strip()][:16]
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
        "duration": int(float(info.get("duration") or 0)),
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
    file_path: str = ""
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": self.job_id,
            "sourceHost": self.source_host,
            "state": self.state,
            "progress": round(max(0.0, min(float(self.progress), 100.0)), 1),
            "detail": self.detail,
            "filePath": self.file_path,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass(frozen=True)
class _QueuedDownload:
    job_id: str
    source_url: str
    payload: dict[str, Any]


class HeadlessRuntime:
    def __init__(self, download_root: Path, *, max_queue_size: int = MAX_QUEUE_SIZE) -> None:
        self.download_root = Path(download_root).resolve(strict=False)
        self.download_root.mkdir(parents=True, exist_ok=True)
        self._queue: queue.Queue[_QueuedDownload | None] = queue.Queue(
            maxsize=max(1, min(int(max_queue_size), MAX_QUEUE_SIZE))
        )
        self._jobs: dict[str, HeadlessJob] = {}
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._worker = threading.Thread(target=self._run, name="GalaxyHeadlessWorker", daemon=True)
        self._worker.start()

    def _prune(self) -> None:
        if len(self._jobs) <= MAX_JOBS:
            return
        removable = [item for item in self._jobs.values() if item.state in TERMINAL_STATES]
        removable.sort(key=lambda item: item.updated_at)
        for item in removable[: max(0, len(self._jobs) - MAX_JOBS)]:
            self._jobs.pop(item.job_id, None)

    def submit(self, payload: dict[str, Any]) -> HeadlessJob:
        if self._stopping.is_set():
            raise HeadlessServiceError("headless service is shutting down")
        if not isinstance(payload, dict):
            raise HeadlessServiceError("download request must be a JSON object")
        source = validated_public_http_url(str(payload.get("sourceUrl") or ""))
        # Validate exact IDs before a job is accepted so malformed selectors never
        # reach yt-dlp's format expression parser.
        _format_selector(payload)
        job_id = uuid.uuid4().hex
        job = HeadlessJob(job_id=job_id, source_host=_safe_host(source))
        with self._lock:
            self._jobs[job_id] = job
            self._prune()
        try:
            self._queue.put_nowait(_QueuedDownload(job_id, source, dict(payload)))
        except queue.Full as exc:
            with self._lock:
                self._jobs.pop(job_id, None)
            raise HeadlessServiceError("download queue is full") from exc
        return job

    def get(self, job_id: object) -> HeadlessJob | None:
        clean = str(job_id or "").strip().lower()
        if len(clean) != 32 or any(character not in "0123456789abcdef" for character in clean):
            return None
        with self._lock:
            return self._jobs.get(clean)

    def status(self) -> dict[str, Any]:
        with self._lock:
            rows = [item.public_payload() for item in self._jobs.values()]
        active = sum(1 for item in rows if item["state"] == "running")
        queued = sum(1 for item in rows if item["state"] == "queued")
        return {
            "service": "Galaxy Headless API",
            "protocol": 1,
            "active": active,
            "queued": queued,
            "capacity": self._queue.maxsize,
            "downloadRoot": str(self.download_root),
            "jobs": sorted(rows, key=lambda item: item["createdAt"], reverse=True)[:50],
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

    def _execute(self, task: _QueuedDownload) -> None:
        self._update(task.job_id, state="running", detail="downloading", progress=0.0)
        last_path = ""

        def progress_hook(event: dict[str, Any]) -> None:
            nonlocal last_path
            status = str(event.get("status") or "")
            filename = str(event.get("filename") or "")
            if filename:
                try:
                    path = Path(filename).resolve(strict=False)
                    path.relative_to(self.download_root)
                    last_path = str(path)
                except (OSError, ValueError):
                    pass
            total = float(event.get("total_bytes") or event.get("total_bytes_estimate") or 0)
            downloaded = float(event.get("downloaded_bytes") or 0)
            progress = downloaded * 100.0 / total if total > 0 else 0.0
            detail = "merging" if status == "finished" else "downloading"
            self._update(task.job_id, progress=progress, detail=detail)

        try:
            options = _download_options(task.payload, self.download_root, progress_hook)
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(task.source_url, download=True)
                if isinstance(info, dict):
                    try:
                        prepared = ydl.prepare_filename(info)
                        if prepared:
                            path = Path(prepared).resolve(strict=False)
                            path.relative_to(self.download_root)
                            last_path = str(path)
                    except (OSError, ValueError):
                        pass
            self._update(
                task.job_id,
                state="completed",
                progress=100.0,
                detail="completed",
                file_path=last_path,
            )
        except Exception as exc:  # noqa: BLE001
            self._update(task.job_id, state="failed", detail=_safe_detail(exc), file_path="")

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if item is None:
                    return
                self._execute(item)
            finally:
                self._queue.task_done()

    def stop(self) -> None:
        self._stopping.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._worker.is_alive():
            self._worker.join(timeout=3.0)


class HeadlessRequestHandler(BaseHTTPRequestHandler):
    server_version = "GalaxyHeadless/1"

    @property
    def runtime(self) -> HeadlessRuntime:
        return self.server.runtime  # type: ignore[attr-defined]

    @property
    def auth_token(self) -> str:
        return self.server.auth_token  # type: ignore[attr-defined]

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _authorized(self) -> bool:
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

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"ok": True, "service": "Galaxy Headless API", "protocol": 1})
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        if self.path == "/v1/status":
            self._json(200, {"ok": True, **self.runtime.status()})
            return
        if self.path.startswith("/v1/jobs/"):
            job = self.runtime.get(self.path.split("/", 3)[-1])
            if job is None:
                self._json(404, {"ok": False, "error": "job not found"})
            else:
                self._json(200, {"ok": True, "job": job.public_payload()})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            payload = self._read_json()
            if self.path == "/v1/parse":
                result = parse_media(payload.get("sourceUrl"))
                self._json(200, {"ok": True, "result": result})
                return
            if self.path == "/v1/download":
                job = self.runtime.submit(payload)
                self._json(202, {"ok": True, "job": job.public_payload()})
                return
            self._json(404, {"ok": False, "error": "not found"})
        except HeadlessServiceError as exc:
            status = 429 if "queue is full" in str(exc) else 400
            self._json(status, {"ok": False, "error": _safe_detail(exc)})
        except Exception as exc:  # noqa: BLE001
            self._json(502, {"ok": False, "error": _safe_detail(exc)})


class GalaxyHeadlessServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, runtime: HeadlessRuntime, auth_token: str) -> None:
        self.runtime = runtime
        self.auth_token = auth_token
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
        raise HeadlessServiceError(
            "GALAXY_HEADLESS_TOKEN with at least 24 characters is required for non-loopback binding"
        )
    runtime = HeadlessRuntime(download_root or _download_root())
    server = GalaxyHeadlessServer((clean_host, clean_port), runtime, token)
    stopping = threading.Event()

    def stop_handler(_signum, _frame) -> None:
        if stopping.is_set():
            return
        stopping.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    for signal_name in ("SIGINT", "SIGTERM"):
        value = getattr(signal, signal_name, None)
        if value is not None:
            try:
                signal.signal(value, stop_handler)
            except (OSError, RuntimeError, ValueError):
                pass
    try:
        print(f"Galaxy Headless API listening on {clean_host}:{clean_port}", flush=True)
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        runtime.stop()
    return 0


def run_headless_service_self_test() -> None:
    assert _loopback_host("127.0.0.1") is True
    assert _loopback_host("::1") is True
    assert _loopback_host("example.com") is False
    assert _bounded_int("99", 4, 1, 8) == 8
    assert _format_selector({"includeAudio": True}) == "bestvideo+bestaudio/best"
    assert _format_selector({"includeAudio": False}) == "bestvideo/best"
    assert _format_selector(
        {"includeAudio": True, "videoFormatId": "399", "audioFormatId": "251"}
    ) == "399+251"
    try:
        _format_selector({"videoFormatId": "137+251"})
    except Exception:
        pass
    else:
        raise AssertionError("unsafe exact format selector was accepted")


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
