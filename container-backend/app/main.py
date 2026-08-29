from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

APP_VERSION = "0.4.0"
PARSE_TIMEOUT_SECONDS = int(os.getenv("PARSE_TIMEOUT_SECONDS", "90"))
PARSE_ATTEMPTS = max(1, int(os.getenv("PARSE_ATTEMPTS", "2")))
PARSE_RETRY_DELAY_SECONDS = max(0.0, float(os.getenv("PARSE_RETRY_DELAY_SECONDS", "0.75")))
DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "1800"))
MAX_SOURCE_URL_LENGTH = 4096
PARSE_CONCURRENCY = int(os.getenv("PARSE_CONCURRENCY", "4"))
DOWNLOAD_CONCURRENCY = int(os.getenv("DOWNLOAD_CONCURRENCY", "2"))
PARSE_QUEUE_TIMEOUT_SECONDS = max(0.1, float(os.getenv("PARSE_QUEUE_TIMEOUT_SECONDS", "15")))
DOWNLOAD_QUEUE_TIMEOUT_SECONDS = max(0.1, float(os.getenv("DOWNLOAD_QUEUE_TIMEOUT_SECONDS", "30")))
MAX_DOWNLOAD_BYTES = max(1, int(os.getenv("MAX_DOWNLOAD_BYTES", str(6 * 1024 * 1024 * 1024))))
DOWNLOAD_DISK_HEADROOM_BYTES = max(0, int(os.getenv("DOWNLOAD_DISK_HEADROOM_BYTES", str(512 * 1024 * 1024))))
MIN_DOWNLOAD_CAPACITY_BYTES = max(1, int(os.getenv("MIN_DOWNLOAD_CAPACITY_BYTES", str(64 * 1024 * 1024))))

parse_slots = asyncio.Semaphore(PARSE_CONCURRENCY)
download_slots = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)

allowed_origins = [
    item.strip()
    for item in os.getenv(
        "ALLOWED_ORIGINS",
        "https://galaxy-downloader.guodongbuding66.workers.dev,http://localhost:3010,http://127.0.0.1:3010",
    ).split(",")
    if item.strip()
]

app = FastAPI(title="Galaxy Downloader Media Backend", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "Content-Range", "Content-Disposition", "Accept-Ranges", "Retry-After", "X-Request-Id"],
)

COOKIE_PATH = Path("/tmp/galaxy-cookies.txt")
AUDIO_EXTENSIONS = {"aac", "flac", "m4a", "m4b", "mp3", "oga", "ogg", "opus", "wav", "weba"}
NON_RETRYABLE_PARSE_MARKERS = (
    "sign in to confirm you’re not a bot",
    "sign in to confirm you're not a bot",
    "no video formats found",
    "unsupported url",
    "private video",
    "login required",
    "this video is unavailable",
    "http error 401",
    "http error 403",
)


def materialize_cookies() -> str | None:
    encoded = os.getenv("YTDLP_COOKIES_B64", "").strip()
    if not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise RuntimeError("YTDLP_COOKIES_B64 is not valid base64") from exc
    if len(decoded) > 2 * 1024 * 1024:
        raise RuntimeError("Cookie file is unexpectedly large")
    COOKIE_PATH.write_bytes(decoded)
    COOKIE_PATH.chmod(0o600)
    return str(COOKIE_PATH)


COOKIE_FILE = materialize_cookies()


PLATFORM_ALIASES: list[tuple[tuple[str, ...], str]] = [
    (("bilibili",), "bilibili"),
    (("douyin",), "douyin"),
    (("youtube",), "youtube"),
    (("telegram",), "telegram"),
    (("threads",), "threads"),
    (("wechat", "weixin"), "wechat"),
    (("niconico", "nicovideo"), "niconico"),
    (("weibo",), "weibo"),
    (("xiaohongshu", "xhs"), "xiaohongshu"),
    (("tiktok",), "tiktok"),
    (("instagram",), "instagram"),
    (("twitter",), "x"),
    (("vimeo",), "vimeo"),
    (("dailymotion",), "dailymotion"),
    (("streamable",), "streamable"),
    (("reddit",), "reddit"),
    (("tumblr",), "tumblr"),
    (("pinterest",), "pinterest"),
    (("vkontakte", "vk"), "vk"),
    (("odnoklassniki", "okru"), "okru"),
    (("twitch",), "twitch"),
    (("soundcloud",), "soundcloud"),
    (("applepodcast",), "applePodcasts"),
    (("kuaishou",), "kuaishou"),
    (("zhihu",), "zhihu"),
    (("bluesky",), "bluesky"),
    (("rumble",), "rumble"),
    (("snapchat",), "snapchat"),
    (("coub",), "coub"),
    (("imgur",), "imgur"),
    (("lbry", "odysee"), "odysee"),
    (("rutube",), "rutube"),
]


def platform_id(info: dict[str, Any]) -> str:
    raw = " ".join(
        str(info.get(key) or "")
        for key in ("extractor_key", "extractor", "webpage_url_domain")
    ).lower()
    compact = re.sub(r"[^a-z0-9]+", "", raw)
    for aliases, value in PLATFORM_ALIASES:
        if any(re.sub(r"[^a-z0-9]+", "", alias.lower()) in compact for alias in aliases):
            return value
    return "generic"


def codec_present(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value.lower() != "none"


def format_has_video(fmt: dict[str, Any]) -> bool:
    vcodec = fmt.get("vcodec")
    if isinstance(vcodec, str):
        return vcodec.lower() != "none"
    if int(fmt.get("height") or 0) > 0 or int(fmt.get("width") or 0) > 0:
        return str(fmt.get("ext") or "").lower() not in AUDIO_EXTENSIONS
    return False


def format_has_audio(fmt: dict[str, Any]) -> bool:
    acodec = fmt.get("acodec")
    if isinstance(acodec, str):
        return acodec.lower() != "none"
    if fmt.get("audio_channels") or float(fmt.get("abr") or 0) > 0:
        return True
    return not format_has_video(fmt) and str(fmt.get("ext") or "").lower() in AUDIO_EXTENSIONS


def public_base(request: Request) -> str:
    forwarded = request.headers.get("x-public-base-url", "").strip()
    if forwarded.startswith(("https://", "http://")):
        return forwarded.rstrip("/")
    return str(request.base_url).rstrip("/")


def build_download_url(base: str, source_url: str, media_type: str, quality: str = "best", format_id: str | None = None) -> str:
    query: dict[str, str] = {
        "url": source_url,
        "type": media_type,
        "quality": quality,
    }
    if format_id:
        query["formatId"] = format_id
    return f"{base}/api/download?{urllib.parse.urlencode(query)}"


def common_yt_dlp_args() -> list[str]:
    args = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "--js-runtimes",
        "node",
        "--impersonate",
        os.getenv("YTDLP_IMPERSONATE", "chrome"),
        "--socket-timeout",
        os.getenv("YTDLP_SOCKET_TIMEOUT", "30"),
        "--extractor-retries",
        os.getenv("YTDLP_EXTRACTOR_RETRIES", "3"),
        "--retries",
        os.getenv("YTDLP_RETRIES", "3"),
        "--fragment-retries",
        os.getenv("YTDLP_FRAGMENT_RETRIES", "3"),
        "--concurrent-fragments",
        os.getenv("YTDLP_CONCURRENT_FRAGMENTS", "4"),
    ]
    if COOKIE_FILE:
        args.extend(["--cookies", COOKIE_FILE])
    proxy = os.getenv("YTDLP_PROXY", "").strip()
    if proxy:
        args.extend(["--proxy", proxy])
    user_agent = os.getenv("YTDLP_USER_AGENT", "").strip()
    if user_agent:
        args.extend(["--user-agent", user_agent])
    return args


def _is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_global


def validate_public_source_url(source_url: str) -> str:
    value = source_url.strip()
    if not value or len(value) > MAX_SOURCE_URL_LENGTH:
        raise HTTPException(status_code=400, detail="Invalid source URL")
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid source URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Only public HTTP(S) URLs are allowed")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Credentials in source URLs are not allowed")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="Private hosts are not allowed")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise HTTPException(status_code=400, detail="Private IP addresses are not allowed")
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="Source host cannot be resolved") from exc
    resolved = {item[4][0] for item in addresses if item and item[4]}
    if not resolved or any(not _is_public_ip(address) for address in resolved):
        raise HTTPException(status_code=400, detail="Source host resolves to a private or reserved address")
    return value


def run_process(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def parse_error_message(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stderr or completed.stdout or "yt-dlp failed")[-4000:].strip()


def parse_error_is_retryable(message: str) -> bool:
    normalized = message.lower()
    return not any(marker in normalized for marker in NON_RETRYABLE_PARSE_MARKERS)


def parse_with_ytdlp(source_url: str) -> dict[str, Any]:
    command = common_yt_dlp_args() + [
        "--dump-single-json",
        "--skip-download",
        source_url,
    ]
    last_message = "yt-dlp failed"
    timed_out = False

    for attempt in range(1, PARSE_ATTEMPTS + 1):
        try:
            completed = run_process(command, PARSE_TIMEOUT_SECONDS)
            timed_out = False
        except subprocess.TimeoutExpired:
            completed = None
            timed_out = True
            last_message = "Parser timed out"

        if completed is not None and completed.returncode == 0:
            try:
                payload = json.loads(completed.stdout)
            except json.JSONDecodeError:
                last_message = "Parser returned invalid JSON"
            else:
                if not isinstance(payload, dict):
                    last_message = "Parser returned an invalid result"
                else:
                    if payload.get("_type") == "playlist":
                        entries = [entry for entry in payload.get("entries") or [] if isinstance(entry, dict)]
                        if not entries:
                            raise HTTPException(status_code=404, detail="No downloadable media was found")
                        payload = entries[0]
                    return payload
        elif completed is not None:
            last_message = parse_error_message(completed)
            if not parse_error_is_retryable(last_message):
                break

        if attempt < PARSE_ATTEMPTS and PARSE_RETRY_DELAY_SECONDS > 0:
            time.sleep(PARSE_RETRY_DELAY_SECONDS * attempt)

    if timed_out:
        raise HTTPException(status_code=504, detail=last_message)
    raise HTTPException(status_code=502, detail=last_message)


def best_format_groups(info: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    formats = [fmt for fmt in info.get("formats") or [] if isinstance(fmt, dict) and isinstance(fmt.get("url"), str)]
    videos = [fmt for fmt in formats if format_has_video(fmt)]
    audios = [fmt for fmt in formats if format_has_audio(fmt)]
    has_muxed = any(format_has_video(fmt) and format_has_audio(fmt) for fmt in formats)
    return videos, audios, has_muxed


def quality_options(info: dict[str, Any], source_url: str, base: str) -> list[dict[str, Any]]:
    videos, _, _ = best_format_groups(info)
    best_by_height: dict[int, dict[str, Any]] = {}
    for fmt in videos:
        height = int(fmt.get("height") or 0)
        if height <= 0:
            continue
        current = best_by_height.get(height)
        score = (float(fmt.get("fps") or 0), float(fmt.get("tbr") or 0), int(fmt.get("filesize") or fmt.get("filesize_approx") or 0))
        current_score = (
            float(current.get("fps") or 0),
            float(current.get("tbr") or 0),
            int(current.get("filesize") or current.get("filesize_approx") or 0),
        ) if current else (-1.0, -1.0, -1)
        if current is None or score > current_score:
            best_by_height[height] = fmt

    output: list[dict[str, Any]] = [
        {
            "quality": "best",
            "label": "Best available",
            "downloadUrl": build_download_url(base, source_url, "video", "best"),
        }
    ]
    for height, fmt in sorted(best_by_height.items(), reverse=True):
        format_id = str(fmt.get("format_id") or "") or None
        label_parts = [f"{height}p"]
        fps = float(fmt.get("fps") or 0)
        if fps > 30:
            label_parts.append(f"{round(fps)}fps")
        if fmt.get("ext"):
            label_parts.append(str(fmt["ext"]).upper())
        output.append({
            "quality": str(height),
            "label": " · ".join(label_parts),
            "width": fmt.get("width"),
            "height": height,
            "fps": fmt.get("fps"),
            "ext": fmt.get("ext"),
            "vcodec": fmt.get("vcodec"),
            "acodec": fmt.get("acodec"),
            "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
            "downloadUrl": build_download_url(base, source_url, "video", str(height), format_id),
        })
    return output


def subtitle_tracks(info: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for key, generated in (("subtitles", False), ("automatic_captions", True)):
        group = info.get(key)
        if not isinstance(group, dict):
            continue
        for language, items in group.items():
            if not isinstance(items, list):
                continue
            preferred = None
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                    continue
                if preferred is None or str(item.get("ext") or "") in {"vtt", "srt"}:
                    preferred = item
                    if str(item.get("ext") or "") in {"vtt", "srt"}:
                        break
            if not preferred:
                continue
            url = preferred["url"]
            marker = (str(language), url)
            if marker in seen:
                continue
            seen.add(marker)
            output.append({
                "id": f"{language}:{'auto' if generated else 'manual'}",
                "language": str(language),
                "label": preferred.get("name") or str(language),
                "url": url,
                "downloadUrl": url,
                "format": preferred.get("ext") or "vtt",
                "isAutoGenerated": generated,
            })
    return output


def normalize_parse_result(info: dict[str, Any], source_url: str, base: str) -> dict[str, Any]:
    videos, audios, has_muxed = best_format_groups(info)
    has_video = bool(videos)
    has_audio = bool(audios)
    has_video_only = any(format_has_video(fmt) and not format_has_audio(fmt) for fmt in videos)
    has_audio_only = any(format_has_audio(fmt) and not format_has_video(fmt) for fmt in audios)

    if not has_video and has_audio:
        mode = "pure_music"
        kind = "audio"
    elif has_video_only and has_audio_only:
        mode = "separate"
        kind = "video"
    elif has_video and (has_muxed or has_audio):
        mode = "muxed"
        kind = "video"
    else:
        mode = "not_applicable"
        kind = "video" if has_video else "picker"

    video_url = build_download_url(base, source_url, "video", "best") if has_video else None
    audio_url = build_download_url(base, source_url, "audio", "best") if has_audio else None
    return {
        "title": str(info.get("title") or info.get("fulltitle") or "Untitled media"),
        "desc": info.get("description") or "",
        "cover": info.get("thumbnail"),
        "platform": platform_id(info),
        "downloadAudioUrl": audio_url,
        "downloadVideoUrl": video_url,
        "originDownloadAudioUrl": None,
        "originDownloadVideoUrl": None,
        "videoAudioMode": mode,
        "mediaActions": {
            "video": "direct-download" if has_video else "hide",
            "audio": "direct-download" if has_audio else "hide",
        },
        "qualityOptions": quality_options(info, source_url, base) if has_video else [],
        "subtitles": subtitle_tracks(info),
        "url": source_url,
        "duration": info.get("duration"),
        "kind": kind,
        "maxDownloadBytes": MAX_DOWNLOAD_BYTES,
    }


def select_format(media_type: str, quality: str, format_id: str | None) -> str:
    if media_type == "audio":
        return "ba/b"
    if format_id:
        safe_id = re.sub(r"[^A-Za-z0-9_.:-]", "", format_id).strip(".")
        if safe_id:
            return f"{safe_id}+ba/{safe_id}/b"
    height_match = re.fullmatch(r"(\d{3,4})(?:p)?", quality.strip().lower())
    if height_match:
        height = int(height_match.group(1))
        return f"bv*[height<={height}]+ba/b[height<={height}]/b"
    return "bv*+ba/b"


def find_downloaded_file(directory: Path) -> Path:
    candidates = [path for path in directory.glob("media.*") if path.is_file() and not path.name.endswith((".part", ".ytdl"))]
    if not candidates:
        candidates = [path for path in directory.iterdir() if path.is_file() and not path.name.endswith((".part", ".ytdl"))]
    if not candidates:
        raise HTTPException(status_code=502, detail="Downloader completed without producing a file")
    return max(candidates, key=lambda path: path.stat().st_size)


def available_download_limit(directory: Path) -> int:
    free_bytes = shutil.disk_usage(directory).free
    safe_free_bytes = max(0, free_bytes - DOWNLOAD_DISK_HEADROOM_BYTES)
    effective_limit = min(MAX_DOWNLOAD_BYTES, safe_free_bytes)
    if effective_limit < MIN_DOWNLOAD_CAPACITY_BYTES:
        raise HTTPException(status_code=507, detail="Not enough temporary storage capacity for a media download")
    return effective_limit


def download_with_ytdlp(source_url: str, media_type: str, quality: str, format_id: str | None, output_dir: Path) -> Path:
    selector = select_format(media_type, quality, format_id)
    effective_limit = available_download_limit(output_dir)
    command = common_yt_dlp_args() + [
        "--quiet",
        "--no-progress",
        "--max-filesize",
        str(effective_limit),
        "--format",
        selector,
        "--output",
        str(output_dir / "media.%(ext)s"),
    ]
    if media_type == "video":
        command.extend(["--merge-output-format", "mp4"])
    command.append(source_url)

    try:
        completed = run_process(command, DOWNLOAD_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Download timed out") from exc

    diagnostic = (completed.stderr or completed.stdout or "")[-4000:].strip()
    if completed.returncode != 0:
        normalized = diagnostic.lower()
        if "max-filesize" in normalized or "larger than max" in normalized or "exceeds" in normalized and "size" in normalized:
            raise HTTPException(status_code=413, detail=f"Media exceeds the {effective_limit} byte download limit")
        raise HTTPException(status_code=502, detail=diagnostic or "yt-dlp download failed")

    try:
        file_path = find_downloaded_file(output_dir)
    except HTTPException:
        normalized = diagnostic.lower()
        if "max-filesize" in normalized or "larger than max" in normalized:
            raise HTTPException(status_code=413, detail=f"Media exceeds the {effective_limit} byte download limit")
        raise

    output_bytes = file_path.stat().st_size
    if output_bytes > effective_limit:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail=f"Media exceeds the {effective_limit} byte download limit")
    return file_path


def safe_download_name(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "-", path.stem).strip(" .-") or "media"
    return f"{stem[:120]}{path.suffix.lower()}"


async def acquire_capacity(slot: asyncio.Semaphore, timeout_seconds: float) -> bool:
    try:
        await asyncio.wait_for(slot.acquire(), timeout=timeout_seconds)
        return True
    except TimeoutError:
        return False


def public_error_message(exc: HTTPException, operation: str) -> str:
    if exc.status_code >= 500 and exc.status_code not in {504, 507}:
        return f"Media provider {operation} failed upstream."
    return str(exc.detail)


def api_error_response(
    code: str,
    status: int,
    message: str,
    request_id: str,
    retry_after: int | None = None,
) -> JSONResponse:
    headers = {
        "X-Request-Id": request_id,
        "Cache-Control": "no-store",
    }
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        {
            "success": False,
            "code": code,
            "status": status,
            "error": message,
            "requestId": request_id,
        },
        status_code=status,
        headers=headers,
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    disk_free_bytes = shutil.disk_usage("/tmp").free
    return {
        "ok": True,
        "service": "galaxy-downloader-backend",
        "version": APP_VERSION,
        "ytDlp": shutil.which("yt-dlp") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "node": shutil.which("node") is not None,
        "cookiesConfigured": bool(COOKIE_FILE),
        "proxyConfigured": bool(os.getenv("YTDLP_PROXY", "").strip()),
        "impersonation": os.getenv("YTDLP_IMPERSONATE", "chrome"),
        "parseAttempts": PARSE_ATTEMPTS,
        "parseConcurrency": PARSE_CONCURRENCY,
        "downloadConcurrency": DOWNLOAD_CONCURRENCY,
        "parseQueueTimeoutSeconds": PARSE_QUEUE_TIMEOUT_SECONDS,
        "downloadQueueTimeoutSeconds": DOWNLOAD_QUEUE_TIMEOUT_SECONDS,
        "maxDownloadBytes": MAX_DOWNLOAD_BYTES,
        "diskFreeBytes": disk_free_bytes,
    }


@app.get("/api/parse")
async def parse_media(
    request: Request,
    url: str = Query(..., min_length=8, max_length=MAX_SOURCE_URL_LENGTH),
    x_request_id: str | None = Header(default=None),
) -> JSONResponse:
    source_url = await asyncio.to_thread(validate_public_source_url, url)
    request_id = x_request_id or "unknown"
    if not await acquire_capacity(parse_slots, PARSE_QUEUE_TIMEOUT_SECONDS):
        return api_error_response(
            "BACKEND_BUSY",
            503,
            "Parser capacity is busy. Please retry shortly.",
            request_id,
            retry_after=5,
        )

    try:
        info = await asyncio.to_thread(parse_with_ytdlp, source_url)
        data = normalize_parse_result(info, source_url, public_base(request))
        return JSONResponse(
            {"success": True, "data": data, "requestId": request_id},
            headers={"X-Request-Id": request_id},
        )
    except HTTPException as exc:
        return api_error_response(
            "PARSE_FAILED",
            exc.status_code,
            public_error_message(exc, "parsing"),
            request_id,
        )
    except Exception:
        return api_error_response(
            "PARSE_FAILED",
            500,
            "Media parsing failed unexpectedly.",
            request_id,
        )
    finally:
        parse_slots.release()


@app.api_route("/api/download", methods=["GET", "HEAD"])
async def download_media(
    request: Request,
    url: str = Query(..., min_length=8, max_length=MAX_SOURCE_URL_LENGTH),
    media_type: str = Query(default="video", alias="type"),
    quality: str = Query(default="best", max_length=32),
    format_id: str | None = Query(default=None, alias="formatId", max_length=80),
    x_request_id: str | None = Header(default=None),
):
    if media_type not in {"video", "audio"}:
        raise HTTPException(status_code=400, detail="type must be video or audio")
    source_url = await asyncio.to_thread(validate_public_source_url, url)
    request_id = x_request_id or "unknown"

    if request.method == "HEAD":
        return JSONResponse(
            {"success": True, "ready": True, "requestId": request_id},
            headers={"X-Request-Id": request_id},
        )

    if not await acquire_capacity(download_slots, DOWNLOAD_QUEUE_TIMEOUT_SECONDS):
        return api_error_response(
            "BACKEND_BUSY",
            503,
            "Download capacity is busy. Please retry shortly.",
            request_id,
            retry_after=10,
        )

    directory: Path | None = None
    response_handoff = False
    try:
        directory = Path(tempfile.mkdtemp(prefix="galaxy-download-"))
        file_path = await asyncio.to_thread(
            download_with_ytdlp,
            source_url,
            media_type,
            quality,
            format_id,
            directory,
        )
        filename = safe_download_name(file_path)
        media_type_header = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        def cleanup() -> None:
            try:
                shutil.rmtree(directory, ignore_errors=True)
            finally:
                download_slots.release()

        response = FileResponse(
            path=file_path,
            filename=filename,
            media_type=media_type_header,
            headers={
                "X-Request-Id": request_id,
                "Cache-Control": "private, no-store",
                "Accept-Ranges": "bytes",
                "X-Max-Download-Bytes": str(MAX_DOWNLOAD_BYTES),
            },
            background=BackgroundTask(cleanup),
        )
        response_handoff = True
        return response
    except HTTPException as exc:
        return api_error_response(
            "DOWNLOAD_FAILED",
            exc.status_code,
            public_error_message(exc, "download"),
            request_id,
        )
    except Exception:
        return api_error_response(
            "DOWNLOAD_FAILED",
            500,
            "Media download failed unexpectedly.",
            request_id,
        )
    finally:
        if not response_handoff:
            if directory is not None:
                shutil.rmtree(directory, ignore_errors=True)
            download_slots.release()
