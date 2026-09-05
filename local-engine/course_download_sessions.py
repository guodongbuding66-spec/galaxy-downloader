from __future__ import annotations

import re
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from course_workspace import CourseWorkspaceError, add_media_to_course
from headless_output_tracking import clear_output_tracking, tracked_output_paths
from media_library import resolve_media_item_path, search_media_items, sync_media_library

MAX_COURSE_DOWNLOAD_SESSIONS = 500
_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_PROVIDER_RE = re.compile(r"^[a-z0-9_-]{1,40}$")
_LOCK = threading.RLock()
_SESSIONS: OrderedDict[str, dict[str, Any]] = OrderedDict()


class CourseDownloadSessionError(RuntimeError):
    pass


def _clean_id(value: object, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(clean):
        raise CourseDownloadSessionError(f"invalid {label} id")
    return clean


def _clean_provider(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _PROVIDER_RE.fullmatch(clean):
        raise CourseDownloadSessionError("invalid course provider")
    return clean


def _clean_source_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 900:
        raise CourseDownloadSessionError("invalid course source URL")
    try:
        parsed = urlsplit(raw)
        hostname = str(parsed.hostname or "").strip().lower()
        if parsed.scheme.lower() not in {"http", "https"} or not hostname:
            raise CourseDownloadSessionError("invalid course source URL")
        if parsed.username is not None or parsed.password is not None:
            raise CourseDownloadSessionError("invalid course source URL")
        host = hostname
        try:
            if parsed.port:
                host = f"{host}:{parsed.port}"
        except ValueError as exc:
            raise CourseDownloadSessionError("invalid course source URL") from exc
        clean = urlunsplit((parsed.scheme.lower(), host, parsed.path or "/", "", ""))
    except CourseDownloadSessionError:
        raise
    except ValueError as exc:
        raise CourseDownloadSessionError("invalid course source URL") from exc
    if len(clean) > 900:
        raise CourseDownloadSessionError("invalid course source URL")
    return clean


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _public(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "jobId": session["jobId"],
        "courseId": session["courseId"],
        "provider": session["provider"],
        "sourceUrl": session["sourceUrl"],
        "syncState": session["syncState"],
        "outputCount": int(session.get("outputCount") or 0),
        "syncedCount": int(session.get("syncedCount") or 0),
        "syncError": str(session.get("syncError") or ""),
        "createdAt": session["createdAt"],
        "updatedAt": session["updatedAt"],
    }


def _evict_terminal_sessions_locked() -> None:
    if len(_SESSIONS) < MAX_COURSE_DOWNLOAD_SESSIONS:
        return
    for job_id, session in list(_SESSIONS.items()):
        if session.get("syncState") in {"synced", "failed"}:
            _SESSIONS.pop(job_id, None)
            try:
                clear_output_tracking(session["trackingId"])
            except Exception:
                pass
        if len(_SESSIONS) < MAX_COURSE_DOWNLOAD_SESSIONS:
            return


def register_course_download_session(
    *,
    job_id: object,
    tracking_id: object,
    course_id: object,
    provider: object,
    source_url: object,
) -> dict[str, Any]:
    clean_job = _clean_id(job_id, "job")
    clean_tracking = _clean_id(tracking_id, "tracking")
    clean_course = _clean_id(course_id, "course")
    clean_provider = _clean_provider(provider)
    clean_url = _clean_source_url(source_url)
    now = _now()
    with _LOCK:
        existing = _SESSIONS.get(clean_job)
        if existing is not None:
            if (
                existing["trackingId"] == clean_tracking
                and existing["courseId"] == clean_course
                and existing["provider"] == clean_provider
                and existing["sourceUrl"] == clean_url
            ):
                _SESSIONS.move_to_end(clean_job)
                return _public(existing)
            raise CourseDownloadSessionError("course download session already exists")
        _evict_terminal_sessions_locked()
        if len(_SESSIONS) >= MAX_COURSE_DOWNLOAD_SESSIONS:
            raise CourseDownloadSessionError("course download session limit reached")
        session = {
            "jobId": clean_job,
            "trackingId": clean_tracking,
            "courseId": clean_course,
            "provider": clean_provider,
            "sourceUrl": clean_url,
            "syncState": "pending",
            "outputCount": 0,
            "syncedCount": 0,
            "syncError": "",
            "createdAt": now,
            "updatedAt": now,
        }
        _SESSIONS[clean_job] = session
        return _public(session)


def course_download_session(job_id: object) -> dict[str, Any] | None:
    clean = _clean_id(job_id, "job")
    with _LOCK:
        session = _SESSIONS.get(clean)
        if session is None:
            return None
        _SESSIONS.move_to_end(clean)
        return _public(session)


def remove_course_download_session(job_id: object, *, clear_tracking: bool = True) -> bool:
    clean = _clean_id(job_id, "job")
    with _LOCK:
        session = _SESSIONS.pop(clean, None)
    if session is None:
        return False
    if clear_tracking:
        try:
            clear_output_tracking(session["trackingId"])
        except Exception:
            pass
    return True


def mark_course_download_sync_failed(job_id: object, detail: object) -> dict[str, Any]:
    clean = _clean_id(job_id, "job")
    message = " ".join(str(detail or "course output sync failed").split()).strip()[:360]
    with _LOCK:
        session = _SESSIONS.get(clean)
        if session is None:
            raise CourseDownloadSessionError("course download session not found")
        if session["syncState"] == "synced":
            return _public(session)
        session["syncState"] = "failed"
        session["syncError"] = message or "course output sync failed"
        session["updatedAt"] = _now()
        _SESSIONS.move_to_end(clean)
        return _public(session)


def _lookup_media_id(engine_module, output: Path) -> str:
    try:
        expected = output.resolve(strict=True)
    except (OSError, RuntimeError):
        return ""
    for item in search_media_items(engine_module, output.name, limit=200):
        if item.get("fileName") != output.name or not item.get("available"):
            continue
        media_id = str(item.get("id") or "")
        if not _ID_RE.fullmatch(media_id):
            continue
        resolved = resolve_media_item_path(engine_module, media_id)
        if resolved is None:
            continue
        try:
            if resolved.resolve(strict=False) == expected:
                return media_id
        except (OSError, RuntimeError):
            continue
    return ""


def _library_records(session: dict[str, Any], outputs: list[Path]) -> list[dict[str, Any]]:
    finished = _now()
    records: list[dict[str, Any]] = []
    for output in outputs:
        records.append(
            {
                "state": "completed",
                "finishedAt": finished,
                "label": output.stem[:220],
                "sourceUrl": session["sourceUrl"],
                "filePath": str(output),
                "fileName": output.name[:220],
                "collectionMode": "course",
                "durationSeconds": 0,
                "retryPayload": {"sourceUrl": session["sourceUrl"]},
            }
        )
    return records


def sync_course_download_outputs(engine_module, job_id: object) -> dict[str, Any]:
    clean = _clean_id(job_id, "job")
    with _LOCK:
        session = _SESSIONS.get(clean)
        if session is None:
            raise CourseDownloadSessionError("course download session not found")
        if session["syncState"] == "synced":
            _SESSIONS.move_to_end(clean)
            return _public(session)
        if session["syncState"] == "syncing":
            raise CourseDownloadSessionError("course download session is already syncing")
        session["syncState"] = "syncing"
        session["syncError"] = ""
        session["updatedAt"] = _now()
        tracking_id = str(session["trackingId"])
        course_id = str(session["courseId"])
        session_snapshot = dict(session)

    try:
        outputs = tracked_output_paths(tracking_id, existing_only=True)
        if not outputs:
            raise CourseDownloadSessionError("no final course output files were tracked")
        records = _library_records(session_snapshot, outputs)
        sync_media_library(engine_module, records)
        media_ids: list[str] = []
        for output in outputs:
            media_id = _lookup_media_id(engine_module, output)
            if not media_id:
                raise CourseDownloadSessionError(f"media library did not index output: {output.name}")
            media_ids.append(media_id)
        synced = 0
        for media_id in media_ids:
            try:
                add_media_to_course(engine_module, course_id, media_id)
            except CourseWorkspaceError as exc:
                raise CourseDownloadSessionError(str(exc)) from exc
            synced += 1
    except Exception as exc:
        with _LOCK:
            current = _SESSIONS.get(clean)
            if current is not None and current["syncState"] != "synced":
                current["syncState"] = "failed"
                current["syncError"] = " ".join(str(exc).split()).strip()[:360] or "course output sync failed"
                current["updatedAt"] = _now()
        if isinstance(exc, CourseDownloadSessionError):
            raise
        raise CourseDownloadSessionError(str(exc)) from exc

    with _LOCK:
        current = _SESSIONS.get(clean)
        if current is None:
            raise CourseDownloadSessionError("course download session disappeared during sync")
        current["syncState"] = "synced"
        current["outputCount"] = len(outputs)
        current["syncedCount"] = synced
        current["syncError"] = ""
        current["updatedAt"] = _now()
        result = _public(current)
        _SESSIONS.move_to_end(clean)
    clear_output_tracking(tracking_id)
    return result
