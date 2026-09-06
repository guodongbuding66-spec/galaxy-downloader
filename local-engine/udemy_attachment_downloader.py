from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from course_attachment_files import (
    MAX_ATTACHMENT_FILE_BYTES,
    CourseAttachmentFileError,
    attachment_file_status,
    attachment_provider_source,
    record_course_attachment_file,
)
from course_attachments import CourseAttachmentError, attachment_download_context
from headless_browser_cookies import browser_cookie_source
from url_policy import validated_public_http_url
from yt_dlp import YoutubeDL
from yt_dlp.extractor.udemy import UdemyIE
from yt_dlp.networking import Request

_CHUNK_BYTES = 256 * 1024
_PROVIDER_NUMERIC_RE = re.compile(r"^udemy:(course|lecture|asset):(\d{1,40})$")


class UdemyAttachmentDownloadError(RuntimeError):
    pass


class UdemyAttachmentDownloadCancelled(UdemyAttachmentDownloadError):
    pass


def _numeric_provider_id(value: object, expected_kind: str) -> str:
    clean = str(value or "").strip().lower()
    match = _PROVIDER_NUMERIC_RE.fullmatch(clean)
    if match is None or match.group(1) != expected_kind:
        raise UdemyAttachmentDownloadError(f"invalid Udemy {expected_kind} id")
    return match.group(2)


def _udemy_origin(source_url: object) -> str:
    try:
        validated = validated_public_http_url(str(source_url or ""))
        parsed = urlsplit(validated)
    except Exception as exc:
        raise UdemyAttachmentDownloadError("course source URL is unavailable") from exc
    host = str(parsed.hostname or "").strip().lower().rstrip(".")
    if host != "udemy.com" and not host.endswith(".udemy.com"):
        raise UdemyAttachmentDownloadError("course source is not an Udemy host")
    if parsed.username is not None or parsed.password is not None:
        raise UdemyAttachmentDownloadError("course source URL is invalid")
    netloc = host
    try:
        if parsed.port:
            netloc = f"{host}:{parsed.port}"
    except ValueError as exc:
        raise UdemyAttachmentDownloadError("course source URL is invalid") from exc
    return urlunsplit((parsed.scheme.lower(), netloc, "", "", ""))


def _select_download_url(value: object) -> str:
    if not isinstance(value, dict):
        raise UdemyAttachmentDownloadError("attachment metadata is unavailable")
    payload = value.get("asset") if isinstance(value.get("asset"), dict) else value
    download_urls = payload.get("download_urls") if isinstance(payload, dict) else None
    if not isinstance(download_urls, dict):
        raise UdemyAttachmentDownloadError("attachment is not downloadable")
    for entries in download_urls.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw = str(entry.get("file") or entry.get("url") or "").strip()
            if not raw:
                continue
            try:
                return validated_public_http_url(raw)
            except Exception:
                continue
    raise UdemyAttachmentDownloadError("attachment download URL is unavailable")


def _safe_file_name(value: object, attachment_id: str) -> str:
    name = re.split(r"[\\/]", str(value or "").replace("\x00", " "))[-1].strip(" .")[:240]
    return name or f"attachment-{attachment_id}.bin"


def _response_size(response) -> int:
    headers = getattr(response, "headers", None)
    if headers is None:
        return 0
    try:
        raw = headers.get("Content-Length") or headers.get("content-length") or ""
        parsed = int(raw)
    except (AttributeError, TypeError, ValueError):
        return 0
    if parsed < 0:
        return 0
    if parsed > MAX_ATTACHMENT_FILE_BYTES:
        raise UdemyAttachmentDownloadError("attachment file exceeds size limit")
    return parsed


def _download_options(browser: str) -> dict[str, Any]:
    options: dict[str, Any] = {
        "ignoreconfig": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 2,
    }
    if browser != "none":
        options["cookiesfrombrowser"] = (browser, None, None, None)
    return options


def download_udemy_attachment(
    engine_module,
    attachment_id: object,
    *,
    browser: object = "none",
    cancel_event: threading.Event | None = None,
    progress_hook: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    try:
        context = attachment_download_context(engine_module, attachment_id)
        browser_id = browser_cookie_source(browser)
    except CourseAttachmentError as exc:
        raise UdemyAttachmentDownloadError(str(exc)) from exc

    if str(context.get("provider") or "").strip().lower() != "udemy":
        raise UdemyAttachmentDownloadError("unsupported attachment provider")
    attachment = str(context["id"])
    existing = attachment_file_status(engine_module, attachment)
    if existing.get("downloaded"):
        return dict(existing)

    course_id = _numeric_provider_id(context.get("providerCourseId"), "course")
    lecture_id = _numeric_provider_id(context.get("providerLectureId"), "lecture")
    asset_id = _numeric_provider_id(context.get("providerAttachmentId"), "asset")
    try:
        source_url = attachment_provider_source(engine_module, attachment)
    except CourseAttachmentFileError as exc:
        raise UdemyAttachmentDownloadError(str(exc)) from exc
    origin = _udemy_origin(source_url)
    file_name = _safe_file_name(context.get("fileName") or context.get("title"), attachment)

    root = Path(engine_module.default_download_dir()).expanduser().resolve(strict=False)
    relative = Path("Course Attachments") / str(context["courseItemId"]) / attachment / file_name
    final_path = (root / relative).resolve(strict=False)
    try:
        final_path.relative_to(root)
    except ValueError as exc:
        raise UdemyAttachmentDownloadError("attachment output path escaped download root") from exc
    final_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = final_path.with_name(final_path.name + ".part")
    endpoint = (
        f"{origin}/api-2.0/users/me/subscribed-courses/{course_id}/lectures/"
        f"{lecture_id}/supplementary-assets/{asset_id}/"
    )
    cancel = cancel_event or threading.Event()
    progress = progress_hook or (lambda _downloaded, _total, _name: None)

    try:
        if cancel.is_set():
            raise UdemyAttachmentDownloadCancelled("attachment download cancelled")
        with YoutubeDL(_download_options(browser_id)) as ydl:
            extractor = UdemyIE(ydl)
            metadata = extractor._download_json(
                endpoint,
                asset_id,
                "Resolving authorized course attachment",
                query={"fields[asset]": "download_urls"},
            )
            download_url = _select_download_url(metadata)
            if cancel.is_set():
                raise UdemyAttachmentDownloadCancelled("attachment download cancelled")
            response = ydl.urlopen(Request(download_url))
            try:
                expected = _response_size(response)
                downloaded = 0
                progress(downloaded, expected, file_name)
                with part_path.open("wb") as handle:
                    while True:
                        if cancel.is_set():
                            raise UdemyAttachmentDownloadCancelled("attachment download cancelled")
                        chunk = response.read(_CHUNK_BYTES)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > MAX_ATTACHMENT_FILE_BYTES:
                            raise UdemyAttachmentDownloadError("attachment file exceeds size limit")
                        handle.write(chunk)
                        progress(downloaded, expected, file_name)
                    if downloaded <= 0:
                        raise UdemyAttachmentDownloadError("attachment download returned an empty file")
                    if expected > 0 and downloaded < expected:
                        raise UdemyAttachmentDownloadError("attachment download was incomplete")
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

        os.replace(part_path, final_path)
        try:
            record_course_attachment_file(
                engine_module,
                attachment,
                relative_path=relative.as_posix(),
                size_bytes=downloaded,
            )
        except Exception:
            try:
                final_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        progress(downloaded, downloaded, file_name)
        return {
            "attachmentId": attachment,
            "downloaded": True,
            "sizeBytes": downloaded,
            "fileName": file_name,
        }
    except UdemyAttachmentDownloadCancelled:
        try:
            part_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except Exception as exc:
        try:
            part_path.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(exc, UdemyAttachmentDownloadError):
            raise
        raise UdemyAttachmentDownloadError("authorized attachment download failed") from exc
