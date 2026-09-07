from __future__ import annotations

from urllib.parse import unquote, urlsplit

from headless_reader_api import HeadlessReaderApiError
from headless_service import _safe_detail


_MAX_ROUTE_PART_CHARS = 240


def _route_parts(path: str) -> list[str]:
    parts: list[str] = []
    for raw in path.split("/"):
        if not raw:
            continue
        value = unquote(raw)
        if len(value) > _MAX_ROUTE_PART_CHARS or "\x00" in value or "/" in value or "\\" in value:
            return []
        parts.append(value)
    return parts


def _reader_epub_error(handler, exc: HeadlessReaderApiError) -> None:
    detail = _safe_detail(exc, 300)
    if detail in {"book not found", "EPUB book not found", "EPUB chapter not found"}:
        status = 404
    else:
        status = 400
    handler._json(status, {"ok": False, "error": detail})


class HeadlessReaderEpubHttpMixin:
    """Authenticated path-safe HTTP exposure for EPUB TOC and chapter text."""

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if not path.startswith("/v1/reader/books/"):
            super().do_GET()
            return

        parts = _route_parts(path)
        document_route = len(parts) == 5 and parts[:3] == ["v1", "reader", "books"] and parts[4] == "epub"
        chapter_route = (
            len(parts) == 7
            and parts[:3] == ["v1", "reader", "books"]
            and parts[4:6] == ["epub", "chapters"]
        )
        if not document_route and not chapter_route:
            super().do_GET()
            return

        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        reader_api = getattr(self.server, "reader_api", None)
        if reader_api is None:
            self._json(503, {"ok": False, "error": "reader api is unavailable"})
            return

        try:
            book_id = parts[3]
            if document_route:
                result = reader_api.epub_document(book_id)
            else:
                result = reader_api.epub_chapter(book_id, parts[6])
            self._json(200, {"ok": True, **result})
        except HeadlessReaderApiError as exc:
            _reader_epub_error(self, exc)
        except Exception:
            self._json(502, {"ok": False, "error": "reader EPUB request failed"})
