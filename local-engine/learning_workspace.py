from __future__ import annotations

import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
import webbrowser
import zipfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

from media_library import list_media_items, resolve_media_item_path
from runtime_storage import state_dir as runtime_state_dir
from url_policy import validated_public_http_url

DATABASE_FILENAME = "learning.sqlite3"
MAX_NOTE_CHARS = 10_000
MAX_FLASHCARD_CHARS = 4_000
MAX_EPUB_BYTES = 300_000_000
MAX_EPUB_FILES = 20_000


class LearningWorkspaceError(RuntimeError):
    pass


def _db_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / DATABASE_FILENAME


def _connect(engine_module) -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_url TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS course_items (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            media_id TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            progress_seconds REAL NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            UNIQUE(course_id, media_id)
        );
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            course_item_id TEXT NOT NULL REFERENCES course_items(id) ON DELETE CASCADE,
            timestamp_seconds REAL NOT NULL DEFAULT 0,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS books (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            managed_epub TEXT NOT NULL UNIQUE,
            reader_html TEXT NOT NULL,
            progress_percent REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS flashcards (
            id TEXT PRIMARY KEY,
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            source_kind TEXT NOT NULL DEFAULT '',
            source_id TEXT NOT NULL DEFAULT '',
            repetitions INTEGER NOT NULL DEFAULT 0,
            interval_days REAL NOT NULL DEFAULT 0,
            ease REAL NOT NULL DEFAULT 2.5,
            due_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_course_items_course ON course_items(course_id, position);
        CREATE INDEX IF NOT EXISTS idx_notes_course_item ON notes(course_item_id, timestamp_seconds);
        CREATE INDEX IF NOT EXISTS idx_flashcards_due ON flashcards(due_at);
        """
    )
    return connection


def _clean_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _clean_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{16,64}", clean):
        raise LearningWorkspaceError("无效条目 ID")
    return clean


def create_course(engine_module, name: object, source_url: object = "") -> dict[str, Any]:
    clean_name = _clean_text(name, 160)
    if not clean_name:
        raise LearningWorkspaceError("课程名称不能为空")
    clean_url = ""
    if str(source_url or "").strip():
        clean_url = validated_public_http_url(str(source_url))
    course_id = uuid.uuid4().hex
    with closing(_connect(engine_module)) as connection:
        connection.execute("INSERT INTO courses(id, name, source_url) VALUES(?, ?, ?)", (course_id, clean_name, clean_url))
        connection.commit()
    return {"id": course_id, "name": clean_name, "sourceUrl": clean_url}


def list_courses(engine_module) -> list[dict[str, Any]]:
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT c.*, COUNT(ci.id) AS item_count, COALESCE(SUM(ci.completed),0) AS completed_count "
            "FROM courses c LEFT JOIN course_items ci ON ci.course_id=c.id "
            "GROUP BY c.id ORDER BY c.created_at DESC"
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "sourceUrl": row["source_url"],
            "itemCount": int(row["item_count"] or 0),
            "completedCount": int(row["completed_count"] or 0),
        }
        for row in rows
    ]


def add_media_to_course(engine_module, course_id: object, media_id: object) -> str:
    course = _clean_id(course_id)
    media = _clean_id(media_id)
    if resolve_media_item_path(engine_module, media) is None:
        raise LearningWorkspaceError("媒体不存在或已离开 Galaxy 下载目录")
    with closing(_connect(engine_module)) as connection:
        exists = connection.execute("SELECT 1 FROM courses WHERE id=?", (course,)).fetchone()
        if exists is None:
            raise LearningWorkspaceError("课程不存在")
        row = connection.execute("SELECT COALESCE(MAX(position),0)+1 AS next FROM course_items WHERE course_id=?", (course,)).fetchone()
        item_id = uuid.uuid4().hex
        try:
            connection.execute(
                "INSERT INTO course_items(id, course_id, media_id, position) VALUES(?, ?, ?, ?)",
                (item_id, course, media, int(row["next"] or 1)),
            )
            connection.commit()
            return item_id
        except sqlite3.IntegrityError:
            existing = connection.execute(
                "SELECT id FROM course_items WHERE course_id=? AND media_id=?", (course, media)
            ).fetchone()
            return str(existing["id"])


def list_course_items(engine_module, course_id: object) -> list[dict[str, Any]]:
    course = _clean_id(course_id)
    media_by_id = {str(item["id"]): item for item in list_media_items(engine_module, limit=500)}
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT * FROM course_items WHERE course_id=? ORDER BY position, id", (course,)
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


def update_course_progress(engine_module, course_item_id: object, seconds: object, *, completed: bool | None = None) -> None:
    item = _clean_id(course_item_id)
    try:
        progress = max(0.0, min(float(seconds), 30 * 24 * 3600))
    except (TypeError, ValueError):
        progress = 0.0
    with closing(_connect(engine_module)) as connection:
        if completed is None:
            connection.execute("UPDATE course_items SET progress_seconds=? WHERE id=?", (progress, item))
        else:
            connection.execute(
                "UPDATE course_items SET progress_seconds=?, completed=? WHERE id=?",
                (progress, 1 if completed else 0, item),
            )
        connection.commit()


def add_timestamp_note(engine_module, course_item_id: object, timestamp_seconds: object, body: object) -> dict[str, Any]:
    item = _clean_id(course_item_id)
    clean_body = str(body or "").strip()[:MAX_NOTE_CHARS]
    if not clean_body:
        raise LearningWorkspaceError("笔记不能为空")
    try:
        timestamp = max(0.0, min(float(timestamp_seconds), 30 * 24 * 3600))
    except (TypeError, ValueError):
        timestamp = 0.0
    note_id = uuid.uuid4().hex
    with closing(_connect(engine_module)) as connection:
        if connection.execute("SELECT 1 FROM course_items WHERE id=?", (item,)).fetchone() is None:
            raise LearningWorkspaceError("课程媒体不存在")
        connection.execute(
            "INSERT INTO notes(id, course_item_id, timestamp_seconds, body) VALUES(?, ?, ?, ?)",
            (note_id, item, timestamp, clean_body),
        )
        connection.commit()
    return {"id": note_id, "timestampSeconds": timestamp, "body": clean_body}


def list_notes(engine_module, course_item_id: object) -> list[dict[str, Any]]:
    item = _clean_id(course_item_id)
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT * FROM notes WHERE course_item_id=? ORDER BY timestamp_seconds, created_at", (item,)
        ).fetchall()
    return [
        {"id": row["id"], "timestampSeconds": float(row["timestamp_seconds"]), "body": row["body"]}
        for row in rows
    ]


def course_download_payload(source_url: object, *, browser: str = "none") -> dict[str, Any]:
    url = validated_public_http_url(str(source_url or ""))
    return {
        "sourceUrl": url,
        "videoQuality": "best",
        "audioQuality": "best",
        "includeAudio": True,
        "includeSubtitle": True,
        "subtitleMode": "both",
        "splitChapters": False,
        "browser": str(browser or "none"),
        "collectionMode": "all",
        "displayTitle": "在线课程下载",
    }


def _find_chromium() -> Path | None:
    candidates: list[Path] = []
    if sys_platform() == "win32":
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = Path(os.environ.get(env_name, ""))
            if not str(base):
                continue
            candidates.extend(
                (
                    base / "Microsoft/Edge/Application/msedge.exe",
                    base / "Google/Chrome/Application/chrome.exe",
                )
            )
    for name in ("msedge", "google-chrome", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return next((path for path in candidates if path.is_file()), None)


def sys_platform() -> str:
    import sys
    return sys.platform


def _course_export_html(engine_module, course_id: str) -> str:
    courses = {item["id"]: item for item in list_courses(engine_module)}
    course = courses.get(course_id)
    if course is None:
        raise LearningWorkspaceError("课程不存在")
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
        "<style>body{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:40px;line-height:1.65;color:#111}"
        "h1{border-bottom:2px solid #222;padding-bottom:12px}section{break-inside:avoid;margin:28px 0}li{margin:8px 0}</style>"
        f"<h1>{html.escape(course['name'])}</h1>{''.join(sections)}"
    )


def export_course_notes(engine_module, course_id: object) -> dict[str, str]:
    course = _clean_id(course_id)
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir())
    target = root / "learning" / "exports"
    target.mkdir(parents=True, exist_ok=True)
    html_path = target / f"course-{course}.html"
    html_path.write_text(_course_export_html(engine_module, course), encoding="utf-8")
    result = {"html": str(html_path), "pdf": ""}
    browser = _find_chromium()
    if browser is not None:
        pdf_path = target / f"course-{course}.pdf"
        command = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, timeout=60, check=False)
            if completed.returncode == 0 and pdf_path.is_file() and pdf_path.stat().st_size > 0:
                result["pdf"] = str(pdf_path)
        except (OSError, subprocess.SubprocessError):
            pass
    return result


def create_local_player(engine_module, media_id: object, *, start_seconds: object = 0) -> Path:
    media = _clean_id(media_id)
    source = resolve_media_item_path(engine_module, media)
    if source is None:
        raise LearningWorkspaceError("媒体文件不可用")
    try:
        start = max(0.0, min(float(start_seconds), 30 * 24 * 3600))
    except (TypeError, ValueError):
        start = 0.0
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir())
    target = root / "learning" / "players"
    target.mkdir(parents=True, exist_ok=True)
    page = target / f"{media}.html"
    media_url = source.resolve().as_uri()
    page.write_text(
        "<!doctype html><meta charset='utf-8'><title>Galaxy Course Player</title>"
        "<style>html,body{margin:0;background:#080c14;color:#fff;font-family:system-ui}main{max-width:1200px;margin:auto;padding:28px}video,audio{width:100%;max-height:75vh}</style>"
        f"<main><h2>{html.escape(source.name)}</h2><video id='m' controls src='{html.escape(media_url, quote=True)}'></video>"
        f"<script>const m=document.getElementById('m');m.addEventListener('loadedmetadata',()=>{{m.currentTime={start:.3f};}});</script></main>",
        encoding="utf-8",
    )
    return page


def open_local_player(engine_module, media_id: object, *, start_seconds: object = 0) -> Path:
    page = create_local_player(engine_module, media_id, start_seconds=start_seconds)
    webbrowser.open(page.resolve().as_uri())
    return page


def _safe_epub_member(name: str) -> Path:
    normalized = name.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise LearningWorkspaceError("EPUB 包含不安全路径")
    return path


def _epub_spine(extract_root: Path) -> list[Path]:
    container = extract_root / "META-INF" / "container.xml"
    try:
        root = ElementTree.parse(container).getroot()
        rootfile = next(element for element in root.iter() if element.tag.endswith("rootfile"))
        opf_rel = rootfile.attrib["full-path"]
        opf = extract_root / _safe_epub_member(opf_rel)
        package = ElementTree.parse(opf).getroot()
        manifest: dict[str, str] = {}
        for element in package.iter():
            if element.tag.endswith("item") and element.attrib.get("id") and element.attrib.get("href"):
                manifest[element.attrib["id"]] = element.attrib["href"]
        spine: list[Path] = []
        for element in package.iter():
            if not element.tag.endswith("itemref"):
                continue
            href = manifest.get(element.attrib.get("idref", ""))
            if href:
                spine.append((opf.parent / _safe_epub_member(href)).resolve(strict=False))
        return [path for path in spine if path.is_file()]
    except Exception:
        return sorted(path for path in extract_root.rglob("*") if path.suffix.lower() in {".xhtml", ".html", ".htm"})


def import_epub(engine_module, source_file: Path) -> dict[str, Any]:
    source = Path(source_file).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".epub":
        raise LearningWorkspaceError("请选择有效 EPUB 文件")
    if source.stat().st_size > MAX_EPUB_BYTES:
        raise LearningWorkspaceError("EPUB 超过 300 MB 上限")
    book_id = uuid.uuid4().hex
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir())
    book_root = root / "learning" / "books" / book_id
    extract_root = book_root / "content"
    extract_root.mkdir(parents=True, exist_ok=True)
    managed_epub = book_root / "book.epub"
    shutil.copy2(source, managed_epub)
    try:
        with zipfile.ZipFile(managed_epub) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_EPUB_FILES:
                raise LearningWorkspaceError("EPUB 文件数量过多")
            total = sum(max(0, info.file_size) for info in infos)
            if total > MAX_EPUB_BYTES:
                raise LearningWorkspaceError("EPUB 解压后超过 300 MB 上限")
            for info in infos:
                rel = _safe_epub_member(info.filename)
                destination = extract_root / rel
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, destination.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
    except zipfile.BadZipFile as exc:
        raise LearningWorkspaceError("EPUB 文件损坏") from exc

    chapters = _epub_spine(extract_root)
    bodies: list[str] = []
    for chapter in chapters[:5000]:
        text = chapter.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"<body[^>]*>(.*?)</body>", text, flags=re.IGNORECASE | re.DOTALL)
        body = match.group(1) if match else text
        # Rebase relative resources to extracted local files.
        base_uri = chapter.parent.resolve().as_uri() + "/"
        bodies.append(f"<section data-base='{html.escape(base_uri, quote=True)}'>{body}</section>")
    reader = book_root / "reader.html"
    reader.write_text(
        "<!doctype html><meta charset='utf-8'><title>Galaxy EPUB Reader</title>"
        "<style>body{max-width:850px;margin:40px auto;padding:0 24px;font:18px/1.8 system-ui,'Microsoft YaHei',sans-serif;color:#222}img{max-width:100%}section{margin:0 0 3em}</style>"
        + "".join(bodies),
        encoding="utf-8",
    )
    title = _clean_text(source.stem, 200) or "EPUB"
    with closing(_connect(engine_module)) as connection:
        connection.execute(
            "INSERT INTO books(id, title, managed_epub, reader_html) VALUES(?, ?, ?, ?)",
            (book_id, title, str(managed_epub), str(reader)),
        )
        connection.commit()
    return {"id": book_id, "title": title, "readerHtml": str(reader), "progressPercent": 0.0}


def list_books(engine_module) -> list[dict[str, Any]]:
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute("SELECT * FROM books ORDER BY created_at DESC").fetchall()
    return [
        {"id": row["id"], "title": row["title"], "readerHtml": row["reader_html"], "progressPercent": float(row["progress_percent"] or 0)}
        for row in rows
    ]


def update_book_progress(engine_module, book_id: object, percent: object) -> None:
    clean = _clean_id(book_id)
    try:
        value = max(0.0, min(float(percent), 100.0))
    except (TypeError, ValueError):
        value = 0.0
    with closing(_connect(engine_module)) as connection:
        connection.execute("UPDATE books SET progress_percent=? WHERE id=?", (value, clean))
        connection.commit()


def create_flashcard(engine_module, front: object, back: object, *, source_kind: object = "", source_id: object = "") -> dict[str, Any]:
    clean_front = str(front or "").strip()[:MAX_FLASHCARD_CHARS]
    clean_back = str(back or "").strip()[:MAX_FLASHCARD_CHARS]
    if not clean_front or not clean_back:
        raise LearningWorkspaceError("卡片正反面不能为空")
    card_id = uuid.uuid4().hex
    due = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with closing(_connect(engine_module)) as connection:
        connection.execute(
            "INSERT INTO flashcards(id, front, back, source_kind, source_id, due_at) VALUES(?, ?, ?, ?, ?, ?)",
            (card_id, clean_front, clean_back, _clean_text(source_kind, 32), _clean_text(source_id, 80), due),
        )
        connection.commit()
    return {"id": card_id, "front": clean_front, "back": clean_back, "dueAt": due}


def due_flashcards(engine_module, *, limit: int = 50) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT * FROM flashcards WHERE due_at<=? ORDER BY due_at LIMIT ?", (now, max(1, min(int(limit), 200)))
        ).fetchall()
    return [dict(row) for row in rows]


def review_flashcard(engine_module, card_id: object, rating: object) -> dict[str, Any]:
    clean = _clean_id(card_id)
    try:
        quality = max(0, min(int(rating), 5))
    except (TypeError, ValueError):
        quality = 0
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT * FROM flashcards WHERE id=?", (clean,)).fetchone()
        if row is None:
            raise LearningWorkspaceError("卡片不存在")
        repetitions = int(row["repetitions"] or 0)
        interval = float(row["interval_days"] or 0)
        ease = float(row["ease"] or 2.5)
        if quality < 3:
            repetitions = 0
            interval = 1.0
        else:
            repetitions += 1
            if repetitions == 1:
                interval = 1.0
            elif repetitions == 2:
                interval = 6.0
            else:
                interval = max(1.0, interval * ease)
            ease = max(1.3, ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
        due = (datetime.now(timezone.utc) + timedelta(days=interval)).replace(microsecond=0).isoformat()
        connection.execute(
            "UPDATE flashcards SET repetitions=?, interval_days=?, ease=?, due_at=? WHERE id=?",
            (repetitions, interval, ease, due, clean),
        )
        connection.commit()
    return {"id": clean, "repetitions": repetitions, "intervalDays": interval, "ease": ease, "dueAt": due}


def music_library(engine_module) -> list[dict[str, Any]]:
    return [item for item in list_media_items(engine_module, limit=500, media_type="audio") if item.get("available")]


def run_learning_workspace_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                target = root / "state"
                target.mkdir(parents=True, exist_ok=True)
                return target

            @staticmethod
            def data_dir() -> Path:
                target = root / "data"
                target.mkdir(parents=True, exist_ok=True)
                return target

        course = create_course(Engine, "Demo")
        assert list_courses(Engine)[0]["id"] == course["id"]
        card = create_flashcard(Engine, "Q", "A")
        assert due_flashcards(Engine)[0]["id"] == card["id"]
        reviewed = review_flashcard(Engine, card["id"], 5)
        assert reviewed["repetitions"] == 1
        assert _safe_epub_member("OPS/chapter.xhtml") == Path("OPS/chapter.xhtml")
        try:
            _safe_epub_member("../escape")
        except LearningWorkspaceError:
            pass
        else:
            raise AssertionError("unsafe EPUB member accepted")
