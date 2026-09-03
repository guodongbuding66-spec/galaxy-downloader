from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from platform_paths import resolve_platform_paths
from reader_workspace import (
    ReaderWorkspaceError,
    add_annotation,
    add_bookmark,
    cbz_pages,
    delete_annotation,
    delete_bookmark,
    list_annotations,
    list_bookmarks,
    list_books,
    search_reader,
    update_reader_settings,
    update_reading_position,
)

_BOOK_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_OBJECT_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_MAX_BOOKS = 5_000


class HeadlessReaderApiError(RuntimeError):
    pass


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def _clean_book_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _BOOK_ID_RE.fullmatch(clean):
        raise HeadlessReaderApiError("invalid book id")
    return clean


def _clean_object_id(value: object, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not _OBJECT_ID_RE.fullmatch(clean):
        raise HeadlessReaderApiError(f"invalid {label} id")
    return clean


def _safe_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()[:limit]


def _safe_directory(value: Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    if raw.exists() and raw.is_symlink():
        raise HeadlessReaderApiError(f"{label} cannot be a symbolic link")
    resolved = raw.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


@dataclass(frozen=True)
class HeadlessReaderContext:
    program_path: Path
    data_path: Path
    state_path: Path

    def app_dir(self) -> Path:
        return self.program_path

    def data_dir(self) -> Path:
        self.data_path.mkdir(parents=True, exist_ok=True)
        return self.data_path

    def state_dir(self) -> Path:
        self.state_path.mkdir(parents=True, exist_ok=True)
        return self.state_path


def build_headless_reader_context(
    *,
    program_dir: Path | None = None,
    data_dir: Path | None = None,
    state_dir: Path | None = None,
) -> HeadlessReaderContext:
    program = Path(program_dir or Path(__file__).resolve().parent).expanduser().resolve(strict=False)
    paths = resolve_platform_paths(program_dir=program)
    data = _safe_directory(Path(data_dir or paths.data_dir), label="reader data directory")
    state = _safe_directory(Path(state_dir or paths.state_dir), label="reader state directory")
    return HeadlessReaderContext(program, data, state)


class HeadlessReaderApi:
    def __init__(
        self,
        *,
        context: HeadlessReaderContext | None = None,
        program_dir: Path | None = None,
        data_dir: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.context = context or build_headless_reader_context(
            program_dir=program_dir,
            data_dir=data_dir,
            state_dir=state_dir,
        )

    def _book(self, book_id: object) -> dict[str, Any]:
        clean = _clean_book_id(book_id)
        for offset in range(0, _MAX_BOOKS, 500):
            rows = list_books(self.context, limit=500, offset=offset)
            for row in rows:
                if str(row.get("id") or "") == clean:
                    return dict(row)
            if len(rows) < 500:
                break
        raise HeadlessReaderApiError("book not found")

    def books(self, *, limit: object = 100, offset: object = 0) -> dict[str, Any]:
        safe_limit = _bounded_int(limit, 100, 1, 500)
        safe_offset = _bounded_int(offset, 0, 0, _MAX_BOOKS)
        try:
            rows = list_books(self.context, limit=safe_limit, offset=safe_offset)
        except ReaderWorkspaceError as exc:
            raise HeadlessReaderApiError(str(exc)) from exc
        return {"books": rows, "limit": safe_limit, "offset": safe_offset}

    def detail(self, book_id: object) -> dict[str, Any]:
        return {"book": self._book(book_id)}

    def search(self, query: object, *, limit: object = 100) -> dict[str, Any]:
        text = _safe_text(query, 200)
        if not text:
            raise HeadlessReaderApiError("reader search query is required")
        safe_limit = _bounded_int(limit, 100, 1, 500)
        try:
            rows = search_reader(self.context, text, limit=safe_limit)
        except ReaderWorkspaceError as exc:
            raise HeadlessReaderApiError(str(exc)) from exc
        return {"results": rows, "query": text, "limit": safe_limit}

    def bookmarks(self, book_id: object, *, limit: object = 1000) -> dict[str, Any]:
        book = self._book(book_id)
        safe_limit = _bounded_int(limit, 1000, 1, 10_000)
        try:
            rows = list_bookmarks(self.context, book["id"], limit=safe_limit)
        except ReaderWorkspaceError as exc:
            raise HeadlessReaderApiError(str(exc)) from exc
        return {"bookId": book["id"], "bookmarks": rows, "limit": safe_limit}

    def annotations(self, book_id: object, *, limit: object = 2000) -> dict[str, Any]:
        book = self._book(book_id)
        safe_limit = _bounded_int(limit, 2000, 1, 20_000)
        try:
            rows = list_annotations(self.context, book["id"], limit=safe_limit)
        except ReaderWorkspaceError as exc:
            raise HeadlessReaderApiError(str(exc)) from exc
        return {"bookId": book["id"], "annotations": rows, "limit": safe_limit}

    def pages(self, book_id: object, *, limit: object = 1000) -> dict[str, Any]:
        book = self._book(book_id)
        safe_limit = _bounded_int(limit, 1000, 1, 5000)
        try:
            rows = cbz_pages(self.context, book["id"], limit=safe_limit)
        except ReaderWorkspaceError as exc:
            raise HeadlessReaderApiError(str(exc)) from exc
        return {"bookId": book["id"], "pages": rows, "limit": safe_limit}

    def set_progress(self, book_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        book = self._book(book_id)
        if "progressPercent" not in payload:
            raise HeadlessReaderApiError("progressPercent is required")
        try:
            progress = float(payload.get("progressPercent"))
        except (TypeError, ValueError) as exc:
            raise HeadlessReaderApiError("progressPercent must be a number") from exc
        if not math.isfinite(progress) or progress < 0 or progress > 100:
            raise HeadlessReaderApiError("progressPercent must be between 0 and 100")
        locator = str(payload.get("locator") or "").replace("\x00", " ").strip()[:1000]
        try:
            update_reading_position(self.context, book["id"], progress, locator)
        except ReaderWorkspaceError as exc:
            raise HeadlessReaderApiError(str(exc)) from exc
        return self.detail(book["id"])

    def set_settings(self, book_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        book = self._book(book_id)
        values = dict(payload)
        if not values:
            raise HeadlessReaderApiError("reader settings payload is empty")
        try:
            settings = update_reader_settings(self.context, book["id"], values)
        except ReaderWorkspaceError as exc:
            raise HeadlessReaderApiError(str(exc)) from exc
        return {"bookId": book["id"], "settings": settings}

    def create_bookmark(self, book_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        book = self._book(book_id)
        try:
            bookmark = add_bookmark(
                self.context,
                book["id"],
                payload.get("locator"),
                label=payload.get("label", ""),
            )
        except ReaderWorkspaceError as exc:
            raise HeadlessReaderApiError(str(exc)) from exc
        return {"bookId": book["id"], "bookmark": bookmark}

    def remove_bookmark(self, bookmark_id: object) -> dict[str, Any]:
        clean = _clean_object_id(bookmark_id, "bookmark")
        try:
            deleted = delete_bookmark(self.context, clean)
        except ReaderWorkspaceError as exc:
            raise HeadlessReaderApiError(str(exc)) from exc
        if not deleted:
            raise HeadlessReaderApiError("bookmark not found")
        return {"bookmarkId": clean, "deleted": True}

    def create_annotation(self, book_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        book = self._book(book_id)
        try:
            annotation = add_annotation(
                self.context,
                book["id"],
                payload.get("locator"),
                kind=payload.get("kind", "highlight"),
                selected_text=payload.get("selectedText", ""),
                note=payload.get("note", ""),
            )
        except ReaderWorkspaceError as exc:
            raise HeadlessReaderApiError(str(exc)) from exc
        return {"bookId": book["id"], "annotation": annotation}

    def remove_annotation(self, annotation_id: object) -> dict[str, Any]:
        clean = _clean_object_id(annotation_id, "annotation")
        try:
            deleted = delete_annotation(self.context, clean)
        except ReaderWorkspaceError as exc:
            raise HeadlessReaderApiError(str(exc)) from exc
        if not deleted:
            raise HeadlessReaderApiError("annotation not found")
        return {"annotationId": clean, "deleted": True}


def run_headless_reader_api_self_test() -> None:
    import tempfile

    from reader_workspace import import_book

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        program = root / "program"
        data = root / "data"
        state = root / "state"
        source = root / "source"
        for target in (program, data, state, source):
            target.mkdir()
        context = HeadlessReaderContext(program, data, state)
        text = source / "Reader Demo.txt"
        text.write_text("Galaxy Reader headless searchable phrase", encoding="utf-8")
        imported = import_book(context, text, title="Reader Demo")
        api = HeadlessReaderApi(context=context)

        listed = api.books(limit=10)
        assert listed["books"][0]["id"] == imported["id"]
        detail = api.detail(imported["id"])
        assert detail["book"]["title"] == "Reader Demo"
        assert "managedPath" not in detail["book"] and "filePath" not in detail["book"]

        searched = api.search("searchable")
        assert searched["results"][0]["bookId"] == imported["id"]
        progress = api.set_progress(imported["id"], {"progressPercent": 42.5, "locator": "line:1"})
        assert progress["book"]["progressPercent"] == 42.5
        settings = api.set_settings(imported["id"], {"fontSize": 23, "theme": "sepia"})
        assert settings["settings"]["fontSize"] == 23 and settings["settings"]["theme"] == "sepia"

        bookmark = api.create_bookmark(imported["id"], {"locator": "line:1", "label": "Start"})
        assert api.bookmarks(imported["id"])["bookmarks"][0]["id"] == bookmark["bookmark"]["id"]
        annotation = api.create_annotation(
            imported["id"],
            {"locator": "line:1", "kind": "highlight", "selectedText": "searchable phrase", "note": "Remember"},
        )
        assert api.annotations(imported["id"])["annotations"][0]["id"] == annotation["annotation"]["id"]
        assert api.remove_bookmark(bookmark["bookmark"]["id"])["deleted"] is True
        assert api.remove_annotation(annotation["annotation"]["id"])["deleted"] is True

        try:
            api.set_progress(imported["id"], {"progressPercent": float("nan")})
        except HeadlessReaderApiError:
            pass
        else:
            raise AssertionError("non-finite Reader progress was accepted")
        try:
            api.detail("not-a-book")
        except HeadlessReaderApiError:
            pass
        else:
            raise AssertionError("invalid Reader book id was accepted")
