from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from PIL import Image

from reader_workspace import ReaderWorkspaceError, book_file_path

MAX_PDF_PAGES = 20_000
MAX_PAGE_POINTS = 200_000.0
MAX_PAGE_TEXT_CHARS = 2_000_000
MAX_SEARCH_QUERY_CHARS = 200
MAX_SEARCH_RESULTS = 500
MAX_SEARCH_PAGES_PER_BATCH = 100
MAX_MATCH_RECTS = 128
MAX_RENDER_PIXELS = 12_000_000
MAX_RENDER_SIDE = 8_000
MIN_RENDER_SCALE = 0.25
MAX_RENDER_SCALE = 4.0
_PAGE_ID_RE = re.compile(r"^pdf-page:([1-9][0-9]{0,5})$")
_PDFIUM_LOCK = threading.RLock()


class ReaderPdfError(RuntimeError):
    pass


@dataclass(frozen=True)
class PdfRenderedPage:
    book_id: str
    page_id: str
    page_number: int
    page_count: int
    width_points: float
    height_points: float
    rotation: int
    scale: float
    image: Image.Image


def _clean_book_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32}", clean):
        raise ReaderPdfError("Book ID 无效")
    return clean


def _pdf_file(engine_module, book_id: object) -> tuple[str, Path]:
    clean = _clean_book_id(book_id)
    try:
        path = book_file_path(engine_module, clean)
    except ReaderWorkspaceError as exc:
        raise ReaderPdfError(str(exc)) from exc
    if path.suffix.lower() != ".pdf":
        raise ReaderPdfError("Book 不是 PDF")
    return clean, path


def _open_pdf(path: Path):  # noqa: ANN201
    try:
        return pdfium.PdfDocument(path)
    except Exception as exc:
        raise ReaderPdfError("PDF 无法打开；文件可能损坏或需要密码") from exc


def _page_count(pdf) -> int:  # noqa: ANN001
    try:
        count = int(len(pdf))
    except Exception as exc:
        raise ReaderPdfError("PDF 页数读取失败") from exc
    if count <= 0:
        raise ReaderPdfError("PDF 没有可读取页面")
    if count > MAX_PDF_PAGES:
        raise ReaderPdfError("PDF 页数超过 20,000 上限")
    return count


def _page_id(page_number: int) -> str:
    number = max(1, int(page_number))
    return f"pdf-page:{number}"


def _page_index(page_id: object, page_count: int) -> int:
    match = _PAGE_ID_RE.fullmatch(str(page_id or "").strip().lower())
    if not match:
        raise ReaderPdfError("PDF page ID 无效")
    number = int(match.group(1))
    if number < 1 or number > page_count:
        raise ReaderPdfError("PDF 页面不存在")
    return number - 1


def _load_page(pdf, page_index: int):  # noqa: ANN001, ANN201
    try:
        return pdf[page_index]
    except Exception as exc:
        raise ReaderPdfError("PDF 页面读取失败") from exc


def _page_geometry(page) -> tuple[float, float, int]:  # noqa: ANN001
    try:
        width, height = page.get_size()
        width = float(width)
        height = float(height)
        rotation = int(page.get_rotation()) % 360
    except Exception as exc:
        raise ReaderPdfError("PDF 页面尺寸读取失败") from exc
    if (
        not math.isfinite(width)
        or not math.isfinite(height)
        or width <= 0
        or height <= 0
        or width > MAX_PAGE_POINTS
        or height > MAX_PAGE_POINTS
    ):
        raise ReaderPdfError("PDF 页面尺寸异常")
    if rotation not in {0, 90, 180, 270}:
        rotation = 0
    return width, height, rotation


def _clean_text(value: object, *, limit: int = MAX_PAGE_TEXT_CHARS) -> tuple[str, bool]:
    text = str(value or "").replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    truncated = len(text) > limit
    return text[:limit], truncated


def _page_text(textpage) -> tuple[str, bool]:  # noqa: ANN001
    try:
        value = textpage.get_text_bounded()
    except Exception as exc:
        raise ReaderPdfError("PDF 文本提取失败") from exc
    return _clean_text(value)


def _bounded_scale(width: float, height: float, requested: object) -> float:
    try:
        scale = float(requested)
    except (TypeError, ValueError):
        scale = 1.0
    if not math.isfinite(scale):
        scale = 1.0
    scale = max(MIN_RENDER_SCALE, min(scale, MAX_RENDER_SCALE))
    pixel_cap = math.sqrt(MAX_RENDER_PIXELS / max(width * height, 1.0))
    side_cap = min(MAX_RENDER_SIDE / width, MAX_RENDER_SIDE / height)
    scale = min(scale, pixel_cap, side_cap)
    if not math.isfinite(scale) or scale <= 0 or width * scale < 1 or height * scale < 1:
        raise ReaderPdfError("PDF 页面无法在安全像素上限内渲染")
    if width * height * scale * scale > MAX_RENDER_PIXELS + 1:
        raise ReaderPdfError("PDF 渲染像素超过安全上限")
    return round(scale, 6)


def _rect_payload(rect: tuple[float, float, float, float]) -> dict[str, float]:
    left, bottom, right, top = (float(value) for value in rect)
    return {
        "left": round(left, 4),
        "bottom": round(bottom, 4),
        "right": round(right, 4),
        "top": round(top, 4),
    }


def _match_rects(textpage, index: int, count: int) -> tuple[list[dict[str, float]], bool]:  # noqa: ANN001
    try:
        rect_count = max(0, int(textpage.count_rects(index=index, count=count)))
    except Exception:
        return [], False
    result: list[dict[str, float]] = []
    for rect_index in range(min(rect_count, MAX_MATCH_RECTS)):
        try:
            result.append(_rect_payload(textpage.get_rect(rect_index)))
        except Exception:
            continue
    return result, rect_count > MAX_MATCH_RECTS


def pdf_document(engine_module, book_id: object) -> dict[str, Any]:
    clean, path = _pdf_file(engine_module, book_id)
    with _PDFIUM_LOCK:
        pdf = _open_pdf(path)
        try:
            count = _page_count(pdf)
        finally:
            pdf.close()
    return {
        "bookId": clean,
        "pageCount": count,
        "firstPageId": _page_id(1),
        "lastPageId": _page_id(count),
    }


def pdf_page(engine_module, book_id: object, page_id: object) -> dict[str, Any]:
    clean, path = _pdf_file(engine_module, book_id)
    with _PDFIUM_LOCK:
        pdf = _open_pdf(path)
        page = None
        textpage = None
        try:
            count = _page_count(pdf)
            index = _page_index(page_id, count)
            page = _load_page(pdf, index)
            width, height, rotation = _page_geometry(page)
            try:
                textpage = page.get_textpage()
            except Exception as exc:
                raise ReaderPdfError("PDF 文本层读取失败") from exc
            text, truncated = _page_text(textpage)
        finally:
            if textpage is not None:
                textpage.close()
            if page is not None:
                page.close()
            pdf.close()
    return {
        "bookId": clean,
        "pageId": _page_id(index + 1),
        "pageNumber": index + 1,
        "pageCount": count,
        "width": round(width, 4),
        "height": round(height, 4),
        "rotation": rotation,
        "text": text,
        "truncated": truncated,
        "previousPageId": _page_id(index) if index > 0 else None,
        "nextPageId": _page_id(index + 2) if index + 1 < count else None,
    }


def render_pdf_page(
    engine_module,
    book_id: object,
    page_id: object,
    *,
    scale: object = 1.0,
) -> PdfRenderedPage:
    clean, path = _pdf_file(engine_module, book_id)
    with _PDFIUM_LOCK:
        pdf = _open_pdf(path)
        page = None
        bitmap = None
        try:
            count = _page_count(pdf)
            index = _page_index(page_id, count)
            page = _load_page(pdf, index)
            width, height, rotation = _page_geometry(page)
            actual_scale = _bounded_scale(width, height, scale)
            try:
                bitmap = page.render(scale=actual_scale, rotation=0)
                image = bitmap.to_pil().copy()
            except Exception as exc:
                raise ReaderPdfError("PDF 页面渲染失败") from exc
            if image.width <= 0 or image.height <= 0 or image.width * image.height > MAX_RENDER_PIXELS:
                raise ReaderPdfError("PDF 渲染结果尺寸异常")
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGB")
        finally:
            if bitmap is not None:
                bitmap.close()
            if page is not None:
                page.close()
            pdf.close()
    return PdfRenderedPage(
        book_id=clean,
        page_id=_page_id(index + 1),
        page_number=index + 1,
        page_count=count,
        width_points=width,
        height_points=height,
        rotation=rotation,
        scale=actual_scale,
        image=image,
    )


def pdf_text_in_rect(
    engine_module,
    book_id: object,
    page_id: object,
    *,
    left: object,
    bottom: object,
    right: object,
    top: object,
) -> dict[str, Any]:
    clean, path = _pdf_file(engine_module, book_id)
    try:
        values = [float(left), float(bottom), float(right), float(top)]
    except (TypeError, ValueError) as exc:
        raise ReaderPdfError("PDF selection rectangle 无效") from exc
    if not all(math.isfinite(value) for value in values):
        raise ReaderPdfError("PDF selection rectangle 无效")

    with _PDFIUM_LOCK:
        pdf = _open_pdf(path)
        page = None
        textpage = None
        try:
            count = _page_count(pdf)
            index = _page_index(page_id, count)
            page = _load_page(pdf, index)
            width, height, _rotation = _page_geometry(page)
            x0, x1 = sorted((values[0], values[2]))
            y0, y1 = sorted((values[1], values[3]))
            x0 = max(0.0, min(x0, width))
            x1 = max(0.0, min(x1, width))
            y0 = max(0.0, min(y0, height))
            y1 = max(0.0, min(y1, height))
            if x1 - x0 < 0.01 or y1 - y0 < 0.01:
                raise ReaderPdfError("PDF selection rectangle 为空")
            try:
                textpage = page.get_textpage()
                value = textpage.get_text_bounded(left=x0, bottom=y0, right=x1, top=y1)
            except Exception as exc:
                raise ReaderPdfError("PDF 区域文本提取失败") from exc
            text, truncated = _clean_text(value)
        finally:
            if textpage is not None:
                textpage.close()
            if page is not None:
                page.close()
            pdf.close()
    return {
        "bookId": clean,
        "pageId": _page_id(index + 1),
        "pageNumber": index + 1,
        "rect": _rect_payload((x0, y0, x1, y1)),
        "text": text,
        "truncated": truncated,
    }


def pdf_search(
    engine_module,
    book_id: object,
    query: object,
    *,
    start_page: object = 1,
    start_char: object = 0,
    max_pages: object = MAX_SEARCH_PAGES_PER_BATCH,
    limit: object = 200,
) -> dict[str, Any]:
    clean_query = " ".join(str(query or "").replace("\x00", " ").split()).strip()[:MAX_SEARCH_QUERY_CHARS]
    if not clean_query:
        raise ReaderPdfError("PDF search query 不能为空")
    try:
        first_page = max(1, int(start_page))
        first_char = max(0, int(start_char))
        batch_pages = max(1, min(int(max_pages), MAX_SEARCH_PAGES_PER_BATCH))
        safe_limit = max(1, min(int(limit), MAX_SEARCH_RESULTS))
    except (TypeError, ValueError) as exc:
        raise ReaderPdfError("PDF search 参数无效") from exc

    clean, path = _pdf_file(engine_module, book_id)
    results: list[dict[str, Any]] = []
    next_cursor: dict[str, int] | None = None
    with _PDFIUM_LOCK:
        pdf = _open_pdf(path)
        try:
            count = _page_count(pdf)
            if first_page > count:
                raise ReaderPdfError("PDF search 起始页不存在")
            final_page = min(count, first_page + batch_pages - 1)
            stop = False
            for page_number in range(first_page, final_page + 1):
                page = None
                textpage = None
                searcher = None
                try:
                    page = _load_page(pdf, page_number - 1)
                    width, height, _rotation = _page_geometry(page)
                    textpage = page.get_textpage()
                    page_start_char = first_char if page_number == first_page else 0
                    searcher = textpage.search(clean_query, index=page_start_char, match_case=False, match_whole_word=False)
                    while True:
                        match = searcher.get_next()
                        if match is None:
                            break
                        index, char_count = int(match[0]), int(match[1])
                        if char_count <= 0:
                            continue
                        snippet_start = max(0, index - 80)
                        snippet_count = min(MAX_PAGE_TEXT_CHARS, char_count + (index - snippet_start) + 120)
                        try:
                            snippet_raw = textpage.get_text_range(index=snippet_start, count=snippet_count)
                        except Exception:
                            snippet_raw = ""
                        snippet, _snippet_truncated = _clean_text(snippet_raw, limit=400)
                        rects, rects_truncated = _match_rects(textpage, index, char_count)
                        results.append(
                            {
                                "pageId": _page_id(page_number),
                                "pageNumber": page_number,
                                "index": index,
                                "length": char_count,
                                "snippet": snippet,
                                "snippetStart": snippet_start,
                                "pageWidth": round(width, 4),
                                "pageHeight": round(height, 4),
                                "rects": rects,
                                "rectsTruncated": rects_truncated,
                            }
                        )
                        if len(results) >= safe_limit:
                            next_cursor = {"pageNumber": page_number, "charIndex": index + char_count}
                            stop = True
                            break
                except ReaderPdfError:
                    raise
                except Exception as exc:
                    raise ReaderPdfError("PDF search 失败") from exc
                finally:
                    if searcher is not None:
                        searcher.close()
                    if textpage is not None:
                        textpage.close()
                    if page is not None:
                        page.close()
                if stop:
                    break
            if not stop and final_page < count:
                next_cursor = {"pageNumber": final_page + 1, "charIndex": 0}
        finally:
            pdf.close()

    return {
        "bookId": clean,
        "query": clean_query,
        "results": results,
        "truncated": next_cursor is not None,
        "next": next_cursor,
    }


def run_reader_pdf_self_test() -> None:
    assert _page_id(1) == "pdf-page:1"
    assert _page_index("pdf-page:2", 3) == 1
    assert _bounded_scale(612.0, 792.0, 1.0) == 1.0
    assert _bounded_scale(10_000.0, 10_000.0, 4.0) < 1.0
    try:
        _page_index("../page:1", 3)
    except ReaderPdfError:
        pass
    else:
        raise AssertionError("unsafe PDF page id was accepted")
