from __future__ import annotations

import html
import math
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from contextlib import closing, suppress
from pathlib import Path
from typing import Any

from media_library import list_media_items, resolve_media_item_path
from runtime_storage import state_dir as runtime_state_dir
from url_policy import validated_public_http_url

DATABASE_FILENAME = "learning.sqlite3"
SCHEMA_VERSION = 1
MAX_COURSES = 2_000
MAX_ITEMS_PER_COURSE = 10_000
MAX_NOTE_CHARS = 20_000
MAX_NOTES_PER_ITEM = 5_000
MAX_PROGRESS_SECONDS = 30 * 24 * 3600
BROWSERS = frozenset({"none", "edge", "chrome", "firefox", "brave"})
_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class CourseWorkspaceError(RuntimeError):
    pass


def course_database_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / DATABASE_FILENAME


def _connect(engine_module) -> sqlite3.Connection:
    connection = sqlite3.connect(course_database_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS learning_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS courses (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_url TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT 'generic',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS course_items (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            media_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            progress_seconds REAL NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_id, media_id)
        );
        CREATE TABLE IF NOT EXISTS course_notes (
            id TEXT PRIMARY KEY,
            course_item_id TEXT NOT NULL REFERENCES course_items(id) ON DELETE CASCADE,
            timestamp_seconds REAL NOT NULL DEFAULT 0,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_course_items_course
            ON course_items(course_id, position);
        CREATE INDEX IF NOT EXISTS idx_course_notes_item
            ON course_notes(course_item_id, timestamp_seconds, created_at);
        """
    )
    row = connection.execute("SELECT value FROM learning_meta WHERE key='schema_version'").fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO learning_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    else:
        try:
            version = int(row["value"])
        except (TypeError, ValueError) as exc:
            raise CourseWorkspaceError("Learning database schema version is invalid") from exc
        if version != SCHEMA_VERSION:
            raise CourseWorkspaceError(f"Unsupported learning database schema version: {version}")
    connection.commit()
    return connection


def _clean_id(value: object, label: str = "ID") -> str:
    clean = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(clean):
        raise CourseWorkspaceError(f"{label} 无效")
    return clean


def _clean_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _bounded_seconds(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return round(max(0.0, min(parsed, MAX_PROGRESS_SECONDS)), 3)


def create_course(
    engine_module,
    name: object,
    source_url: object = "",
    *,
    provider: object = "generic",
) -> dict[str, Any]:
    clean_name = _clean_text(name, 160)
    if not clean_name:
        raise CourseWorkspaceError("课程名称不能为空")
    clean_provider = _clean_text(provider, 40).lower() or "generic"
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", clean_provider):
        raise CourseWorkspaceError("课程 Provider 无效")
    clean_url = ""
    if str(source_url or "").strip():
        clean_url = validated_public_http_url(str(source_url))
    course_id = uuid.uuid4().hex
    with closing(_connect(engine_module)) as connection:
        count = int(connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0])
        if count >= MAX_COURSES:
            raise CourseWorkspaceError("课程数量超过安全上限")
        connection.execute(
            "INSERT INTO courses(id, name, source_url, provider) VALUES(?, ?, ?, ?)",
            (course_id, clean_name, clean_url, clean_provider),
        )
        connection.commit()
    return {"id": course_id, "name": clean_name, "sourceUrl": clean_url, "provider": clean_provider}


def rename_course(engine_module, course_id: object, name: object) -> None:
    clean_id = _clean_id(course_id, "课程 ID")
    clean_name = _clean_text(name, 160)
    if not clean_name:
        raise CourseWorkspaceError("课程名称不能为空")
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute(
            "UPDATE courses SET name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (clean_name, clean_id),
        )
        if cursor.rowcount != 1:
            raise CourseWorkspaceError("课程不存在")
        connection.commit()


def delete_course(engine_module, course_id: object) -> bool:
    clean_id = _clean_id(course_id, "课程 ID")
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute("DELETE FROM courses WHERE id=?", (clean_id,))
        connection.commit()
        return cursor.rowcount == 1


def list_courses(engine_module, *, limit: int = 500) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), MAX_COURSES))
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            """
            SELECT c.*, COUNT(ci.id) AS item_count,
                   COALESCE(SUM(ci.completed), 0) AS completed_count,
                   COALESCE(MAX(ci.progress_seconds), 0) AS last_progress
            FROM courses c
            LEFT JOIN course_items ci ON ci.course_id=c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC, c.created_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "sourceUrl": row["source_url"],
            "provider": row["provider"],
            "itemCount": int(row["item_count"] or 0),
            "completedCount": int(row["completed_count"] or 0),
            "lastProgressSeconds": float(row["last_progress"] or 0),
        }
        for row in rows
    ]


def add_media_to_course(engine_module, course_id: object, media_id: object) -> str:
    course = _clean_id(course_id, "课程 ID")
    media = _clean_id(media_id, "媒体 ID")
    if resolve_media_item_path(engine_module, media) is None:
        raise CourseWorkspaceError("媒体不存在或已离开 Galaxy 下载目录")
    with closing(_connect(engine_module)) as connection:
        if connection.execute("SELECT 1 FROM courses WHERE id=?", (course,)).fetchone() is None:
            raise CourseWorkspaceError("课程不存在")
        existing = connection.execute(
            "SELECT id FROM course_items WHERE course_id=? AND media_id=?",
            (course, media),
        ).fetchone()
        if existing is not None:
            return str(existing["id"])
        count = int(connection.execute("SELECT COUNT(*) FROM course_items WHERE course_id=?", (course,)).fetchone()[0])
        if count >= MAX_ITEMS_PER_COURSE:
            raise CourseWorkspaceError("课程条目数量超过安全上限")
        position = int(
            connection.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM course_items WHERE course_id=?",
                (course,),
            ).fetchone()[0]
        )
        item_id = uuid.uuid4().hex
        connection.execute(
            "INSERT INTO course_items(id, course_id, media_id, position) VALUES(?, ?, ?, ?)",
            (item_id, course, media, position),
        )
        connection.execute("UPDATE courses SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (course,))
        connection.commit()
    return item_id


def list_course_items(engine_module, course_id: object, *, limit: int = MAX_ITEMS_PER_COURSE) -> list[dict[str, Any]]:
    course = _clean_id(course_id, "课程 ID")
    safe_limit = max(1, min(int(limit), MAX_ITEMS_PER_COURSE))
    media_by_id: dict[str, dict[str, Any]] = {}
    offset = 0
    while offset < 10_000:
        batch = list_media_items(engine_module, limit=500, offset=offset)
        if not batch:
            break
        media_by_id.update({str(item["id"]): item for item in batch})
        if len(batch) < 500:
            break
        offset += 500
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT * FROM course_items WHERE course_id=? ORDER BY position, id LIMIT ?",
            (course, safe_limit),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        media = media_by_id.get(str(row["media_id"]), {})
        result.append(
            {
                "id": row["id"],
                "mediaId": row["media_id"],
                "position": int(row["position"]),
                "progressSeconds": float(row["progress_seconds"] or 0),
                "completed": bool(row["completed"]),
                "title": media.get("title") or media.get("fileName") or "Missing media",
                "durationSeconds": float(media.get("durationSeconds") or 0),
                "available": bool(media.get("available")),
                "mediaType": media.get("mediaType") or "",
            }
        )
    return result


def update_course_progress(
    engine_module,
    course_item_id: object,
    seconds: object,
    *,
    completed: bool | None = None,
) -> None:
    item = _clean_id(course_item_id, "课程条目 ID")
    progress = _bounded_seconds(seconds)
    with closing(_connect(engine_module)) as connection:
        if completed is None:
            cursor = connection.execute(
                "UPDATE course_items SET progress_seconds=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (progress, item),
            )
        else:
            cursor = connection.execute(
                "UPDATE course_items SET progress_seconds=?, completed=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (progress, 1 if completed else 0, item),
            )
        if cursor.rowcount != 1:
            raise CourseWorkspaceError("课程条目不存在")
        connection.execute(
            "UPDATE courses SET updated_at=CURRENT_TIMESTAMP WHERE id=(SELECT course_id FROM course_items WHERE id=?)",
            (item,),
        )
        connection.commit()


def add_timestamp_note(
    engine_module,
    course_item_id: object,
    timestamp_seconds: object,
    body: object,
) -> dict[str, Any]:
    item = _clean_id(course_item_id, "课程条目 ID")
    clean_body = str(body or "").strip()[:MAX_NOTE_CHARS]
    if not clean_body:
        raise CourseWorkspaceError("笔记不能为空")
    timestamp = _bounded_seconds(timestamp_seconds)
    note_id = uuid.uuid4().hex
    with closing(_connect(engine_module)) as connection:
        if connection.execute("SELECT 1 FROM course_items WHERE id=?", (item,)).fetchone() is None:
            raise CourseWorkspaceError("课程条目不存在")
        count = int(connection.execute("SELECT COUNT(*) FROM course_notes WHERE course_item_id=?", (item,)).fetchone()[0])
        if count >= MAX_NOTES_PER_ITEM:
            raise CourseWorkspaceError("单个课程条目的笔记数量超过安全上限")
        connection.execute(
            "INSERT INTO course_notes(id, course_item_id, timestamp_seconds, body) VALUES(?, ?, ?, ?)",
            (note_id, item, timestamp, clean_body),
        )
        connection.commit()
    return {"id": note_id, "timestampSeconds": timestamp, "body": clean_body}


def list_notes(engine_module, course_item_id: object, *, limit: int = 1_000) -> list[dict[str, Any]]:
    item = _clean_id(course_item_id, "课程条目 ID")
    safe_limit = max(1, min(int(limit), MAX_NOTES_PER_ITEM))
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT * FROM course_notes WHERE course_item_id=? ORDER BY timestamp_seconds, created_at LIMIT ?",
            (item, safe_limit),
        ).fetchall()
    return [
        {"id": row["id"], "timestampSeconds": float(row["timestamp_seconds"]), "body": row["body"]}
        for row in rows
    ]


def delete_note(engine_module, note_id: object) -> bool:
    note = _clean_id(note_id, "笔记 ID")
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute("DELETE FROM course_notes WHERE id=?", (note,))
        connection.commit()
        return cursor.rowcount == 1


def course_download_payload(source_url: object, *, browser: str = "none") -> dict[str, Any]:
    url = validated_public_http_url(str(source_url or ""))
    browser_id = str(browser or "none").strip().lower()
    if browser_id not in BROWSERS:
        raise CourseWorkspaceError("浏览器 Cookie 来源无效")
    return {
        "sourceUrl": url,
        "videoQuality": "best",
        "audioQuality": "best",
        "includeAudio": True,
        "includeSubtitle": True,
        "subtitleMode": "both",
        "splitChapters": False,
        "browser": browser_id,
        "collectionMode": "all",
        "displayTitle": "在线课程下载",
    }


def _data_root(engine_module) -> Path:
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir()) / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_learning_dir(engine_module, child: str) -> Path:
    root = _data_root(engine_module) / "learning"
    root.mkdir(parents=True, exist_ok=True)
    target = root / child
    if target.exists() and target.is_symlink():
        raise CourseWorkspaceError("Learning 目录不能是符号链接")
    target.mkdir(parents=True, exist_ok=True)
    return target


def create_local_player(engine_module, media_id: object, *, start_seconds: object = 0) -> Path:
    media = _clean_id(media_id, "媒体 ID")
    source = resolve_media_item_path(engine_module, media)
    if source is None:
        raise CourseWorkspaceError("媒体文件不可用")
    start = _bounded_seconds(start_seconds)
    target = _safe_learning_dir(engine_module, "players")
    page = target / f"{media}.html"
    tag = "audio" if source.suffix.lower() in {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus"} else "video"
    page.write_text(
        "<!doctype html><meta charset='utf-8'><title>Galaxy Course Player</title>"
        "<style>html,body{margin:0;background:#0b0d12;color:#f4f5f7;font-family:system-ui}main{max-width:1200px;margin:auto;padding:28px}video,audio{width:100%;max-height:78vh}</style>"
        f"<main><h2>{html.escape(source.name)}</h2><{tag} id='m' controls src='{html.escape(source.resolve().as_uri(), quote=True)}'></{tag}>"
        f"<script>const m=document.getElementById('m');m.addEventListener('loadedmetadata',()=>{{m.currentTime={start:.3f};}});</script></main>",
        encoding="utf-8",
    )
    return page


def _course_export_html(engine_module, course_id: str) -> str:
    course = next((item for item in list_courses(engine_module) if item["id"] == course_id), None)
    if course is None:
        raise CourseWorkspaceError("课程不存在")
    sections: list[str] = []
    for item in list_course_items(engine_module, course_id):
        notes = list_notes(engine_module, item["id"])
        note_html = "".join(
            f"<li><b>{note['timestampSeconds']:.1f}s</b> {html.escape(note['body'])}</li>" for note in notes
        ) or "<li>暂无笔记</li>"
        sections.append(
            f"<section><h2>{html.escape(str(item['title']))}</h2>"
            f"<p>进度：{item['progressSeconds']:.1f}s · {'已完成' if item['completed'] else '进行中'}</p>"
            f"<ul>{note_html}</ul></section>"
        )
    return (
        "<!doctype html><meta charset='utf-8'><title>Galaxy Course Notes</title>"
        "<style>body{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:40px;line-height:1.65;color:#111}h1{border-bottom:2px solid #222;padding-bottom:12px}section{break-inside:avoid;margin:28px 0}li{margin:8px 0}</style>"
        f"<h1>{html.escape(course['name'])}</h1>{''.join(sections)}"
    )


def _find_chromium() -> Path | None:
    candidates: list[Path] = []
    if os.name == "nt":
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            raw = os.environ.get(env_name)
            if not raw:
                continue
            base = Path(raw)
            candidates.extend((base / "Microsoft/Edge/Application/msedge.exe", base / "Google/Chrome/Application/chrome.exe"))
    for name in ("msedge", "google-chrome", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return next((path for path in candidates if path.is_file() and not path.is_symlink()), None)


def export_course_notes(engine_module, course_id: object) -> dict[str, str]:
    course = _clean_id(course_id, "课程 ID")
    target = _safe_learning_dir(engine_module, "exports")
    html_path = target / f"course-{course}.html"
    temporary = html_path.with_suffix(".html.tmp")
    temporary.write_text(_course_export_html(engine_module, course), encoding="utf-8")
    temporary.replace(html_path)
    result = {"html": str(html_path), "pdf": ""}
    browser = _find_chromium()
    if browser is None:
        return result
    pdf_path = target / f"course-{course}.pdf"
    with suppress(OSError, subprocess.SubprocessError):
        completed = subprocess.run(
            [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                f"--print-to-pdf={pdf_path}",
                html_path.resolve().as_uri(),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=False,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        if completed.returncode == 0 and pdf_path.is_file() and pdf_path.stat().st_size > 0:
            result["pdf"] = str(pdf_path)
    return result


def run_course_workspace_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        downloads.mkdir()
        state.mkdir()
        data.mkdir()
        media_file = downloads / "lesson.mp4"
        media_file.write_bytes(b"demo")
        media_id = "a" * 32

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return state

            @staticmethod
            def data_dir() -> Path:
                return data

            @staticmethod
            def default_download_dir() -> Path:
                return downloads

        with patch("course_workspace.validated_public_http_url", side_effect=lambda value: str(value)), patch(
            "course_workspace.resolve_media_item_path", return_value=media_file.resolve()
        ), patch(
            "course_workspace.list_media_items",
            return_value=[{
                "id": media_id,
                "title": "Lesson 1",
                "fileName": media_file.name,
                "mediaType": "video",
                "available": True,
                "durationSeconds": 100.0,
            }],
        ):
            course = create_course(Engine, "Demo Course", "https://example.com/course")
            item_id = add_media_to_course(Engine, course["id"], media_id)
            assert add_media_to_course(Engine, course["id"], media_id) == item_id
            update_course_progress(Engine, item_id, 12.5)
            note = add_timestamp_note(Engine, item_id, 12.5, "Important point")
            assert note["body"] == "Important point"
            items = list_course_items(Engine, course["id"])
            assert items[0]["progressSeconds"] == 12.5
            assert items[0]["title"] == "Lesson 1"
            assert list_notes(Engine, item_id)[0]["timestampSeconds"] == 12.5
            page = create_local_player(Engine, media_id, start_seconds=12.5)
            assert page.is_file() and "currentTime=12.500" in page.read_text(encoding="utf-8")
            with patch("course_workspace._find_chromium", return_value=None):
                exported = export_course_notes(Engine, course["id"])
                assert Path(exported["html"]).is_file() and exported["pdf"] == ""
            payload = course_download_payload("https://example.com/course", browser="edge")
            assert payload["collectionMode"] == "all" and payload["browser"] == "edge"
            assert delete_note(Engine, note["id"])
            assert delete_course(Engine, course["id"])
