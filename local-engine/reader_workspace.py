from __future__ import annotations

import html
import json
import math
import re
import shutil
import sqlite3
import stat
import uuid
import zipfile
from contextlib import closing, suppress
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from runtime_storage import state_dir as runtime_state_dir

DATABASE_FILENAME = "reader.sqlite3"
SCHEMA_VERSION = 1
SUPPORTED_EXTENSIONS = frozenset({".pdf", ".epub", ".cbz", ".txt", ".html", ".htm"})
MAX_BOOK_BYTES = 500 * 1024 * 1024
MAX_ARCHIVE_FILES = 20_000
MAX_ARCHIVE_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TEXT_CHARS = 12_000_000
MAX_BOOKS = 5_000
MAX_BOOKMARKS_PER_BOOK = 10_000
MAX_ANNOTATIONS_PER_BOOK = 20_000
MAX_ANNOTATION_CHARS = 20_000
MAX_LOCATOR_CHARS = 1_000
_BOOK_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_SAFE_SETTING_KEYS = frozenset({"fontSize", "contentWidth", "theme", "focusMode", "readingMode", "mangaDirection"})
_READER_THEMES = frozenset({"system", "light", "dark", "sepia"})
_READING_MODES = frozenset({"auto", "vertical", "single", "double", "fit-width"})
_MANGA_DIRECTIONS = frozenset({"ltr", "rtl"})
_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"})


class ReaderWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReaderBook:
    id: str
    title: str
    format: str
    source_name: str
    size_bytes: int
    progress_percent: float
    locator: str
    settings: dict[str, Any]

    def public_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["sourceName"] = data.pop("source_name")
        data["sizeBytes"] = data.pop("size_bytes")
        data["progressPercent"] = data.pop("progress_percent")
        return data


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.lower() in {"script", "style", "svg", "noscript"}:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag.lower() in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "svg", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and tag.lower() in {"p", "div", "li", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts)).replace("\x00", " ")
        lines = [" ".join(line.split()) for line in value.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def reader_database_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / DATABASE_FILENAME


def _connect(engine_module) -> sqlite3.Connection:
    connection = sqlite3.connect(reader_database_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS reader_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS books (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            format TEXT NOT NULL,
            source_name TEXT NOT NULL,
            managed_path TEXT NOT NULL,
            content_root TEXT NOT NULL DEFAULT '',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            progress_percent REAL NOT NULL DEFAULT 0,
            locator TEXT NOT NULL DEFAULT '',
            settings_json TEXT NOT NULL DEFAULT '{}',
            text_content TEXT NOT NULL DEFAULT '',
            page_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS bookmarks (
            id TEXT PRIMARY KEY,
            book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            locator TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS annotations (
            id TEXT PRIMARY KEY,
            book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            locator TEXT NOT NULL,
            selected_text TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_reader_books_updated
            ON books(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_reader_bookmarks_book
            ON bookmarks(book_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_reader_annotations_book
            ON annotations(book_id, created_at);
        """
    )
    row = connection.execute("SELECT value FROM reader_meta WHERE key='schema_version'").fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO reader_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    else:
        try:
            version = int(row["value"])
        except (TypeError, ValueError) as exc:
            raise ReaderWorkspaceError("Reader database schema version is invalid") from exc
        if version != SCHEMA_VERSION:
            raise ReaderWorkspaceError(f"Unsupported Reader database schema version: {version}")
    connection.commit()
    return connection


def _data_root(engine_module) -> Path:
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir()) / "data"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "reader"
    if target.exists() and target.is_symlink():
        raise ReaderWorkspaceError("Reader data root cannot be a symbolic link")
    target.mkdir(parents=True, exist_ok=True)
    return target


def _clean_book_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _BOOK_ID_RE.fullmatch(clean):
        raise ReaderWorkspaceError("Book ID 无效")
    return clean


def _clean_locator(value: object) -> str:
    clean = str(value or "").replace("\x00", " ").strip()[:MAX_LOCATOR_CHARS]
    if not clean:
        raise ReaderWorkspaceError("阅读位置不能为空")
    return clean


def _clean_title(value: object, fallback: str = "Book") -> str:
    clean = " ".join(str(value or fallback).split()).strip()[:240]
    return clean or fallback


def _safe_archive_member(name: str) -> PurePosixPath:
    normalized = str(name or "").replace("\\", "/")
    if not normalized or normalized.startswith("/") or "\x00" in normalized:
        raise ReaderWorkspaceError("Archive member path 无效")
    path = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ReaderWorkspaceError("Archive 包含路径穿越")
    if path.parts and re.match(r"^[A-Za-z]:", path.parts[0]):
        raise ReaderWorkspaceError("Archive member drive path 无效")
    return path


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _prepare_source(source_file: Path) -> tuple[Path, int, str]:
    raw = Path(source_file).expanduser()
    if raw.is_symlink():
        raise ReaderWorkspaceError("Reader import 不接受符号链接")
    try:
        source = raw.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ReaderWorkspaceError("Reader source 不存在") from exc
    if not source.is_file() or source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ReaderWorkspaceError("Reader 支持 PDF / EPUB / CBZ / TXT / HTML")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise ReaderWorkspaceError(str(exc)) from exc
    if size <= 0 or size > MAX_BOOK_BYTES:
        raise ReaderWorkspaceError("Reader 文件为空或超过 500 MB 上限")
    return source, size, source.suffix.lower().lstrip(".")


def _copy_atomic(source: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + f".{uuid.uuid4().hex[:8]}.part")
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        temporary.replace(destination)
    except Exception:
        with suppress(OSError):
            temporary.unlink()
        raise


def _extract_archive(archive_path: Path, destination: Path, *, cbz_only_images: bool = False) -> list[Path]:
    if destination.exists() and destination.is_symlink():
        raise ReaderWorkspaceError("Reader content root cannot be a symbolic link")
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    expanded = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_FILES:
                raise ReaderWorkspaceError("Archive 文件数量超过 20,000 上限")
            for info in infos:
                if info.flag_bits & 0x1:
                    raise ReaderWorkspaceError("加密 Archive 不受支持")
                if _zip_member_is_symlink(info):
                    raise ReaderWorkspaceError("Archive 内符号链接不受支持")
                rel = _safe_archive_member(info.filename)
                if info.file_size < 0 or info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ReaderWorkspaceError("Archive 单个成员过大")
                expanded += info.file_size
                if expanded > MAX_ARCHIVE_EXPANDED_BYTES:
                    raise ReaderWorkspaceError("Archive 解压后超过 1 GB 上限")
                if cbz_only_images and not info.is_dir() and Path(rel.name).suffix.lower() not in _IMAGE_EXTENSIONS:
                    continue
                target = destination.joinpath(*rel.parts)
                try:
                    target.resolve(strict=False).relative_to(destination.resolve(strict=False))
                except (OSError, RuntimeError, ValueError) as exc:
                    raise ReaderWorkspaceError("Archive extraction escaped Reader root") from exc
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(info, "r") as src, target.open("xb") as dst:
                    while True:
                        block = src.read(1024 * 1024)
                        if not block:
                            break
                        written += len(block)
                        if written > info.file_size + 1024 or written > MAX_ARCHIVE_MEMBER_BYTES:
                            raise ReaderWorkspaceError("Archive member 实际大小异常")
                        dst.write(block)
                extracted.append(target)
    except zipfile.BadZipFile as exc:
        raise ReaderWorkspaceError("EPUB/CBZ 文件损坏") from exc
    return extracted


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    with suppress(Exception):
        parser.feed(value)
        parser.close()
    return parser.text()


def _read_text_file(path: Path, *, html_mode: bool = False) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > 40 * 1024 * 1024:
        data = data[:40 * 1024 * 1024]
    value = data.decode("utf-8", errors="replace")
    if html_mode:
        value = _html_to_text(value)
    else:
        value = value.replace("\x00", " ")
    return value[:MAX_TEXT_CHARS]


def _epub_spine(content_root: Path) -> list[Path]:
    container = content_root / "META-INF" / "container.xml"
    try:
        root = ElementTree.parse(container).getroot()
        rootfile = next(element for element in root.iter() if element.tag.endswith("rootfile"))
        opf_rel = _safe_archive_member(rootfile.attrib["full-path"])
        opf = content_root.joinpath(*opf_rel.parts)
        package = ElementTree.parse(opf).getroot()
        manifest: dict[str, str] = {}
        for element in package.iter():
            if element.tag.endswith("item") and element.attrib.get("id") and element.attrib.get("href"):
                manifest[element.attrib["id"]] = element.attrib["href"]
        result: list[Path] = []
        for element in package.iter():
            if not element.tag.endswith("itemref"):
                continue
            href = manifest.get(element.attrib.get("idref", ""))
            if not href:
                continue
            rel = _safe_archive_member(href)
            candidate = opf.parent.joinpath(*rel.parts).resolve(strict=False)
            candidate.relative_to(content_root.resolve(strict=False))
            if candidate.is_file() and candidate.suffix.lower() in {".xhtml", ".html", ".htm"}:
                result.append(candidate)
        if result:
            return result
    except (OSError, RuntimeError, StopIteration, KeyError, ValueError, ElementTree.ParseError, ReaderWorkspaceError):
        pass
    return sorted(
        path for path in content_root.rglob("*") if path.is_file() and path.suffix.lower() in {".xhtml", ".html", ".htm"}
    )[:5000]


def _book_text(format_id: str, managed: Path, content_root: Path, extracted: list[Path]) -> str:
    if format_id == "txt":
        return _read_text_file(managed)
    if format_id in {"html", "htm"}:
        return _read_text_file(managed, html_mode=True)
    if format_id != "epub":
        return ""
    parts: list[str] = []
    total = 0
    for chapter in _epub_spine(content_root):
        text = _read_text_file(chapter, html_mode=True)
        if not text:
            continue
        remaining = MAX_TEXT_CHARS - total
        if remaining <= 0:
            break
        piece = text[:remaining]
        parts.append(piece)
        total += len(piece) + 2
    return "\n\n".join(parts)[:MAX_TEXT_CHARS]


def _default_settings(format_id: str) -> dict[str, Any]:
    return {
        "fontSize": 18,
        "contentWidth": 820,
        "theme": "system",
        "focusMode": False,
        "readingMode": "vertical" if format_id == "cbz" else "auto",
        "mangaDirection": "ltr",
    }


def import_book(engine_module, source_file: Path, *, title: object = "") -> dict[str, Any]:
    source, size, format_id = _prepare_source(source_file)
    with closing(_connect(engine_module)) as connection:
        count = int(connection.execute("SELECT COUNT(*) FROM books").fetchone()[0])
        if count >= MAX_BOOKS:
            raise ReaderWorkspaceError("Reader 书籍数量超过安全上限")
    book_id = uuid.uuid4().hex
    book_root = _data_root(engine_module) / "books" / book_id
    book_root.mkdir(parents=True, exist_ok=False)
    managed = book_root / f"source.{format_id}"
    content_root = book_root / "content"
    extracted: list[Path] = []
    try:
        _copy_atomic(source, managed)
        if format_id == "epub":
            extracted = _extract_archive(managed, content_root)
        elif format_id == "cbz":
            extracted = _extract_archive(managed, content_root, cbz_only_images=True)
        text_content = _book_text(format_id, managed, content_root, extracted)
        page_count = (
            len([path for path in extracted if path.suffix.lower() in _IMAGE_EXTENSIONS])
            if format_id == "cbz"
            else len(_epub_spine(content_root)) if format_id == "epub" else 0
        )
        clean_title = _clean_title(title, source.stem)
        settings = _default_settings(format_id)
        with closing(_connect(engine_module)) as connection:
            connection.execute(
                """
                INSERT INTO books(
                    id, title, format, source_name, managed_path, content_root,
                    size_bytes, settings_json, text_content, page_count
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    clean_title,
                    format_id,
                    source.name[:240],
                    str(managed),
                    str(content_root) if content_root.exists() else "",
                    size,
                    json.dumps(settings, ensure_ascii=False, separators=(",", ":")),
                    text_content,
                    page_count,
                ),
            )
            connection.commit()
    except Exception:
        with suppress(OSError):
            shutil.rmtree(book_root)
        raise
    return {
        "id": book_id,
        "title": clean_title,
        "format": format_id,
        "sourceName": source.name[:240],
        "sizeBytes": size,
        "pageCount": page_count,
        "progressPercent": 0.0,
        "settings": settings,
    }


def _book_from_row(row: sqlite3.Row) -> ReaderBook:
    try:
        settings = json.loads(row["settings_json"] or "{}")
    except (TypeError, ValueError):
        settings = {}
    if not isinstance(settings, dict):
        settings = {}
    return ReaderBook(
        id=str(row["id"]),
        title=str(row["title"]),
        format=str(row["format"]),
        source_name=str(row["source_name"]),
        size_bytes=max(0, int(row["size_bytes"] or 0)),
        progress_percent=float(row["progress_percent"] or 0),
        locator=str(row["locator"] or ""),
        settings=settings,
    )


def list_books(engine_module, *, limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT * FROM books ORDER BY updated_at DESC, created_at DESC LIMIT ? OFFSET ?",
            (safe_limit, safe_offset),
        ).fetchall()
    return [_book_from_row(row).public_payload() for row in rows]


def book_file_path(engine_module, book_id: object) -> Path:
    clean = _clean_book_id(book_id)
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT managed_path FROM books WHERE id=?", (clean,)).fetchone()
    if row is None:
        raise ReaderWorkspaceError("Book 不存在")
    path = Path(row["managed_path"])
    root = _data_root(engine_module) / "books" / clean
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ReaderWorkspaceError("Book 文件路径未通过 Reader 边界校验") from exc
    if path.is_symlink() or not resolved.is_file():
        raise ReaderWorkspaceError("Book 文件不可用")
    return resolved


def cbz_pages(engine_module, book_id: object, *, limit: int = 5000) -> list[str]:
    clean = _clean_book_id(book_id)
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT format, content_root FROM books WHERE id=?", (clean,)).fetchone()
    if row is None or row["format"] != "cbz":
        return []
    root = Path(row["content_root"])
    if not root.is_dir() or root.is_symlink():
        return []
    safe_limit = max(1, min(int(limit), 5000))
    pages = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in _IMAGE_EXTENSIONS)
    result: list[str] = []
    for path in pages[:safe_limit]:
        try:
            rel = path.resolve(strict=True).relative_to(root.resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            continue
        result.append(rel.as_posix())
    return result


def update_reading_position(engine_module, book_id: object, progress_percent: object, locator: object) -> None:
    clean = _clean_book_id(book_id)
    try:
        progress = float(progress_percent)
    except (TypeError, ValueError):
        progress = 0.0
    if not math.isfinite(progress):
        progress = 0.0
    progress = round(max(0.0, min(progress, 100.0)), 3)
    clean_locator = str(locator or "").replace("\x00", " ").strip()[:MAX_LOCATOR_CHARS]
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute(
            "UPDATE books SET progress_percent=?, locator=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (progress, clean_locator, clean),
        )
        if cursor.rowcount != 1:
            raise ReaderWorkspaceError("Book 不存在")
        connection.commit()


def update_reader_settings(engine_module, book_id: object, values: dict[str, Any]) -> dict[str, Any]:
    clean = _clean_book_id(book_id)
    if not isinstance(values, dict):
        raise ReaderWorkspaceError("Reader settings 格式无效")
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT settings_json FROM books WHERE id=?", (clean,)).fetchone()
        if row is None:
            raise ReaderWorkspaceError("Book 不存在")
        try:
            current = json.loads(row["settings_json"] or "{}")
        except (TypeError, ValueError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        for key, value in values.items():
            if key not in _SAFE_SETTING_KEYS:
                continue
            if key == "fontSize":
                try:
                    current[key] = max(10, min(int(value), 72))
                except (TypeError, ValueError):
                    continue
            elif key == "contentWidth":
                try:
                    current[key] = max(320, min(int(value), 1800))
                except (TypeError, ValueError):
                    continue
            elif key == "focusMode":
                current[key] = bool(value)
            elif key == "theme" and str(value) in _READER_THEMES:
                current[key] = str(value)
            elif key == "readingMode" and str(value) in _READING_MODES:
                current[key] = str(value)
            elif key == "mangaDirection" and str(value) in _MANGA_DIRECTIONS:
                current[key] = str(value)
        connection.execute(
            "UPDATE books SET settings_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(current, ensure_ascii=False, separators=(",", ":")), clean),
        )
        connection.commit()
    return current


def add_bookmark(engine_module, book_id: object, locator: object, *, label: object = "") -> dict[str, str]:
    clean = _clean_book_id(book_id)
    position = _clean_locator(locator)
    clean_label = _clean_title(label, "")[:160]
    bookmark_id = uuid.uuid4().hex
    with closing(_connect(engine_module)) as connection:
        if connection.execute("SELECT 1 FROM books WHERE id=?", (clean,)).fetchone() is None:
            raise ReaderWorkspaceError("Book 不存在")
        count = int(connection.execute("SELECT COUNT(*) FROM bookmarks WHERE book_id=?", (clean,)).fetchone()[0])
        if count >= MAX_BOOKMARKS_PER_BOOK:
            raise ReaderWorkspaceError("Bookmark 数量超过安全上限")
        connection.execute(
            "INSERT INTO bookmarks(id, book_id, locator, label) VALUES(?, ?, ?, ?)",
            (bookmark_id, clean, position, clean_label),
        )
        connection.commit()
    return {"id": bookmark_id, "locator": position, "label": clean_label}


def list_bookmarks(engine_module, book_id: object, *, limit: int = 1000) -> list[dict[str, str]]:
    clean = _clean_book_id(book_id)
    safe_limit = max(1, min(int(limit), MAX_BOOKMARKS_PER_BOOK))
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT id, locator, label FROM bookmarks WHERE book_id=? ORDER BY created_at LIMIT ?",
            (clean, safe_limit),
        ).fetchall()
    return [{"id": row["id"], "locator": row["locator"], "label": row["label"]} for row in rows]


def delete_bookmark(engine_module, bookmark_id: object) -> bool:
    clean = _clean_book_id(bookmark_id)
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute("DELETE FROM bookmarks WHERE id=?", (clean,))
        connection.commit()
        return cursor.rowcount == 1


def add_annotation(
    engine_module,
    book_id: object,
    locator: object,
    *,
    kind: object = "highlight",
    selected_text: object = "",
    note: object = "",
) -> dict[str, str]:
    clean = _clean_book_id(book_id)
    position = _clean_locator(locator)
    clean_kind = str(kind or "highlight").strip().lower()
    if clean_kind not in {"highlight", "note"}:
        raise ReaderWorkspaceError("Annotation 类型无效")
    selection = str(selected_text or "").replace("\x00", " ").strip()[:MAX_ANNOTATION_CHARS]
    clean_note = str(note or "").replace("\x00", " ").strip()[:MAX_ANNOTATION_CHARS]
    if not selection and not clean_note:
        raise ReaderWorkspaceError("Annotation 内容不能为空")
    annotation_id = uuid.uuid4().hex
    with closing(_connect(engine_module)) as connection:
        if connection.execute("SELECT 1 FROM books WHERE id=?", (clean,)).fetchone() is None:
            raise ReaderWorkspaceError("Book 不存在")
        count = int(connection.execute("SELECT COUNT(*) FROM annotations WHERE book_id=?", (clean,)).fetchone()[0])
        if count >= MAX_ANNOTATIONS_PER_BOOK:
            raise ReaderWorkspaceError("Annotation 数量超过安全上限")
        connection.execute(
            "INSERT INTO annotations(id, book_id, kind, locator, selected_text, note) VALUES(?, ?, ?, ?, ?, ?)",
            (annotation_id, clean, clean_kind, position, selection, clean_note),
        )
        connection.commit()
    return {
        "id": annotation_id,
        "kind": clean_kind,
        "locator": position,
        "selectedText": selection,
        "note": clean_note,
    }


def list_annotations(engine_module, book_id: object, *, limit: int = 2000) -> list[dict[str, str]]:
    clean = _clean_book_id(book_id)
    safe_limit = max(1, min(int(limit), MAX_ANNOTATIONS_PER_BOOK))
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT id, kind, locator, selected_text, note FROM annotations WHERE book_id=? ORDER BY created_at LIMIT ?",
            (clean, safe_limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "locator": row["locator"],
            "selectedText": row["selected_text"],
            "note": row["note"],
        }
        for row in rows
    ]


def delete_annotation(engine_module, annotation_id: object) -> bool:
    clean = _clean_book_id(annotation_id)
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute("DELETE FROM annotations WHERE id=?", (clean,))
        connection.commit()
        return cursor.rowcount == 1


def search_reader(engine_module, query: object, *, limit: int = 100) -> list[dict[str, Any]]:
    text = " ".join(str(query or "").split()).strip()[:200]
    if not text:
        return []
    safe_limit = max(1, min(int(limit), 500))
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            """
            SELECT id, title, format, text_content
            FROM books
            WHERE title LIKE ? ESCAPE '\\' OR text_content LIKE ? ESCAPE '\\'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (pattern, pattern, safe_limit),
        ).fetchall()
        annotation_rows = connection.execute(
            """
            SELECT a.id, a.book_id, a.kind, a.locator, a.selected_text, a.note, b.title
            FROM annotations a JOIN books b ON b.id=a.book_id
            WHERE a.selected_text LIKE ? ESCAPE '\\' OR a.note LIKE ? ESCAPE '\\'
            ORDER BY a.updated_at DESC
            LIMIT ?
            """,
            (pattern, pattern, safe_limit),
        ).fetchall()
    results: list[dict[str, Any]] = []
    lower = text.casefold()
    for row in rows:
        content = str(row["text_content"] or "")
        position = content.casefold().find(lower)
        preview = ""
        if position >= 0:
            preview = content[max(0, position - 100) : position + len(text) + 160].strip()
        results.append(
            {
                "type": "book",
                "bookId": row["id"],
                "title": row["title"],
                "format": row["format"],
                "preview": preview[:400],
            }
        )
    for row in annotation_rows:
        results.append(
            {
                "type": "annotation",
                "id": row["id"],
                "bookId": row["book_id"],
                "title": row["title"],
                "kind": row["kind"],
                "locator": row["locator"],
                "preview": (row["selected_text"] or row["note"] or "")[:400],
            }
        )
    return results[:safe_limit]


def delete_book(engine_module, book_id: object) -> bool:
    clean = _clean_book_id(book_id)
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT managed_path FROM books WHERE id=?", (clean,)).fetchone()
        if row is None:
            return False
        connection.execute("DELETE FROM books WHERE id=?", (clean,))
        connection.commit()
    root = _data_root(engine_module) / "books" / clean
    try:
        root.resolve(strict=False).relative_to((_data_root(engine_module) / "books").resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return True
    if root.exists() and not root.is_symlink():
        with suppress(OSError):
            shutil.rmtree(root)
    return True


def run_reader_workspace_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        data = root / "data"
        source_root = root / "source"
        state.mkdir()
        data.mkdir()
        source_root.mkdir()

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

        text_file = source_root / "notes.txt"
        text_file.write_text("Galaxy Reader searchable phrase\nSecond line", encoding="utf-8")
        text_book = import_book(Engine, text_file)
        assert text_book["format"] == "txt"
        update_reading_position(Engine, text_book["id"], 25.5, "line:1")
        bookmark = add_bookmark(Engine, text_book["id"], "line:1", label="Start")
        annotation = add_annotation(
            Engine,
            text_book["id"],
            "line:1",
            selected_text="searchable phrase",
            note="Remember this",
        )
        assert list_bookmarks(Engine, text_book["id"])[0]["id"] == bookmark["id"]
        assert list_annotations(Engine, text_book["id"])[0]["id"] == annotation["id"]
        assert search_reader(Engine, "searchable")[0]["bookId"] == text_book["id"]
        settings = update_reader_settings(
            Engine,
            text_book["id"],
            {"fontSize": 22, "theme": "sepia", "focusMode": True, "unknown": "ignored"},
        )
        assert settings["fontSize"] == 22 and settings["theme"] == "sepia" and settings["focusMode"] is True
        listed = list_books(Engine)
        assert listed[0]["progressPercent"] == 25.5 and listed[0]["locator"] == "line:1"
        assert delete_bookmark(Engine, bookmark["id"])
        assert delete_annotation(Engine, annotation["id"])

        epub_file = source_root / "demo.epub"
        with zipfile.ZipFile(epub_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("META-INF/container.xml", "<container><rootfiles><rootfile full-path='OPS/content.opf'/></rootfiles></container>")
            archive.writestr(
                "OPS/content.opf",
                "<package><manifest><item id='c1' href='chapter.xhtml'/></manifest><spine><itemref idref='c1'/></spine></package>",
            )
            archive.writestr("OPS/chapter.xhtml", "<html><body><h1>Chapter</h1><p>EPUB searchable text</p></body></html>")
        epub = import_book(Engine, epub_file)
        assert epub["format"] == "epub" and search_reader(Engine, "EPUB searchable")

        cbz_file = source_root / "comic.cbz"
        with zipfile.ZipFile(cbz_file, "w") as archive:
            archive.writestr("001.jpg", b"fake-image")
            archive.writestr("002.png", b"fake-image")
        cbz = import_book(Engine, cbz_file)
        assert cbz["pageCount"] == 2 and cbz_pages(Engine, cbz["id"]) == ["001.jpg", "002.png"]

        unsafe = source_root / "unsafe.epub"
        with zipfile.ZipFile(unsafe, "w") as archive:
            archive.writestr("../escape.txt", "bad")
        try:
            import_book(Engine, unsafe)
        except ReaderWorkspaceError:
            pass
        else:
            raise AssertionError("Archive traversal was accepted")
        assert not (root / "escape.txt").exists()
        assert book_file_path(Engine, text_book["id"]).name == "source.txt"
        assert delete_book(Engine, text_book["id"])
