from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.background import BackgroundTask
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

APP_VERSION = "0.1.0"
PARSE_TIMEOUT_SECONDS = int(os.getenv("PARSE_TIMEOUT_SECONDS", "90"))
DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "1800"))
MAX_SOURCE_URL_LENGTH = 4096
PARSE_CONCURRENCY = int(os.getenv("PARSE_CONCURRENCY", "4"))
DOWNLOAD_CONCURRENCY = int(os.getenv("DOWNLOAD_CONCURRENCY", "2"))

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
    expose_headers=["Content-Length", "Content-Range", "Content-Disposition", "Accept-Ranges", "X-Request-Id"],
)

COOKIE_PATH = Path("/tmp/galaxy-cookies.txt")


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
    (("xiaohongshu", "xiaohongshu"), "xiaohongshu"),
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


def parse_with_ytdlp(source_url: str) -> dict[str, Any]:
    command = common_yt_dlp_args() + [
        "--dump-single-json",
        "--skip-download",
        source_url,
    ]
    try:
        completed = run_process(command, PARSE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Parser timed out") from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "yt-dlp failed")[-4000:].strip()
        raise HTTPException(status_code=502, detail=message)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Parser returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Parser returned an invalid result")
    if payload.get("_type") == "playlist":
        entries = [entry for entry in payload.get("entries") or [] if isinstance(entry, dict)]
        if not entries:
            raise HTTPException(status_code=404, detail="No downloadable media was found")
        payload = entries[0]
    return payload


def best_format_groups(info: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    formats = [fmt for fmt in info.get("formats") or [] if isinstance(fmt, dict) and isinstance(fmt.get("url"), str)]
    videos = [fmt for fmt in formats if codec_present(fmt.get("vcodec"))]
    audios = [fmt for fmt in formats if codec_present(fmt.get("acodec"))]
    has_muxed = any(codec_present(fmt.get("vcodec")) and codec_present(fmt.get("acodec")) for fmt in formats)
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
    has_video_only = any(codec_present(fmt.get("vcodec")) and not codec_present(fmt.get("acodec")) for fmt in videos)
    has_audio_only = any(codec_present(fmt.get("acodec")) and not codec_present(fmt.get("vcodec")) for fmt in audios)

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
    }


def select_format(media_type: str, quality: str, format_id: str | None) -> str:
    if media_type == "audio":
        return "ba/b"
    if format_id:
        safe_id = re.sub(r"[^A-Za-z0-9_.+-]", "", format_id)
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


def download_with_ytdlp(source_url: str, media_type: str, quality: str, format_id: str | None, output_dir: Path) -> Path:
    selector = select_format(media_type, quality, format_id)
    command = common_yt_dlp_args() + [
        "--quiet",
        "--no-progress",
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
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "yt-dlp download failed")[-4000:].strip()
        raise HTTPException(status_code=502, detail=message)
    return find_downloaded_file(output_dir)


def safe_download_name(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "-", path.stem).strip(" .-") or "media"
    return f"{stem[:120]}{path.suffix.lower()}"


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "galaxy-downloader-backend",
        "version": APP_VERSION,
        "ytDlp": shutil.which("yt-dlp") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "cookiesConfigured": bool(COOKIE_FILE),
        "proxyConfigured": bool(os.getenv("YTDLP_PROXY", "").strip()),
        "impersonation": os.getenv("YTDLP_IMPERSONATE", "chrome"),
    }


@app.get("/api/parse")
async def parse_media(
    request: Request,
    url: str = Query(..., min_length=8, max_length=MAX_SOURCE_URL_LENGTH),
    x_request_id: str | None = Header(default=None),
) -> JSONResponse:
    source_url = await asyncio.to_thread(validate_public_source_url, url)
    request_id = x_request_id or "unknown"
    async with parse_slots:
        try:
            info = await asyncio.to_thread(parse_with_ytdlp, source_url)
            data = normalize_parse_result(info, source_url, public_base(request))
            return JSONResponse({"success": True, "data": data, "requestId": request_id}, headers={"X-Request-Id": request_id})
        except HTTPException as exc:
            return JSONResponse(
                {"success": False, "code": "PARSE_FAILED", "status": exc.status_code, "error": str(exc.detail), "requestId": request_id},
                status_code=exc.status_code,
                headers={"X-Request-Id": request_id},
            )


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

    # A HEAD request verifies service reachability without starting an expensive
    # download. Actual media probing should use GET/Range when content is needed.
    if request.method == "HEAD":
        return JSONResponse(
            {"success": True, "ready": True, "requestId": request_id},
            headers={"X-Request-Id": request_id},
        )

    await download_slots.acquire()
    directory = Path(tempfile.mkdtemp(prefix="galaxy-download-"))
    try:
        file_path = await asyncio.to_thread(
            download_with_ytdlp,
            source_url,
            media_type,
            quality,
            format_id,
            directory,
        )
        filename = safe_download_name(file_path)

        def cleanup() -> None:
            try:
                shutil.rmtree(directory, ignore_errors=True)
            finally:
                download_slots.release()

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/octet-stream",
            headers={
                "X-Request-Id": request_id,
                "Cache-Control": "private, no-store",
                "Accept-Ranges": "bytes",
            },
            background=BackgroundTask(cleanup),
        )
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        download_slots.release()
        raise
