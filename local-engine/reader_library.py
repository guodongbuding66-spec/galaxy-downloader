from __future__ import annotations

import html
import json
import os
import re
import shutil
import sqlite3
import uuid
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any

from learning_workspace import list_courses
from runtime_storage import state_dir as runtime_state_dir

DATABASE_FILENAME = "reader-library.sqlite3"
MAX_BOOK_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 30_000
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
SUPPORTED_BOOKS = {".pdf", ".epub", ".cbz"}
SUPPORTED_ATTACHMENTS = SUPPORTED_BOOKS | {".txt", ".md", ".srt", ".vtt"}


class ReaderLibraryError(RuntimeError):
    pass


def _data_root(engine_module) -> Path:
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir())
    target = root / "reader"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _db_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / DATABASE_FILENAME


def _connect(engine_module) -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS books (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          kind TEXT NOT NULL,
          source_name TEXT NOT NULL,
          managed_path TEXT NOT NULL UNIQUE,
          reader_path TEXT NOT NULL,
          progress REAL NOT NULL DEFAULT 0,
          focus_mode INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS bookmarks (
          id TEXT PRIMARY KEY,
          book_id TEXT NOT NULL,
          locator TEXT NOT NULL,
          label TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS highlights (
          id TEXT PRIMARY KEY,
          book_id TEXT NOT NULL,
          locator TEXT NOT NULL,
          quote TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS course_attachments (
          id TEXT PRIMARY KEY,
          course_id TEXT NOT NULL,
          name TEXT NOT NULL,
          managed_path TEXT NOT NULL UNIQUE,
          kind TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_bookmarks_book ON bookmarks(book_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_highlights_book ON highlights(book_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_attachments_course ON course_attachments(course_id, created_at);
        """
    )
    return connection


def _source_file(value: object, allowed: set[str]) -> Path:
    try:
        path = Path(str(value or "")).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ReaderLibraryError("文件不存在") from exc
    if not path.is_file() or path.is_symlink() or path.suffix.lower() not in allowed:
        raise ReaderLibraryError("文件类型不受支持")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ReaderLibraryError(str(exc)) from exc
    if size <= 0 or size > MAX_BOOK_BYTES:
        raise ReaderLibraryError("文件为空或超过 2 GB")
    return path


def _safe_member(name: str) -> Path:
    normalized = name.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ReaderLibraryError("压缩包包含不安全路径")
    return path


def _extract_archive(source: Path, destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=False)
    files: list[Path] = []
    total = 0
    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_FILES:
                raise ReaderLibraryError("电子书文件数超过安全上限")
            for info in infos:
                if info.is_dir():
                    continue
                relative = _safe_member(info.filename)
                total += max(0, int(info.file_size))
                if total > MAX_ARCHIVE_BYTES:
                    raise ReaderLibraryError("电子书解压大小超过安全上限")
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
                files.append(target)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return files


def _epub_pages(files: list[Path]) -> list[Path]:
    return [path for path in files if path.suffix.lower() in {".xhtml", ".html", ".htm"}]


def _cbz_pages(files: list[Path]) -> list[Path]:
    return sorted(path for path in files if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"})


def _reader_html(kind: str, managed: Path, extracted: Path | None, files: list[Path]) -> str:
    if kind == "pdf":
        body = f"<iframe src='{html.escape(managed.resolve().as_uri(), quote=True)}'></iframe>"
    elif kind == "cbz" and extracted is not None:
        images = _cbz_pages(files)[:5000]
        body = "".join(f"<img loading='lazy' src='{html.escape(path.resolve().as_uri(), quote=True)}'>" for path in images)
    else:
        pages = _epub_pages(files)[:2000]
        links = "".join(f"<li><a target='reader' href='{html.escape(path.resolve().as_uri(), quote=True)}'>{html.escape(path.name)}</a></li>" for path in pages)
        initial = html.escape(pages[0].resolve().as_uri(), quote=True) if pages else "about:blank"
        body = f"<aside><ol>{links}</ol></aside><iframe name='reader' src='{initial}'></iframe>"
    return (
        "<!doctype html><meta charset='utf-8'><title>Galaxy Reader</title>"
        "<style>html,body{height:100%;margin:0;background:#f3efe4;color:#191919;font:16px system-ui}"
        "body{display:flex}aside{width:260px;overflow:auto;padding:20px;background:#e9e2d3}"
        "iframe{border:0;flex:1;width:100%;height:100%}img{display:block;max-width:96%;margin:18px auto;box-shadow:0 2px 14px #0002}"
        "a{color:#374151;text-decoration:none}li{margin:8px 0}</style>" + body
    )


def import_book(engine_module, source_file: object, *, title: object = "") -> dict[str, Any]:
    source = _source_file(source_file, SUPPORTED_BOOKS)
    book_id = uuid.uuid4().hex
    root = _data_root(engine_module) / "books" / book_id
    root.mkdir(parents=True, exist_ok=False)
    managed = root / f"book{source.suffix.lower()}"
    shutil.copy2(source, managed)
    extracted: Path | None = None
    files: list[Path] = []
    kind = source.suffix.lower().lstrip(".")
    if kind in {"epub", "cbz"}:
        extracted = root / "content"
        files = _extract_archive(managed, extracted)
    reader = root / "reader.html"
    reader.write_text(_reader_html(kind, managed, extracted, files), encoding="utf-8")
    clean_title = " ".join(str(title or source.stem).split()).strip()[:240] or source.stem[:240]
    with closing(_connect(engine_module)) as connection:
        connection.execute(
            "INSERT INTO books(id,title,kind,source_name,managed_path,reader_path) VALUES(?,?,?,?,?,?)",
            (book_id, clean_title, kind, source.name[:240], str(managed), str(reader)),
        )
        connection.commit()
    return {"id": book_id, "title": clean_title, "kind": kind, "readerPath": str(reader), "progress": 0.0, "focusMode": False}


def list_books_v2(engine_module) -> list[dict[str, Any]]:
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute("SELECT * FROM books ORDER BY created_at DESC").fetchall()
    return [
        {"id": str(row["id"]), "title": str(row["title"]), "kind": str(row["kind"]), "progress": float(row["progress"]), "focusMode": bool(row["focus_mode"]), "readerPath": str(row["reader_path"])}
        for row in rows
    ]


def update_reading_state(engine_module, book_id: object, *, progress: object | None = None, focus_mode: bool | None = None) -> None:
    clean_id = str(book_id or "").strip().lower()
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT progress, focus_mode FROM books WHERE id=?", (clean_id,)).fetchone()
        if row is None:
            raise ReaderLibraryError("书籍不存在")
        try:
            new_progress = float(row["progress"]) if progress is None else max(0.0, min(float(progress), 100.0))
        except (TypeError, ValueError):
            new_progress = float(row["progress"])
        new_focus = bool(row["focus_mode"]) if focus_mode is None else bool(focus_mode)
        connection.execute("UPDATE books SET progress=?, focus_mode=? WHERE id=?", (new_progress, 1 if new_focus else 0, clean_id))
        connection.commit()


def add_bookmark(engine_module, book_id: object, locator: object, label: object = "") -> str:
    bookmark_id = uuid.uuid4().hex
    clean_locator = str(locator or "").strip()[:1000]
    if not clean_locator:
        raise ReaderLibraryError("书签位置不能为空")
    with closing(_connect(engine_module)) as connection:
        if connection.execute("SELECT 1 FROM books WHERE id=?", (str(book_id),)).fetchone() is None:
            raise ReaderLibraryError("书籍不存在")
        connection.execute("INSERT INTO bookmarks(id,book_id,locator,label) VALUES(?,?,?,?)", (bookmark_id, str(book_id), clean_locator, " ".join(str(label or "").split())[:200]))
        connection.commit()
    return bookmark_id


def add_highlight(engine_module, book_id: object, locator: object, quote_text: object, note: object = "") -> str:
    highlight_id = uuid.uuid4().hex
    clean_quote = str(quote_text or "").strip()[:5000]
    if not clean_quote:
        raise ReaderLibraryError("高亮内容不能为空")
    with closing(_connect(engine_module)) as connection:
        if connection.execute("SELECT 1 FROM books WHERE id=?", (str(book_id),)).fetchone() is None:
            raise ReaderLibraryError("书籍不存在")
        connection.execute("INSERT INTO highlights(id,book_id,locator,quote,note) VALUES(?,?,?,?,?)", (highlight_id, str(book_id), str(locator or "")[:1000], clean_quote, str(note or "")[:5000]))
        connection.commit()
    return highlight_id


def book_annotations(engine_module, book_id: object) -> dict[str, list[dict[str, str]]]:
    with closing(_connect(engine_module)) as connection:
        bookmarks = connection.execute("SELECT * FROM bookmarks WHERE book_id=? ORDER BY created_at", (str(book_id),)).fetchall()
        highlights = connection.execute("SELECT * FROM highlights WHERE book_id=? ORDER BY created_at", (str(book_id),)).fetchall()
    return {
        "bookmarks": [{"id": str(row["id"]), "locator": str(row["locator"]), "label": str(row["label"])} for row in bookmarks],
        "highlights": [{"id": str(row["id"]), "locator": str(row["locator"]), "quote": str(row["quote"]), "note": str(row["note"])} for row in highlights],
    }


def add_course_attachment(engine_module, course_id: object, source_file: object) -> dict[str, Any]:
    clean_course = str(course_id or "").strip().lower()
    if clean_course not in {str(item["id"]) for item in list_courses(engine_module)}:
        raise ReaderLibraryError("课程不存在")
    source = _source_file(source_file, SUPPORTED_ATTACHMENTS)
    attachment_id = uuid.uuid4().hex
    root = _data_root(engine_module) / "course-attachments" / clean_course
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{attachment_id}{source.suffix.lower()}"
    shutil.copy2(source, destination)
    with closing(_connect(engine_module)) as connection:
        connection.execute("INSERT INTO course_attachments(id,course_id,name,managed_path,kind) VALUES(?,?,?,?,?)", (attachment_id, clean_course, source.name[:240], str(destination), source.suffix.lower().lstrip(".")))
        connection.commit()
    return {"id": attachment_id, "courseId": clean_course, "name": source.name[:240], "kind": source.suffix.lower().lstrip("."), "path": str(destination)}


def list_course_attachments(engine_module, course_id: object) -> list[dict[str, Any]]:
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute("SELECT * FROM course_attachments WHERE course_id=? ORDER BY created_at", (str(course_id),)).fetchall()
    return [{"id": str(row["id"]), "name": str(row["name"]), "kind": str(row["kind"]), "path": str(row["managed_path"])} for row in rows]


def run_reader_library_self_test() -> None:
    import tempfile

    assert _safe_member("OPS/chapter.xhtml") == Path("OPS/chapter.xhtml")
    try:
        _safe_member("../evil")
    except ReaderLibraryError:
        pass
    else:
        raise AssertionError("archive traversal accepted")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        data = root / "data"
        pdf = root / "book.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF")

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

        book = import_book(Engine, pdf)
        assert book["kind"] == "pdf"
        add_bookmark(Engine, book["id"], "page:1", "Start")
        add_highlight(Engine, book["id"], "page:1", "Quote")
        assert len(book_annotations(Engine, book["id"])["bookmarks"]) == 1
