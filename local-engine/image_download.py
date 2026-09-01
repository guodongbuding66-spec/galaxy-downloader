from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from url_policy import PublicUrlError, validated_public_http_url

MAX_IMAGES_PER_JOB = 300
MAX_IMAGE_BYTES = 2 * 1024 * 1024 * 1024
MAX_BATCH_BYTES = 20 * 1024 * 1024 * 1024
CHUNK_BYTES = 512 * 1024
REQUEST_TIMEOUT_SECONDS = 35
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

_IMAGE_JOB_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_IMAGE_JOB_STATE: dict[str, Any] = {
    "busy": False,
    "progress": 0,
    "completed": 0,
    "total": 0,
    "status": "Ready",
    "detail": "Waiting for an image download job",
    "lastPath": None,
}


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _download_dir() -> Path:
    target = _app_dir() / "downloads"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _ffmpeg_executable() -> Path | None:
    names = ("ffmpeg.exe", "ffmpeg")
    for directory in (_app_dir() / "ffmpeg" / "bin", _app_dir() / "bin", _app_dir()):
        for name in names:
            candidate = directory / name
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def _set_state(**values: Any) -> None:
    with _STATE_LOCK:
        _IMAGE_JOB_STATE.update(values)


def image_job_status() -> dict[str, Any]:
    with _STATE_LOCK:
        return dict(_IMAGE_JOB_STATE)


def _safe_filename(value: object, fallback: str = "images") -> str:
    text = str(value or "").strip()
    text = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]+', "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")[:120]
    return text or fallback


def _origin_referer(value: object) -> str | None:
    source = str(value or "").strip()
    if not source:
        return None
    try:
        public = validated_public_http_url(source)
        parsed = urlparse(public)
    except (PublicUrlError, ValueError):
        return None
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}/"


def _default_referer(hostname: str) -> str | None:
    host = hostname.lower().rstrip(".")
    mappings = (
        (("mmbiz.qpic.cn",), "https://mp.weixin.qq.com/"),
        (("xhscdn.com", "xiaohongshu.com"), "https://www.xiaohongshu.com/"),
        (("douyinpic.com",), "https://www.douyin.com/"),
        (("tiktokcdn.com", "tiktokcdn-us.com"), "https://www.tiktok.com/"),
        (("cdninstagram.com", "fbcdn.net"), "https://www.instagram.com/"),
        (("twimg.com",), "https://x.com/"),
    )
    for suffixes, referer in mappings:
        if any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes):
            return referer
    return None


def _wechat_original_candidate(value: str) -> str | None:
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not (host == "mmbiz.qpic.cn" or host.endswith(".mmbiz.qpic.cn")):
        return None
    parts = parsed.path.rstrip("/").split("/")
    if not parts or not parts[-1].isdigit() or parts[-1] == "0":
        return None
    parts[-1] = "0"
    query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() != "tp"]
    return urlunparse(parsed._replace(path="/".join(parts), query=urlencode(query)))


def _image_candidates(value: str) -> list[str]:
    original = _wechat_original_candidate(value)
    result: list[str] = []
    for candidate in (original, value):
        if candidate and candidate not in result:
            result.append(candidate)
    return result


class _PublicRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        validated_public_http_url(str(newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = build_opener(_PublicRedirectHandler())


def _sniff_extension(first: bytes, content_type: str, source_url: str) -> str | None:
    content_type = content_type.split(";", 1)[0].strip().lower()
    by_type = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/avif": "avif",
        "image/bmp": "bmp",
    }
    if content_type in by_type:
        return by_type[content_type]
    if first.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if first.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if first.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if first.startswith(b"BM"):
        return "bmp"
    if len(first) >= 12 and first[:4] == b"RIFF" and first[8:12] == b"WEBP":
        return "webp"
    if len(first) >= 12 and first[4:8] == b"ftyp" and first[8:12] in {b"avif", b"avis"}:
        return "avif"

    parsed = urlparse(source_url)
    wx_fmt = dict(parse_qsl(parsed.query, keep_blank_values=True)).get("wx_fmt", "").lower()
    if wx_fmt in {"jpeg", "jpg", "png", "gif", "webp", "avif", "bmp"}:
        return "jpg" if wx_fmt in {"jpeg", "jpg"} else wx_fmt
    match = re.search(r"\.([a-z0-9]{2,5})$", parsed.path, re.I)
    if match:
        ext = match.group(1).lower()
        if ext in {"jpeg", "jpg", "png", "gif", "webp", "avif", "bmp"}:
            return "jpg" if ext == "jpeg" else ext
    return None


def _source_prefers_jpeg(value: str) -> bool:
    parsed = urlparse(value)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    hint = str(query.get("wx_fmt") or query.get("format") or "").lower()
    if hint in {"jpg", "jpeg"}:
        return True
    return bool(re.search(r"\.jpe?g$", parsed.path, re.I))


def _unique_path(directory: Path, stem: str, extension: str) -> Path:
    base = directory / f"{stem}.{extension}"
    if not base.exists():
        return base
    for index in range(2, 10000):
        candidate = directory / f"{stem}-{index}.{extension}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not allocate a unique image filename")


def _download_one(
    raw_url: str,
    destination_dir: Path,
    stem: str,
    source_referer: str | None,
) -> tuple[Path, int]:
    last_error: Exception | None = None
    for candidate in _image_candidates(validated_public_http_url(raw_url)):
        try:
            validated = validated_public_http_url(candidate)
            parsed = urlparse(validated)
            headers = {
                "User-Agent": USER_AGENT,
                "Accept": "image/jpeg,image/png,image/gif,image/webp,image/avif,image/*;q=0.8,*/*;q=0.1",
                "Accept-Encoding": "identity",
            }
            referer = source_referer or _default_referer(parsed.hostname or "")
            if referer:
                headers["Referer"] = referer
            request = Request(validated, headers=headers, method="GET")
            with _OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                declared = int(response.headers.get("Content-Length") or "0")
                if declared > MAX_IMAGE_BYTES:
                    raise ValueError("Image exceeds the local per-image safety limit")
                first = response.read(CHUNK_BYTES)
                extension = _sniff_extension(
                    first,
                    response.headers.get("Content-Type") or "",
                    response.geturl() or validated,
                )
                if not extension:
                    raise ValueError("Upstream response is not a recognized image")
                destination = _unique_path(destination_dir, stem, extension)
                part = destination.with_suffix(destination.suffix + ".part")
                total = len(first)
                with part.open("wb") as handle:
                    handle.write(first)
                    while True:
                        chunk = response.read(CHUNK_BYTES)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_IMAGE_BYTES:
                            raise ValueError("Image exceeds the local per-image safety limit")
                        handle.write(chunk)
                part.replace(destination)
                return destination, total
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    raise last_error or RuntimeError("Image download failed")


def _convert_modern_image(path: Path, original_url: str) -> Path:
    if path.suffix.lower() not in {".webp", ".avif"}:
        return path
    ffmpeg = _ffmpeg_executable()
    if not ffmpeg:
        return path
    extension = "jpg" if _source_prefers_jpeg(original_url) else "png"
    output = path.with_suffix(f".{extension}")
    command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(path)]
    if extension == "jpg":
        command.extend(["-q:v", "2"])
    command.extend(["-frames:v", "1", str(output)])
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return path
    if completed.returncode != 0 or not output.exists() or output.stat().st_size <= 0:
        output.unlink(missing_ok=True)
        return path
    path.unlink(missing_ok=True)
    return output


def _archive_text(payload: dict[str, Any]) -> str:
    title = str(payload.get("title") or "Images").strip()
    lines = [title]
    author = str(payload.get("author") or "").strip()
    published = str(payload.get("publishedAt") or "").strip()
    source = str(payload.get("sourceUrl") or "").strip()
    description = str(payload.get("description") or "").strip()
    if author:
        lines.append(f"Author: {author}")
    if published:
        lines.append(f"Published: {published}")
    if source:
        lines.append(f"Source: {source}")
    if description:
        lines.extend(["", description])
    return "\n".join(lines).strip()


def _archive_markdown(payload: dict[str, Any], files: list[tuple[str, Path]]) -> str:
    title = str(payload.get("title") or "Images").strip()
    markdown = str(payload.get("markdownContent") or "").strip()
    if not markdown:
        description = str(payload.get("description") or "").strip()
        markdown = f"# {title}"
        if description:
            markdown += f"\n\n{description}"
        for _url, path in files:
            markdown += f"\n\n![]({path.name})"
    for original_url, path in files:
        markdown = markdown.replace(original_url, path.name)
    return markdown.strip() + "\n"


def _run_image_job(payload: dict[str, Any]) -> None:
    images = [str(value).strip() for value in payload.get("images", []) if str(value).strip()]
    images = images[:MAX_IMAGES_PER_JOB]
    title = _safe_filename(payload.get("title"), "images")
    package = bool(payload.get("package", False))
    referer = _origin_referer(payload.get("sourceUrl"))
    downloads = _download_dir()
    work_dir: Path | None = None
    downloaded: list[tuple[str, Path]] = []
    total_bytes = 0

    try:
        if not images:
            raise ValueError("No image URLs were supplied")
        _set_state(
            busy=True,
            progress=0,
            completed=0,
            total=len(images),
            status="Downloading images",
            detail="Downloading original images directly to this computer",
            lastPath=None,
        )
        destination_dir = downloads
        if package:
            work_dir = Path(tempfile.mkdtemp(prefix=".galaxy-images-", dir=downloads))
            destination_dir = work_dir

        for index, image_url in enumerate(images, start=1):
            stem = f"{title}-{index}"
            path, size = _download_one(image_url, destination_dir, stem, referer)
            path = _convert_modern_image(path, image_url)
            total_bytes += size
            if total_bytes > MAX_BATCH_BYTES:
                raise ValueError("Image batch exceeds the local safety limit")
            downloaded.append((image_url, path))
            _set_state(
                completed=index,
                progress=round(index * 100 / len(images)),
                detail=f"Saved {index} of {len(images)} images",
            )

        if package:
            zip_path = _unique_path(downloads, title, "zip")
            text = _archive_text(payload)
            markdown = _archive_markdown(payload, downloaded)
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
                for _source, path in downloaded:
                    archive.write(path, arcname=path.name)
                if text:
                    archive.writestr(f"{title}.txt", text.encode("utf-8"))
                archive.writestr(f"{title}.md", markdown.encode("utf-8"))
            final_path = zip_path
        else:
            final_path = downloaded[-1][1]

        _set_state(
            busy=False,
            progress=100,
            status="Completed",
            detail=f"Saved to {final_path}",
            lastPath=str(final_path),
        )
    except Exception as exc:  # noqa: BLE001
        _set_state(
            busy=False,
            status="Download failed",
            detail=str(exc),
        )
    finally:
        if work_dir is not None:
            shutil.rmtree(work_dir, ignore_errors=True)
        _IMAGE_JOB_LOCK.release()


def start_image_download_job(payload: dict[str, Any]) -> tuple[bool, str]:
    images = payload.get("images")
    if not isinstance(images, list) or not images:
        return False, "At least one image URL is required"
    if len(images) > MAX_IMAGES_PER_JOB:
        return False, f"A maximum of {MAX_IMAGES_PER_JOB} images is allowed per job"
    if not _IMAGE_JOB_LOCK.acquire(blocking=False):
        return False, "Galaxy Local Engine is already processing an image job"
    threading.Thread(
        target=_run_image_job,
        args=(dict(payload),),
        name="GalaxyImageDownload",
        daemon=True,
    ).start()
    return True, "Image download job accepted"
