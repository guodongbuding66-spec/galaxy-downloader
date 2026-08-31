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
BRIDGE_PROTOCOL_VERSION = 3
MAX_REQUEST_BYTES = 32 * 1024
LOCAL_PARSE_TIMEOUT_SECONDS = 45
SUPPORTED_BROWSERS = {"none", "edge", "chrome", "firefox", "brave", "chromium", "opera", "vivaldi"}

AUTH_REQUIRED_PATTERNS = (
    "use --cookies-from-browser",
    "use --cookies",
    "login required",
    "log in",
    "logged-in",
    "authentication",
    "empty media response",
    "not accessible",
    "sign in",
)
COOKIE_ACCESS_PATTERNS = (
    "could not copy chrome cookie database",
    "could not copy edge cookie database",
    "could not copy firefox cookie database",
    "cookie database is locked",
    "database is locked",
    "failed to decrypt with dpapi",
    "failed to decrypt cookie",
    "could not find chrome cookies database",
    "could not find edge cookies database",
    "could not find firefox cookies database",
)

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


def _validated_browser(value: object) -> str:
    browser = str(value or "none").strip().lower()
    return browser if browser in SUPPORTED_BROWSERS else "none"


def _auth_required(detail: str) -> bool:
    lowered = detail.lower()
    return any(pattern in lowered for pattern in AUTH_REQUIRED_PATTERNS)


def _cookie_access_error(detail: str) -> bool:
    lowered = detail.lower()
    return any(pattern in lowered for pattern in COOKIE_ACCESS_PATTERNS)


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
    fallback = re.sub(
        r"[^a-z0-9_]+",
        "_",
        str(info.get("extractor_key") or info.get("extractor") or "unknown").lower(),
    ).strip("_")
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
                    entry
                    for entry in entries
                    if isinstance(entry, dict)
                    and isinstance(entry.get("url"), str)
                    and entry.get("url")
                    and str(entry.get("ext") or "").lower()
                    in {"srt", "vtt", "ass", "ttml", "srv3"}
                ),
                None,
            )
            if preferred is None:
                preferred = next(
                    (
                        entry
                        for entry in entries
                        if isinstance(entry, dict)
                        and isinstance(entry.get("url"), str)
                        and entry.get("url")
                    ),
                    None,
                )
            if preferred is None:
                continue
            result.append(
                {
                    "id": f"{language}:{'auto' if auto else 'manual'}",
                    "language": str(language),
                    "label": str(language),
                    "url": preferred.get("url"),
                    "downloadUrl": preferred.get("url"),
                    "format": str(preferred.get("ext") or "vtt"),
                    "isAutoGenerated": auto,
                }
            )
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


def _run_parse(executable: Path, source_url: str, browser: str = "none") -> subprocess.CompletedProcess[str] | dict[str, Any]:
    command = [
        str(executable),
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        "--socket-timeout",
        "20",
        "--retries",
        "2",
        "--extractor-retries",
        "2",
    ]
    if browser != "none":
        command.extend(["--cookies-from-browser", browser])
    command.extend(["--", source_url])

    try:
        return subprocess.run(
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
            "error": "本地解析超时，请稍后重试。",
        }
    except OSError as exc:
        return {
            "success": False,
            "code": "SERVICE_UNAVAILABLE",
            "status": 503,
            "error": f"无法启动内置 yt-dlp：{exc}",
        }


def _completed_error(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stderr or completed.stdout or "yt-dlp parse failed").strip()


def _success_payload(completed: subprocess.CompletedProcess[str], source_url: str, browser_used: str) -> dict[str, Any]:
    try:
        raw_info = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "success": False,
            "code": "PARSE_FAILED",
            "status": 502,
            "error": "本地解析器返回了无效数据。",
        }
    if not isinstance(raw_info, dict):
        return {
            "success": False,
            "code": "PARSE_FAILED",
            "status": 502,
            "error": "本地解析器返回了不支持的数据格式。",
        }

    info = _normalize_info(raw_info)
    formats = (
        [item for item in info.get("formats", []) if isinstance(item, dict)]
        if isinstance(info.get("formats"), list)
        else []
    )
    muxed = max(
        (
            item
            for item in formats
            if _has_video(item) and _has_audio(item) and _stream_url(item)
        ),
        key=_format_score,
        default=None,
    )
    video_only = max(
        (item for item in formats if _has_video(item) and _stream_url(item)),
        key=_format_score,
        default=None,
    )
    audio_only = max(
        (
            item
            for item in formats
            if not _has_video(item) and _has_audio(item) and _stream_url(item)
        ),
        key=lambda item: (_number(item.get("abr")), _number(item.get("tbr"))),
        default=None,
    )

    top_url = info.get("url") if isinstance(info.get("url"), str) else None
    selected_video_url = _stream_url(muxed) or _stream_url(video_only) or top_url
    selected_audio_url = _stream_url(audio_only)
    has_video = bool(selected_video_url) or any(_has_video(item) for item in formats)
    has_audio = (
        bool(selected_audio_url)
        or bool(muxed and _has_audio(muxed))
        or any(_has_audio(item) for item in formats)
    )
    mode = (
        "muxed"
        if muxed or (has_video and has_audio and not selected_audio_url)
        else "separate"
        if has_video and has_audio
        else "pure_music"
        if has_audio
        else "not_applicable"
    )

    title = str(
        info.get("title")
        or info.get("fulltitle")
        or info.get("description")
        or "Untitled media"
    ).strip()
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
                "video": "direct-download"
                if muxed
                else "merge-then-download"
                if has_video
                else "hide",
                "audio": "direct-download"
                if selected_audio_url
                else "extract-audio"
                if has_audio
                else "hide",
            },
            "qualityOptions": _quality_options(formats),
            "subtitles": _subtitle_tracks(info),
            "url": source_url,
            "duration": info.get("duration"),
            "kind": "video" if has_video else "audio" if has_audio else "video",
            "localAuthBrowser": None if browser_used == "none" else browser_used,
        },
    }


def parse_with_bundled_ytdlp(source_url: str, browser: str = "none") -> dict[str, Any]:
    if not _valid_source_url(source_url):
        return {
            "success": False,
            "code": "BAD_REQUEST",
            "status": 400,
            "error": "无效的媒体链接。",
        }

    executable = _yt_dlp_path()
    if executable is None:
        return {
            "success": False,
            "code": "SERVICE_UNAVAILABLE",
            "status": 503,
            "error": "安装包中的 yt-dlp.exe 缺失，请重新下载完整安装包。",
        }

    requested_browser = _validated_browser(browser)

    # Public media should never require browser cookies. Try the clean path
    # first so an open Chromium browser cannot break ordinary parsing.
    public_attempt = _run_parse(executable, source_url, "none")
    if isinstance(public_attempt, dict):
        return public_attempt
    if public_attempt.returncode == 0:
        return _success_payload(public_attempt, source_url, "none")

    public_error = _completed_error(public_attempt)
    if not _auth_required(public_error):
        return {
            "success": False,
            "code": "PARSE_FAILED",
            "status": 502,
            "error": public_error[-1800:],
        }

    if requested_browser == "none":
        return {
            "success": False,
            "code": "AUTH_REQUIRED",
            "status": 401,
            "error": "该内容需要登录状态才能解析。请在浏览器中登录对应平台后重新解析。",
            "details": {"raw": public_error[-1200:]},
        }

    # The website passes the browser it is currently running in. Retry with
    # that browser only after yt-dlp has confirmed that authentication is needed.
    browser_attempt = _run_parse(executable, source_url, requested_browser)
    if isinstance(browser_attempt, dict):
        return browser_attempt
    if browser_attempt.returncode == 0:
        return _success_payload(browser_attempt, source_url, requested_browser)

    browser_error = _completed_error(browser_attempt)
    if _cookie_access_error(browser_error):
        return {
            "success": False,
            "code": "BROWSER_COOKIE_UNAVAILABLE",
            "status": 409,
            "error": (
                f"Instagram 需要登录状态，但当前无法读取 {requested_browser.title()} 的 Cookie。"
                "如果浏览器正在占用 Cookie 数据库，请完全退出该浏览器后重试；"
                "也可以改用另一个已经登录 Instagram 的浏览器。"
            ),
            "details": {"browser": requested_browser, "raw": browser_error[-1200:]},
        }

    if _auth_required(browser_error):
        return {
            "success": False,
            "code": "AUTH_REQUIRED",
            "status": 401,
            "error": (
                f"已尝试读取 {requested_browser.title()} 登录状态，但 Instagram 仍拒绝返回媒体。"
                "请确认该浏览器已经登录 Instagram，并且此 Reel 在该账号中可以正常播放。"
            ),
            "details": {"browser": requested_browser, "raw": browser_error[-1200:]},
        }

    return {
        "success": False,
        "code": "PARSE_FAILED",
        "status": 502,
        "error": browser_error[-1800:],
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
            server_version = "GalaxyLocalBridge/3"

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
                self._json(
                    200,
                    {
                        "ok": True,
                        "bridgeProtocol": BRIDGE_PROTOCOL_VERSION,
                        **payload,
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
                if self.path == "/parse":
                    payload = self._read_json()
                    if payload is None:
                        return
                    source_url = str(payload.get("url") or "").strip()
                    browser = _validated_browser(payload.get("browser"))
                    result = parse_with_bundled_ytdlp(source_url, browser)
                    self._json(
                        int(result.get("status") or (200 if result.get("success") else 502)),
                        result,
                    )
                    return
                if self.path == "/download":
                    payload = self._read_json()
                    if payload is None:
                        return
                    accepted, message = bridge._submit_job(payload)
                    self._json(
                        202 if accepted else 409,
                        {
                            "ok": accepted,
                            "accepted": accepted,
                            "message": message,
                        },
                    )
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
