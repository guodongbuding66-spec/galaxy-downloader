from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from typing import Any, Iterable

from course_workspace import course_database_path, list_courses

SUBTITLE_SCHEMA_VERSION = 1
MAX_SUBTITLE_TRACKS_PER_ITEM = 64
MAX_SUBTITLE_LANGUAGE_CHARS = 32
_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_SUBTITLE_KINDS = frozenset({"manual", "automatic"})


class CourseSubtitleError(RuntimeError):
    pass


def _clean_id(value: object, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(clean):
        raise CourseSubtitleError(f"invalid {label} id")
    return clean


def normalize_subtitle_tracks(value: object) -> list[dict[str, str]]:
    if value is None or value == "":
        return []
    if not isinstance(value, (list, tuple)):
        raise CourseSubtitleError("subtitle tracks must be a list")

    tracks: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise CourseSubtitleError("subtitle track must be an object")
        language = str(raw.get("language") or "").strip()
        if not _LANGUAGE_RE.fullmatch(language):
            raise CourseSubtitleError("invalid subtitle language")
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in _SUBTITLE_KINDS:
            raise CourseSubtitleError("invalid subtitle kind")
        key = (language.lower(), kind)
        if key in seen:
            continue
        if len(tracks) >= MAX_SUBTITLE_TRACKS_PER_ITEM:
            raise CourseSubtitleError("subtitle track limit reached")
        seen.add(key)
        tracks.append({"language": language, "kind": kind})
    return tracks


def _connect(engine_module) -> sqlite3.Connection:
    # course_workspace owns the base learning schema. Its public list call creates
    # and validates the base tables before this additive extension opens the DB.
    list_courses(engine_module, limit=1)
    connection = sqlite3.connect(course_database_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS learning_subtitle_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS course_item_subtitle_tracks (
            course_item_id TEXT NOT NULL REFERENCES course_items(id) ON DELETE CASCADE,
            language TEXT NOT NULL,
            kind TEXT NOT NULL,
            position INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(course_item_id, language, kind)
        );

        CREATE INDEX IF NOT EXISTS idx_course_item_subtitle_tracks_item_position
            ON course_item_subtitle_tracks(course_item_id, position, language, kind);
        """
    )
    row = connection.execute(
        "SELECT value FROM learning_subtitle_meta WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO learning_subtitle_meta(key, value) VALUES('schema_version', ?)",
            (str(SUBTITLE_SCHEMA_VERSION),),
        )
    else:
        try:
            version = int(row["value"])
        except (TypeError, ValueError) as exc:
            connection.close()
            raise CourseSubtitleError("course subtitle schema version is invalid") from exc
        if version != SUBTITLE_SCHEMA_VERSION:
            connection.close()
            raise CourseSubtitleError(f"unsupported course subtitle schema version: {version}")
    connection.commit()
    return connection


def ensure_course_subtitles(engine_module) -> dict[str, int]:
    with closing(_connect(engine_module)) as connection:
        tracks = int(connection.execute("SELECT COUNT(*) FROM course_item_subtitle_tracks").fetchone()[0])
    return {"schemaVersion": SUBTITLE_SCHEMA_VERSION, "tracks": tracks}


def set_course_item_subtitle_tracks(
    engine_module,
    course_item_id: object,
    tracks: object,
) -> dict[str, Any]:
    item = _clean_id(course_item_id, "course item")
    clean_tracks = normalize_subtitle_tracks(tracks)
    with closing(_connect(engine_module)) as connection:
        if connection.execute("SELECT 1 FROM course_items WHERE id=?", (item,)).fetchone() is None:
            raise CourseSubtitleError("course item not found")
        connection.execute("DELETE FROM course_item_subtitle_tracks WHERE course_item_id=?", (item,))
        for position, track in enumerate(clean_tracks, start=1):
            connection.execute(
                """
                INSERT INTO course_item_subtitle_tracks(course_item_id, language, kind, position)
                VALUES(?, ?, ?, ?)
                """,
                (item, track["language"], track["kind"], position),
            )
        connection.commit()
    return {"courseItemId": item, "subtitleTracks": clean_tracks}


def course_item_subtitle_tracks(
    engine_module,
    course_item_ids: Iterable[object],
) -> dict[str, list[dict[str, str]]]:
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
            SELECT course_item_id, language, kind
            FROM course_item_subtitle_tracks
            WHERE course_item_id IN ({placeholders})
            ORDER BY course_item_id, position, language, kind
            """,
            ids,
        ).fetchall()

    result: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        item_id = str(row["course_item_id"])
        result.setdefault(item_id, []).append(
            {"language": str(row["language"]), "kind": str(row["kind"])}
        )
    return result


def enrich_course_item_subtitles(
    engine_module,
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    values = [dict(item) for item in items if isinstance(item, dict)]
    mapping = course_item_subtitle_tracks(
        engine_module,
        [item.get("id") for item in values if item.get("id")],
    )
    for item in values:
        tracks = mapping.get(str(item.get("id") or ""), [])
        if tracks:
            item["subtitleTracks"] = [dict(track) for track in tracks]
    return values
