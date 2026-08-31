from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = int(os.getenv("GALAXY_LOCAL_BRIDGE_PORT", "17836"))
BRIDGE_BASE_URL = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"
BRIDGE_PROTOCOL_VERSION = 2
MAX_REQUEST_BYTES = 32 * 1024
LOCAL_PARSE_TIMEOUT_SECONDS = 45

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
        return True
    return origin.rstrip("/") in allowed_origins()


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _yt_dlp_path() -> Path | None:
    app_dir = _app_dir()
    for candidate in (
        app_dir / "yt-dlp.exe",
        app_dir / "bin" / "yt-dlp.exe",
        app_dir / "yt-dlp",
    ):
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _valid_source_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _platform_name(info: dict[str, Any]) -> str:
    raw = f"{info.get('extractor_key') or ''} {info.get('extractor') or ''}".lower()
    mappings = (
        ("instagram", "instagram"),
        ("youtube", "youtube"),
        ("tiktok", "tiktok"),
        ("bilibili", "bilibili"),
        ("twitter", "twitter"),
        ("x.com", "twitter"),
        ("vimeo", "vimeo"),
        ("dailymotion", "dailymotion"),
        ("reddit", "reddit"),
        ("twitch", "twitch"),
        ("soundcloud", "soundcloud"),
        ("pinterest", "pinterest"),
        ("tumblr", "tumblr"),
        ("vk", "vk"),
    )
    for needle, platform in mappings:
        if needle in raw:
            return platform
    fallback = re.sub(r"[^a-z0-9_]+", "_", str(info.get("extractor_key") or info.get("extractor") or "unknown").lower()).strip("_")
    return fallback or "unknown"


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _format_score(item: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        _number(item.get("height")),
        _number(item.get("fps")),
        _number(item.get("tbr")),
        _number(item.get("filesize") or item.get("filesize_approx")),
    )


def _has_video(item: dict[str, Any]) -> bool:
    codec = str(item.get("vcodec") or "none").lower()
    return codec not in {"", "none"}


def _has_audio(item: dict[str, Any]) -> bool:
    codec = str(item.get("acodec") or "none").lower()
    return codec not in {"", "none"}


def _stream_url(item: dict[str, Any] | None) -> str | None:
    if not item:
        return None
    value = item.get("url")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _quality_options(formats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [item for item in formats if _has_video(item) and _stream_url(item)]
    candidates.sort(key=_format_score, reverse=True)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        height = int(_number(item.get("height")))
        format_id = str(item.get("format_id") or "").strip()
        quality = str(height) if height > 0 else format_id or "best"
        key = f"{quality}:{item.get('vcodec')}:{item.get('acodec')}"
        if key in seen:
            continue
        seen.add(key)
        label_parts = [f"{height}p" if height > 0 else (format_id or "Best")]
        fps = _number(item.get("fps"))
        if fps > 30:
            label_parts.append(f"{int(round(fps))}fps")
        ext = str(item.get("ext") or "").strip()
        if ext:
            label_parts.append(ext.upper())
        option: dict[str, Any] = {
            "quality": quality,
            "label": " · ".join(label_parts),
            "downloadUrl": _stream_url(item),
        }
        for source_key, target_key in (
            ("width", "width"),
            ("height", "height"),
            ("fps", "fps"),
            ("filesize", "filesize"),
        ):
            if item.get(source_key) is not None:
                option[target_key] = item.get(source_key)
        for key_name in ("ext", "vcodec", "acodec"):
            if item.get(key_name):
                option[key_name] = item.get(key_name)
        result.append(option)
        if len(result) >= 12:
            break
    return result


def _subtitle_tracks(info: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source_name, auto in (("subtitles", False), ("automatic_captions", True)):
        source = info.get(source_name)
        if not isinstance(source, dict):
            continue
        for language, entries in source.items():
            if not isinstance(entries, list):
                continue
            preferred = next(
                (
                    entry for entry in entries
                    if isinstance(entry, dict)
                    and isinstance(entry.get("url"), str)
                    and entry.get("url")
                    and str(entry.get("ext") or "").lower() in {"srt", "vtt", "ass", "ttml", "srv3"}
                ),
                None,
            )
            if preferred is None:
                preferred = next(
                    (
                        entry for entry in entries
                        if isinstance(entry, dict) and isinstance(entry.get("url"), str) and entry.get("url")
                    ),
                    None,
                )
            if preferred is None:
                continue
            result.append({
                "id": f"{language}:{'auto' if auto else 'manual'}",
                "language": str(language),
                "label": str(language),
                "url": preferred.get("url"),
                "downloadUrl": preferred.get("url"),
                "format": str(preferred.get("ext") or "vtt"),
                "isAutoGenerated": auto,
            })
            if len(result) >= 30:
                return result
    return result


def _normalize_info(raw_info: dict[str, Any]) -> dict[str, Any]:
    entries = raw_info.get("entries")
    if isinstance(entries, list):
        first = next((entry for entry in entries if isinstance(entry, dict)), None)
        if first:
            merged = dict(raw_info)
            merged.update(first)
            return merged
    return raw_info


def parse_with_bundled_ytdlp(source_url: str) -> dict[str, Any]:
    if not _valid_source_url(source_url):
        return {
            "success": False,
            "code": "BAD_REQUEST",
            "status": 400,
            "error": "Invalid media URL",
        }

    executable = _yt_dlp_path()
    if executable is None:
        return {
            "success": False,
            "code": "SERVICE_UNAVAILABLE",
            "status": 503,
            "error": "Bundled yt-dlp.exe is missing",
        }

    command = [
        str(executable),
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        "--socket-timeout", "20",
        "--retries", "2",
        "--extractor-retries", "2",
        "--",
        source_url,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=LOCAL_PARSE_TIMEOUT_SECONDS,
            creationflags=_creation_flags(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "code": "SERVICE_UNAVAILABLE",
            "status": 504,
            "error": "Local parser timed out",
        }
    except OSError as exc:
        return {
            "success": False,
            "code": "SERVICE_UNAVAILABLE",
            "status": 503,
            "error": f"Could not start bundled yt-dlp: {exc}",
        }

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "yt-dlp parse failed").strip()
        return {
            "success": False,
            "code": "PARSE_FAILED",
            "status": 502,
            "error": detail[-1800:],
        }

    try:
        raw_info = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "success": False,
            "code": "PARSE_FAILED",
            "status": 502,
            "error": "Local parser returned invalid JSON",
        }
    if not isinstance(raw_info, dict):
        return {
            "success": False,
            "code": "PARSE_FAILED",
            "status": 502,
            "error": "Local parser returned an unsupported result",
        }

    info = _normalize_info(raw_info)
    formats = [item for item in info.get("formats", []) if isinstance(item, dict)] if isinstance(info.get("formats"), list) else []
    muxed = max((item for item in formats if _has_video(item) and _has_audio(item) and _stream_url(item)), key=_format_score, default=None)
    video_only = max((item for item in formats if _has_video(item) and _stream_url(item)), key=_format_score, default=None)
    audio_only = max((item for item in formats if not _has_video(item) and _has_audio(item) and _stream_url(item)), key=lambda item: (_number(item.get("abr")), _number(item.get("tbr"))), default=None)

    top_url = info.get("url") if isinstance(info.get("url"), str) else None
    selected_video_url = _stream_url(muxed) or _stream_url(video_only) or top_url
    selected_audio_url = _stream_url(audio_only)
    has_video = bool(selected_video_url) or any(_has_video(item) for item in formats)
    has_audio = bool(selected_audio_url) or bool(muxed and _has_audio(muxed)) or any(_has_audio(item) for item in formats)
    mode = "muxed" if muxed or (has_video and has_audio and not selected_audio_url) else "separate" if has_video and has_audio else "pure_music" if has_audio else "not_applicable"

    title = str(info.get("title") or info.get("fulltitle") or info.get("description") or "Untitled media").strip()
    description = str(info.get("description") or "").strip()
    thumbnail = info.get("thumbnail") if isinstance(info.get("thumbnail"), str) else None

    return {
        "success": True,
        "data": {
            "title": title,
            "desc": description,
            "cover": thumbnail,
            "platform": _platform_name(info),
            "downloadAudioUrl": selected_audio_url,
            "downloadVideoUrl": selected_video_url,
            "originDownloadAudioUrl": selected_audio_url,
            "originDownloadVideoUrl": selected_video_url,
            "videoAudioMode": mode,
            "mediaActions": {
                "video": "direct-download" if muxed else "merge-then-download" if has_video else "hide",
                "audio": "direct-download" if selected_audio_url else "extract-audio" if has_audio else "hide",
            },
            "qualityOptions": _quality_options(formats),
            "subtitles": _subtitle_tracks(info),
            "url": source_url,
            "duration": info.get("duration"),
            "kind": "video" if has_video else "audio" if has_audio else "video",
        },
    }


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
            server_version = "GalaxyLocalBridge/2"

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
                if self.path == "/parse":
                    payload = self._read_json()
                    if payload is None:
                        return
                    source_url = str(payload.get("url") or "").strip()
                    result = parse_with_bundled_ytdlp(source_url)
                    self._json(int(result.get("status") or (200 if result.get("success") else 502)), result)
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
