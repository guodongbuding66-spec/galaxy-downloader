from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from course_attachments import CourseAttachmentError, ensure_course_attachments
from course_workspace import course_database_path

ATTACHMENT_FILE_SCHEMA_VERSION = 1
MAX_ATTACHMENT_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_RELATIVE_PATH_CHARS = 720
_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class CourseAttachmentFileError(RuntimeError):
    pass


def _clean_id(value: object, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(clean):
        raise CourseAttachmentFileError(f"invalid {label} id")
    return clean


def _clean_relative_path(value: object) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or len(raw) > MAX_RELATIVE_PATH_CHARS or "\x00" in raw:
        raise CourseAttachmentFileError("invalid attachment file path")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise CourseAttachmentFileError("invalid attachment file path")
    return path.as_posix()


def _bounded_size(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise CourseAttachmentFileError("attachment file size must be an integer") from exc
    if parsed < 0 or parsed > MAX_ATTACHMENT_FILE_BYTES:
        raise CourseAttachmentFileError("attachment file exceeds size limit")
    return parsed


def _connect(engine_module) -> sqlite3.Connection:
    try:
        ensure_course_attachments(engine_module)
    except CourseAttachmentError as exc:
        raise CourseAttachmentFileError(str(exc)) from exc
    connection = sqlite3.connect(course_database_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS learning_attachment_file_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS course_attachment_files (
            attachment_id TEXT PRIMARY KEY REFERENCES course_item_attachments(id) ON DELETE CASCADE,
            relative_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    row = connection.execute(
        "SELECT value FROM learning_attachment_file_meta WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO learning_attachment_file_meta(key, value) VALUES('schema_version', ?)",
            (str(ATTACHMENT_FILE_SCHEMA_VERSION),),
        )
    else:
        try:
            version = int(row["value"])
        except (TypeError, ValueError) as exc:
            connection.close()
            raise CourseAttachmentFileError("attachment file schema version is invalid") from exc
        if version != ATTACHMENT_FILE_SCHEMA_VERSION:
            connection.close()
            raise CourseAttachmentFileError(f"unsupported attachment file schema version: {version}")
    connection.commit()
    return connection


def _download_root(engine_module) -> Path:
    root = Path(engine_module.default_download_dir()).expanduser()
    if root.exists() and root.is_symlink():
        raise CourseAttachmentFileError("download root cannot be a symbolic link")
    root = root.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    return root


def record_course_attachment_file(
    engine_module,
    attachment_id: object,
    *,
    relative_path: object,
    size_bytes: object,
) -> dict[str, Any]:
    attachment = _clean_id(attachment_id, "attachment")
    rendered_path = _clean_relative_path(relative_path)
    rendered_size = _bounded_size(size_bytes)
    with closing(_connect(engine_module)) as connection:
        if connection.execute(
            "SELECT 1 FROM course_item_attachments WHERE id=?", (attachment,)
        ).fetchone() is None:
            raise CourseAttachmentFileError("course attachment not found")
        connection.execute(
            """
            INSERT INTO course_attachment_files(attachment_id, relative_path, size_bytes)
            VALUES(?, ?, ?)
            ON CONFLICT(attachment_id) DO UPDATE SET
                relative_path=excluded.relative_path,
                size_bytes=excluded.size_bytes,
                updated_at=CURRENT_TIMESTAMP
            """,
            (attachment, rendered_path, rendered_size),
        )
        connection.commit()
    return {
        "attachmentId": attachment,
        "relativePath": rendered_path,
        "sizeBytes": rendered_size,
    }


def attachment_file_record(engine_module, attachment_id: object) -> dict[str, Any] | None:
    attachment = _clean_id(attachment_id, "attachment")
    with closing(_connect(engine_module)) as connection:
        row = connection.execute(
            "SELECT attachment_id, relative_path, size_bytes FROM course_attachment_files WHERE attachment_id=?",
            (attachment,),
        ).fetchone()
    if row is None:
        return None
    return {
        "attachmentId": str(row["attachment_id"]),
        "relativePath": str(row["relative_path"]),
        "sizeBytes": int(row["size_bytes"]),
    }


def _resolved_file(engine_module, record: dict[str, Any]) -> Path | None:
    try:
        root = _download_root(engine_module)
        relative = _clean_relative_path(record.get("relativePath"))
        candidate = (root / Path(*PurePosixPath(relative).parts)).resolve(strict=False)
        candidate.relative_to(root)
        if not candidate.is_file():
            return None
        return candidate
    except (CourseAttachmentFileError, OSError, RuntimeError, ValueError):
        return None


def attachment_file_status(engine_module, attachment_id: object) -> dict[str, Any]:
    attachment = _clean_id(attachment_id, "attachment")
    record = attachment_file_record(engine_module, attachment)
    if record is None:
        return {"attachmentId": attachment, "downloaded": False, "sizeBytes": 0, "fileName": ""}
    path = _resolved_file(engine_module, record)
    if path is None:
        return {"attachmentId": attachment, "downloaded": False, "sizeBytes": 0, "fileName": ""}
    try:
        size = min(int(path.stat().st_size), MAX_ATTACHMENT_FILE_BYTES)
    except OSError:
        size = int(record.get("sizeBytes") or 0)
    return {
        "attachmentId": attachment,
        "downloaded": True,
        "sizeBytes": max(0, size),
        "fileName": path.name[:240],
    }


def attachment_provider_source(engine_module, attachment_id: object) -> str:
    attachment = _clean_id(attachment_id, "attachment")
    with closing(_connect(engine_module)) as connection:
        row = connection.execute(
            """
            SELECT c.source_url
            FROM course_item_attachments a
            JOIN course_items i ON i.id=a.course_item_id
            JOIN courses c ON c.id=i.course_id
            WHERE a.id=?
            """,
            (attachment,),
        ).fetchone()
    if row is None:
        raise CourseAttachmentFileError("course attachment not found")
    return str(row["source_url"] or "").strip()


def enrich_course_attachment_files(
    engine_module,
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    values = [dict(item) for item in items if isinstance(item, dict)]
    for item in values:
        attachments = item.get("attachments")
        if not isinstance(attachments, list):
            continue
        enriched: list[dict[str, Any]] = []
        for raw in attachments:
            if not isinstance(raw, dict):
                continue
            entry = dict(raw)
            attachment_id = str(entry.get("id") or "").strip().lower()
            if _ID_RE.fullmatch(attachment_id):
                status = attachment_file_status(engine_module, attachment_id)
                entry["downloaded"] = bool(status["downloaded"])
                entry["sizeBytes"] = int(status["sizeBytes"])
            enriched.append(entry)
        item["attachments"] = enriched
    return values
