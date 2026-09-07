from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlsplit

from headless_reader_api import HeadlessReaderApiError, HeadlessPdfRender
from headless_service import HeadlessServiceError, _safe_detail

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


def _first(values: dict[str, list[str]], name: str, default: str = "") -> str:
    rows = values.get(name)
    return str(rows[0]) if rows else default


def _reader_pdf_error(handler, exc: HeadlessReaderApiError) -> None:  # noqa: ANN001
    detail = _safe_detail(exc, 300)
    if detail in {"book not found", "PDF 页面不存在"}:
        status = 404
    else:
        status = 400
    handler._json(status, {"ok": False, "error": detail})


def _send_png(handler, rendered: HeadlessPdfRender) -> None:  # noqa: ANN001
    body = rendered.body
    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, OSError):
        return


class HeadlessReaderPdfHttpMixin:
    """Authenticated bounded HTTP access to PDF metadata, text, search, selection and PNG render."""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        if not path.startswith("/v1/reader/books/"):
            super().do_GET()
            return

        parts = _route_parts(path)
        document_route = len(parts) == 5 and parts[:3] == ["v1", "reader", "books"] and parts[4] == "pdf"
        search_route = (
            len(parts) == 6
            and parts[:3] == ["v1", "reader", "books"]
            and parts[4:] == ["pdf", "search"]
        )
        page_route = (
            len(parts) == 7
            and parts[:3] == ["v1", "reader", "books"]
            and parts[4:6] == ["pdf", "pages"]
        )
        render_route = (
            len(parts) == 8
            and parts[:3] == ["v1", "reader", "books"]
            and parts[4:6] == ["pdf", "pages"]
            and parts[7] == "render"
        )
        if not any((document_route, search_route, page_route, render_route)):
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
                result = reader_api.pdf_document(book_id)
                self._json(200, {"ok": True, **result})
                return
            if search_route:
                values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=10)
                result = reader_api.pdf_search(
                    book_id,
                    _first(values, "q"),
                    start_page=_first(values, "startPage", "1"),
                    start_char=_first(values, "startChar", "0"),
                    max_pages=_first(values, "maxPages", "100"),
                    limit=_first(values, "limit", "200"),
                )
                self._json(200, {"ok": True, **result})
                return
            page_id = parts[6]
            if render_route:
                values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=5)
                rendered = reader_api.pdf_render_png(book_id, page_id, scale=_first(values, "scale", "1"))
                _send_png(self, rendered)
                return
            result = reader_api.pdf_page(book_id, page_id)
            self._json(200, {"ok": True, **result})
        except HeadlessReaderApiError as exc:
            _reader_pdf_error(self, exc)
        except (ValueError, UnicodeError):
            self._json(400, {"ok": False, "error": "invalid PDF request"})
        except Exception:
            self._json(502, {"ok": False, "error": "reader PDF request failed"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if not path.startswith("/v1/reader/books/"):
            super().do_POST()
            return
        parts = _route_parts(path)
        selection_route = (
            len(parts) == 8
            and parts[:3] == ["v1", "reader", "books"]
            and parts[4:6] == ["pdf", "pages"]
            and parts[7] == "selection"
        )
        if not selection_route:
            super().do_POST()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        reader_api = getattr(self.server, "reader_api", None)
        if reader_api is None:
            self._json(503, {"ok": False, "error": "reader api is unavailable"})
            return
        try:
            payload = self._read_json()
            result = reader_api.pdf_selection(parts[3], parts[6], payload)
            self._json(200, {"ok": True, **result})
        except HeadlessReaderApiError as exc:
            _reader_pdf_error(self, exc)
        except HeadlessServiceError as exc:
            self._json(400, {"ok": False, "error": _safe_detail(exc, 300)})
        except Exception:
            self._json(502, {"ok": False, "error": "reader PDF request failed"})
