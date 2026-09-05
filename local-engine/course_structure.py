from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import closing
from typing import Any, Iterable

from course_workspace import course_database_path, list_courses

STRUCTURE_SCHEMA_VERSION = 1
MAX_SECTIONS_PER_COURSE = 2_000
MAX_PROVIDER_ID_CHARS = 160
MAX_SECTION_TITLE_CHARS = 240
MAX_ITEM_TITLE_CHARS = 300
_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


class CourseStructureError(RuntimeError):
    pass


def _clean_id(value: object, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(clean):
        raise CourseStructureError(f"invalid {label} id")
    return clean


def _clean_text(value: object, limit: int, label: str, *, required: bool = False) -> str:
    clean = " ".join(str(value or "").split()).strip()[:limit]
    if required and not clean:
        raise CourseStructureError(f"{label} is required")
    return clean


def _clean_provider_id(value: object, label: str, *, required: bool = False) -> str:
    clean = str(value or "").strip()[:MAX_PROVIDER_ID_CHARS]
    if not clean:
        if required:
            raise CourseStructureError(f"{label} is required")
        return ""
    if not _PROVIDER_ID_RE.fullmatch(clean):
        raise CourseStructureError(f"invalid {label}")
    return clean


def _bounded_position(value: object, *, high: int = 100_000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise CourseStructureError("position must be an integer") from exc
    if parsed < 1 or parsed > high:
        raise CourseStructureError(f"position must be between 1 and {high}")
    return parsed


def _ensure_base_schema(engine_module) -> None:
    # course_workspace remains the authority for the base learning schema. Calling
    # its public list API creates/validates the v1 tables before this extension
    # opens the same database.
    list_courses(engine_module, limit=1)


def _connect(engine_module) -> sqlite3.Connection:
    _ensure_base_schema(engine_module)
    connection = sqlite3.connect(course_database_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS learning_structure_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS course_sections (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            provider_section_id TEXT NOT NULL,
            title TEXT NOT NULL,
            position INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_id, provider_section_id)
        );

        CREATE TABLE IF NOT EXISTS course_item_metadata (
            course_item_id TEXT PRIMARY KEY REFERENCES course_items(id) ON DELETE CASCADE,
            section_id TEXT REFERENCES course_sections(id) ON DELETE SET NULL,
            provider_item_id TEXT NOT NULL DEFAULT '',
            provider_title TEXT NOT NULL DEFAULT '',
            provider_position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_course_sections_course_position
            ON course_sections(course_id, position, id);
        CREATE INDEX IF NOT EXISTS idx_course_item_metadata_section
            ON course_item_metadata(section_id, provider_position, course_item_id);
        CREATE INDEX IF NOT EXISTS idx_course_item_metadata_provider
            ON course_item_metadata(provider_item_id);
        """
    )
    row = connection.execute(
        "SELECT value FROM learning_structure_meta WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO learning_structure_meta(key, value) VALUES('schema_version', ?)",
            (str(STRUCTURE_SCHEMA_VERSION),),
        )
    else:
        try:
            version = int(row["value"])
        except (TypeError, ValueError) as exc:
            connection.close()
            raise CourseStructureError("course structure schema version is invalid") from exc
        if version != STRUCTURE_SCHEMA_VERSION:
            connection.close()
            raise CourseStructureError(f"unsupported course structure schema version: {version}")
    connection.commit()
    return connection


def ensure_course_structure(engine_module) -> dict[str, int]:
    with closing(_connect(engine_module)) as connection:
        sections = int(connection.execute("SELECT COUNT(*) FROM course_sections").fetchone()[0])
        metadata = int(connection.execute("SELECT COUNT(*) FROM course_item_metadata").fetchone()[0])
    return {
        "schemaVersion": STRUCTURE_SCHEMA_VERSION,
        "sections": sections,
        "itemMetadata": metadata,
    }


def upsert_course_section(
    engine_module,
    course_id: object,
    *,
    provider_section_id: object,
    title: object,
    position: object,
) -> dict[str, Any]:
    course = _clean_id(course_id, "course")
    provider_id = _clean_provider_id(provider_section_id, "provider section id", required=True)
    clean_title = _clean_text(title, MAX_SECTION_TITLE_CHARS, "section title", required=True)
    clean_position = _bounded_position(position)

    with closing(_connect(engine_module)) as connection:
        if connection.execute("SELECT 1 FROM courses WHERE id=?", (course,)).fetchone() is None:
            raise CourseStructureError("course not found")
        existing = connection.execute(
            "SELECT id FROM course_sections WHERE course_id=? AND provider_section_id=?",
            (course, provider_id),
        ).fetchone()
        if existing is None:
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM course_sections WHERE course_id=?",
                    (course,),
                ).fetchone()[0]
            )
            if count >= MAX_SECTIONS_PER_COURSE:
                raise CourseStructureError("course section limit reached")
            section_id = uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO course_sections(id, course_id, provider_section_id, title, position)
                VALUES(?, ?, ?, ?, ?)
                """,
                (section_id, course, provider_id, clean_title, clean_position),
            )
        else:
            section_id = str(existing["id"])
            connection.execute(
                """
                UPDATE course_sections
                SET title=?, position=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (clean_title, clean_position, section_id),
            )
        connection.commit()
    return {
        "id": section_id,
        "courseId": course,
        "providerSectionId": provider_id,
        "title": clean_title,
        "position": clean_position,
    }


def list_course_sections(engine_module, course_id: object) -> list[dict[str, Any]]:
    course = _clean_id(course_id, "course")
    with closing(_connect(engine_module)) as connection:
        if connection.execute("SELECT 1 FROM courses WHERE id=?", (course,)).fetchone() is None:
            raise CourseStructureError("course not found")
        rows = connection.execute(
            """
            SELECT id, course_id, provider_section_id, title, position
            FROM course_sections
            WHERE course_id=?
            ORDER BY position, id
            """,
            (course,),
        ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "courseId": str(row["course_id"]),
            "providerSectionId": str(row["provider_section_id"]),
            "title": str(row["title"]),
            "position": int(row["position"]),
        }
        for row in rows
    ]


def set_course_item_metadata(
    engine_module,
    course_item_id: object,
    *,
    section_id: object = "",
    provider_item_id: object = "",
    provider_title: object = "",
    provider_position: object = 0,
) -> dict[str, Any]:
    item = _clean_id(course_item_id, "course item")
    clean_section = ""
    if str(section_id or "").strip():
        clean_section = _clean_id(section_id, "section")
    clean_provider_id = _clean_provider_id(provider_item_id, "provider item id")
    clean_title = _clean_text(provider_title, MAX_ITEM_TITLE_CHARS, "provider title")
    try:
        clean_position = int(provider_position or 0)
    except (TypeError, ValueError) as exc:
        raise CourseStructureError("provider position must be an integer") from exc
    if clean_position < 0 or clean_position > 100_000:
        raise CourseStructureError("provider position must be between 0 and 100000")

    with closing(_connect(engine_module)) as connection:
        item_row = connection.execute(
            "SELECT course_id FROM course_items WHERE id=?",
            (item,),
        ).fetchone()
        if item_row is None:
            raise CourseStructureError("course item not found")
        course_id = str(item_row["course_id"])
        if clean_section:
            section = connection.execute(
                "SELECT course_id FROM course_sections WHERE id=?",
                (clean_section,),
            ).fetchone()
            if section is None:
                raise CourseStructureError("course section not found")
            if str(section["course_id"]) != course_id:
                raise CourseStructureError("course section belongs to a different course")
        connection.execute(
            """
            INSERT INTO course_item_metadata(
                course_item_id, section_id, provider_item_id, provider_title, provider_position
            ) VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(course_item_id) DO UPDATE SET
                section_id=excluded.section_id,
                provider_item_id=excluded.provider_item_id,
                provider_title=excluded.provider_title,
                provider_position=excluded.provider_position,
                updated_at=CURRENT_TIMESTAMP
            """,
            (item, clean_section or None, clean_provider_id, clean_title, clean_position),
        )
        connection.commit()
    return {
        "courseItemId": item,
        "courseId": course_id,
        "sectionId": clean_section,
        "providerItemId": clean_provider_id,
        "providerTitle": clean_title,
        "providerPosition": clean_position,
    }


def course_item_metadata(engine_module, course_item_ids: Iterable[object]) -> dict[str, dict[str, Any]]:
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
            SELECT m.course_item_id, m.section_id, m.provider_item_id,
                   m.provider_title, m.provider_position,
                   s.title AS section_title, s.position AS section_position,
                   s.provider_section_id
            FROM course_item_metadata m
            LEFT JOIN course_sections s ON s.id=m.section_id
            WHERE m.course_item_id IN ({placeholders})
            """,
            ids,
        ).fetchall()
    return {
        str(row["course_item_id"]): {
            "sectionId": str(row["section_id"] or ""),
            "sectionTitle": str(row["section_title"] or ""),
            "sectionPosition": int(row["section_position"] or 0),
            "providerSectionId": str(row["provider_section_id"] or ""),
            "providerItemId": str(row["provider_item_id"] or ""),
            "providerTitle": str(row["provider_title"] or ""),
            "providerPosition": int(row["provider_position"] or 0),
        }
        for row in rows
    }


def enrich_course_items(engine_module, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [dict(item) for item in items if isinstance(item, dict)]
    metadata = course_item_metadata(
        engine_module,
        [item.get("id") for item in values if item.get("id")],
    )
    for item in values:
        extra = metadata.get(str(item.get("id") or ""), {})
        item.update(extra)
        provider_title = str(extra.get("providerTitle") or "").strip()
        if provider_title:
            item["title"] = provider_title
    return values
