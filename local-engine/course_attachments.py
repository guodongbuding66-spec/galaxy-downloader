from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import closing
from typing import Any, Iterable

from course_workspace import course_database_path, list_courses

ATTACHMENT_SCHEMA_VERSION = 1
MAX_ATTACHMENTS_PER_ITEM = 128
MAX_ATTACHMENT_TITLE_CHARS = 240
MAX_ATTACHMENT_FILE_NAME_CHARS = 240
MAX_ATTACHMENT_TYPE_CHARS = 60
_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_PROVIDER_RE = re.compile(r"^[a-z0-9_-]{1,40}$")
_PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_UDEMY_COURSE_RE = re.compile(r"^udemy:course:\d{1,40}$")
_UDEMY_LECTURE_RE = re.compile(r"^udemy:lecture:\d{1,40}$")
_UDEMY_ASSET_RE = re.compile(r"^udemy:asset:\d{1,40}$")


class CourseAttachmentError(RuntimeError):
    pass


def _clean_id(value: object, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(clean):
        raise CourseAttachmentError(f"invalid {label} id")
    return clean


def _clean_provider(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _PROVIDER_RE.fullmatch(clean):
        raise CourseAttachmentError("invalid attachment provider")
    if clean != "udemy":
        raise CourseAttachmentError("unsupported attachment provider")
    return clean


def _clean_provider_id(value: object, label: str, *, required: bool = True) -> str:
    clean = str(value or "").strip()[:160]
    if not clean:
        if required:
            raise CourseAttachmentError(f"{label} is required")
        return ""
    if not _PROVIDER_ID_RE.fullmatch(clean):
        raise CourseAttachmentError(f"invalid {label}")
    return clean


def _clean_text(value: object, limit: int) -> str:
    clean = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    return clean[:limit]


def _clean_file_name(value: object) -> str:
    clean = _clean_text(value, MAX_ATTACHMENT_FILE_NAME_CHARS * 2)
    if not clean:
        return ""
    # Provider filenames are metadata only here, but keep them basename-only so
    # the later downloader cannot accidentally inherit path traversal content.
    clean = re.split(r"[\\/]", clean)[-1].strip(" .")
    return clean[:MAX_ATTACHMENT_FILE_NAME_CHARS]


def normalize_attachment_inventory(value: object) -> list[dict[str, str]]:
    if value is None or value == "":
        return []
    if not isinstance(value, (list, tuple)):
        raise CourseAttachmentError("attachment inventory must be a list")

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise CourseAttachmentError("attachment inventory item must be an object")
        provider_attachment_id = _clean_provider_id(
            raw.get("providerAttachmentId"),
            "provider attachment id",
        )
        identity = provider_attachment_id.lower()
        if identity in seen:
            continue
        if len(result) >= MAX_ATTACHMENTS_PER_ITEM:
            raise CourseAttachmentError("attachment inventory limit reached")
        seen.add(identity)
        result.append(
            {
                "providerAttachmentId": provider_attachment_id,
                "title": _clean_text(raw.get("title"), MAX_ATTACHMENT_TITLE_CHARS),
                "fileName": _clean_file_name(raw.get("fileName")),
                "assetType": _clean_text(raw.get("assetType"), MAX_ATTACHMENT_TYPE_CHARS),
            }
        )
    return result


def _connect(engine_module) -> sqlite3.Connection:
    list_courses(engine_module, limit=1)
    connection = sqlite3.connect(course_database_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS learning_attachment_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS course_item_attachment_context (
            course_item_id TEXT PRIMARY KEY REFERENCES course_items(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            provider_course_id TEXT NOT NULL,
            provider_lecture_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS course_item_attachments (
            id TEXT PRIMARY KEY,
            course_item_id TEXT NOT NULL REFERENCES course_items(id) ON DELETE CASCADE,
            provider_attachment_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            file_name TEXT NOT NULL DEFAULT '',
            asset_type TEXT NOT NULL DEFAULT '',
            position INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_item_id, provider_attachment_id)
        );

        CREATE INDEX IF NOT EXISTS idx_course_item_attachments_item_position
            ON course_item_attachments(course_item_id, position, id);
        CREATE INDEX IF NOT EXISTS idx_course_item_attachments_provider_id
            ON course_item_attachments(provider_attachment_id);
        """
    )
    row = connection.execute(
        "SELECT value FROM learning_attachment_meta WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO learning_attachment_meta(key, value) VALUES('schema_version', ?)",
            (str(ATTACHMENT_SCHEMA_VERSION),),
        )
    else:
        try:
            version = int(row["value"])
        except (TypeError, ValueError) as exc:
            connection.close()
            raise CourseAttachmentError("course attachment schema version is invalid") from exc
        if version != ATTACHMENT_SCHEMA_VERSION:
            connection.close()
            raise CourseAttachmentError(f"unsupported course attachment schema version: {version}")
    connection.commit()
    return connection


def ensure_course_attachments(engine_module) -> dict[str, int]:
    with closing(_connect(engine_module)) as connection:
        contexts = int(connection.execute("SELECT COUNT(*) FROM course_item_attachment_context").fetchone()[0])
        attachments = int(connection.execute("SELECT COUNT(*) FROM course_item_attachments").fetchone()[0])
    return {
        "schemaVersion": ATTACHMENT_SCHEMA_VERSION,
        "contexts": contexts,
        "attachments": attachments,
    }


def replace_course_item_attachments(
    engine_module,
    course_item_id: object,
    *,
    provider: object,
    provider_course_id: object,
    provider_lecture_id: object,
    attachments: object,
) -> dict[str, Any]:
    item = _clean_id(course_item_id, "course item")
    clean_provider = _clean_provider(provider)
    course_id = _clean_provider_id(provider_course_id, "provider course id")
    lecture_id = _clean_provider_id(provider_lecture_id, "provider lecture id")
    inventory = normalize_attachment_inventory(attachments)
    if not _UDEMY_COURSE_RE.fullmatch(course_id):
        raise CourseAttachmentError("invalid Udemy provider course id")
    if not _UDEMY_LECTURE_RE.fullmatch(lecture_id):
        raise CourseAttachmentError("invalid Udemy provider lecture id")
    if any(not _UDEMY_ASSET_RE.fullmatch(entry["providerAttachmentId"]) for entry in inventory):
        raise CourseAttachmentError("invalid Udemy provider attachment id")

    with closing(_connect(engine_module)) as connection:
        if connection.execute("SELECT 1 FROM course_items WHERE id=?", (item,)).fetchone() is None:
            raise CourseAttachmentError("course item not found")
        existing_rows = connection.execute(
            "SELECT id, provider_attachment_id FROM course_item_attachments WHERE course_item_id=?",
            (item,),
        ).fetchall()
        existing = {str(row["provider_attachment_id"]): str(row["id"]) for row in existing_rows}
        connection.execute(
            """
            INSERT INTO course_item_attachment_context(
                course_item_id, provider, provider_course_id, provider_lecture_id
            ) VALUES(?, ?, ?, ?)
            ON CONFLICT(course_item_id) DO UPDATE SET
                provider=excluded.provider,
                provider_course_id=excluded.provider_course_id,
                provider_lecture_id=excluded.provider_lecture_id,
                updated_at=CURRENT_TIMESTAMP
            """,
            (item, clean_provider, course_id, lecture_id),
        )
        connection.execute("DELETE FROM course_item_attachments WHERE course_item_id=?", (item,))
        rendered: list[dict[str, Any]] = []
        for position, entry in enumerate(inventory, start=1):
            attachment_id = existing.get(entry["providerAttachmentId"]) or uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO course_item_attachments(
                    id, course_item_id, provider_attachment_id, title, file_name, asset_type, position
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    item,
                    entry["providerAttachmentId"],
                    entry["title"],
                    entry["fileName"],
                    entry["assetType"],
                    position,
                ),
            )
            rendered.append(
                {
                    "id": attachment_id,
                    "courseItemId": item,
                    **entry,
                    "position": position,
                }
            )
        connection.commit()
    return {
        "courseItemId": item,
        "provider": clean_provider,
        "attachments": rendered,
    }


def list_course_item_attachments(
    engine_module,
    course_item_ids: Iterable[object],
) -> dict[str, list[dict[str, Any]]]:
    ids: list[str] = []
    seen: set[str] = set()
    for value in course_item_ids:
        clean = _clean_id(value, "course item")
        if clean not in seen:
            seen.add(clean)
            ids.append(clean)
        if len(ids) >= 10_000:
            break
    if not ids:
        return {}

    placeholders = ",".join("?" for _ in ids)
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            f"""
            SELECT id, course_item_id, provider_attachment_id, title, file_name, asset_type, position
            FROM course_item_attachments
            WHERE course_item_id IN ({placeholders})
            ORDER BY course_item_id, position, id
            """,
            ids,
        ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item_id = str(row["course_item_id"])
        result.setdefault(item_id, []).append(
            {
                "id": str(row["id"]),
                "courseItemId": item_id,
                "providerAttachmentId": str(row["provider_attachment_id"]),
                "title": str(row["title"]),
                "fileName": str(row["file_name"]),
                "assetType": str(row["asset_type"]),
                "position": int(row["position"]),
            }
        )
    return result


def attachment_download_context(engine_module, attachment_id: object) -> dict[str, Any]:
    clean = _clean_id(attachment_id, "attachment")
    with closing(_connect(engine_module)) as connection:
        row = connection.execute(
            """
            SELECT a.id, a.course_item_id, a.provider_attachment_id, a.title, a.file_name,
                   a.asset_type, c.provider, c.provider_course_id, c.provider_lecture_id
            FROM course_item_attachments a
            JOIN course_item_attachment_context c ON c.course_item_id=a.course_item_id
            WHERE a.id=?
            """,
            (clean,),
        ).fetchone()
    if row is None:
        raise CourseAttachmentError("course attachment not found")
    return {
        "id": str(row["id"]),
        "courseItemId": str(row["course_item_id"]),
        "provider": str(row["provider"]),
        "providerCourseId": str(row["provider_course_id"]),
        "providerLectureId": str(row["provider_lecture_id"]),
        "providerAttachmentId": str(row["provider_attachment_id"]),
        "title": str(row["title"]),
        "fileName": str(row["file_name"]),
        "assetType": str(row["asset_type"]),
    }


def enrich_course_item_attachments(
    engine_module,
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    values = [dict(item) for item in items if isinstance(item, dict)]
    mapping = list_course_item_attachments(
        engine_module,
        [item.get("id") for item in values if item.get("id")],
    )
    for item in values:
        attachments = mapping.get(str(item.get("id") or ""), [])
        if attachments:
            item["attachments"] = [dict(entry) for entry in attachments]
    return values
