from __future__ import annotations

import math
import re
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import simpledialog, ttk
from typing import Any, Callable

from PIL import ImageTk

from reader_pdf import ReaderPdfError, pdf_document, pdf_search, pdf_text_in_rect, render_pdf_page
from reader_workspace import (
    ReaderWorkspaceError,
    add_annotation,
    add_bookmark,
    delete_annotation,
    delete_bookmark,
    list_annotations,
    list_bookmarks,
    update_reader_settings,
    update_reading_position,
)

_PAGE_RE = re.compile(r"^pdf-page:([1-9][0-9]{0,5})$")
_RECT_RE = re.compile(
    r"^(pdf-page:[1-9][0-9]{0,5})@rect:"
    r"([0-9]+(?:\.[0-9]+)?),([0-9]+(?:\.[0-9]+)?),"
    r"([0-9]+(?:\.[0-9]+)?),([0-9]+(?:\.[0-9]+)?)$"
)
_MIN_ZOOM = 0.25
_MAX_ZOOM = 4.0
_MAX_SEARCH_RESULTS = 500


class DesktopPdfReaderError(RuntimeError):
    pass


@dataclass(frozen=True)
class PdfRect:
    left: float
    bottom: float
    right: float
    top: float


@dataclass(frozen=True)
class PdfSelection:
    page_id: str
    rect: PdfRect
    text: str


def _bounded_zoom(value: object, default: float = 1.0) -> float:
    try:
        zoom = float(value)
    except (TypeError, ValueError):
        zoom = default
    if not math.isfinite(zoom):
        zoom = default
    return round(max(_MIN_ZOOM, min(zoom, _MAX_ZOOM)), 3)


def _page_locator(page_number: object) -> str:
    try:
        number = max(1, int(page_number))
    except (TypeError, ValueError):
        number = 1
    return f"pdf-page:{number}"


def _page_number_from_locator(locator: object, page_count: int, progress_percent: object = 0) -> int:
    total = max(1, int(page_count))
    text = str(locator or "").strip().lower()
    rect_match = _RECT_RE.fullmatch(text)
    page_text = rect_match.group(1) if rect_match is not None else text
    match = _PAGE_RE.fullmatch(page_text)
    if match is not None:
        return max(1, min(int(match.group(1)), total))
    try:
        progress = float(progress_percent)
    except (TypeError, ValueError):
        progress = 0.0
    if not math.isfinite(progress):
        progress = 0.0
    progress = max(0.0, min(progress, 100.0))
    return max(1, min(total, int(round((progress / 100.0) * max(total - 1, 0))) + 1))


def _progress_percent(page_number: int, page_count: int) -> float:
    total = max(1, int(page_count))
    number = max(1, min(int(page_number), total))
    return round((number / total) * 100.0, 4)


def _rect_locator(page_id: str, rect: PdfRect) -> str:
    return (
        f"{page_id}@rect:{rect.left:.4f},{rect.bottom:.4f},"
        f"{rect.right:.4f},{rect.top:.4f}"
    )


def _parse_rect_locator(value: object) -> tuple[str, PdfRect] | None:
    match = _RECT_RE.fullmatch(str(value or "").strip().lower())
    if match is None:
        return None
    values = [float(match.group(index)) for index in range(2, 6)]
    if not all(math.isfinite(value) for value in values):
        return None
    left, bottom, right, top = values
    if right <= left or top <= bottom:
        return None
    return match.group(1), PdfRect(left, bottom, right, top)


def _canvas_rect_to_pdf(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    origin: tuple[float, float],
    scale: float,
    page_width: float,
    page_height: float,
) -> PdfRect | None:
    safe_scale = _bounded_zoom(scale)
    ox, oy = origin
    x0, x1 = sorted((float(start[0]), float(end[0])))
    y0, y1 = sorted((float(start[1]), float(end[1])))
    x0 = max(ox, min(x0, ox + page_width * safe_scale))
    x1 = max(ox, min(x1, ox + page_width * safe_scale))
    y0 = max(oy, min(y0, oy + page_height * safe_scale))
    y1 = max(oy, min(y1, oy + page_height * safe_scale))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    left = (x0 - ox) / safe_scale
    right = (x1 - ox) / safe_scale
    top = page_height - ((y0 - oy) / safe_scale)
    bottom = page_height - ((y1 - oy) / safe_scale)
    left = max(0.0, min(left, page_width))
    right = max(0.0, min(right, page_width))
    bottom = max(0.0, min(bottom, page_height))
    top = max(0.0, min(top, page_height))
    if right - left < 0.01 or top - bottom < 0.01:
        return None
    return PdfRect(left, bottom, right, top)


def _pdf_rect_to_canvas(
    rect: PdfRect,
    *,
    origin: tuple[float, float],
    scale: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    safe_scale = _bounded_zoom(scale)
    ox, oy = origin
    return (
        ox + rect.left * safe_scale,
        oy + (page_height - rect.top) * safe_scale,
        ox + rect.right * safe_scale,
        oy + (page_height - rect.bottom) * safe_scale,
    )


def run_desktop_pdf_reader_self_test() -> None:
    assert _bounded_zoom(99) == 4.0
    assert _bounded_zoom("bad") == 1.0
    assert _page_locator(3) == "pdf-page:3"
    assert _page_number_from_locator("pdf-page:4", 5) == 4
    assert _page_number_from_locator("pdf-page:2@rect:1,2,3,4", 5) == 2
    assert _page_number_from_locator("legacy", 10, 50) == 5
    assert _progress_percent(2, 4) == 50.0
    rect = PdfRect(10.0, 20.0, 110.0, 220.0)
    locator = _rect_locator("pdf-page:2", rect)
    parsed = _parse_rect_locator(locator)
    assert parsed is not None and parsed[0] == "pdf-page:2" and parsed[1] == rect
    canvas_rect = _pdf_rect_to_canvas(rect, origin=(20.0, 30.0), scale=2.0, page_height=300.0)
    roundtrip = _canvas_rect_to_pdf(
        (canvas_rect[0], canvas_rect[1]),
        (canvas_rect[2], canvas_rect[3]),
        origin=(20.0, 30.0),
        scale=2.0,
        page_width=200.0,
        page_height=300.0,
    )
    assert roundtrip is not None
    assert abs(roundtrip.left - rect.left) < 0.001
    assert abs(roundtrip.bottom - rect.bottom) < 0.001
    assert abs(roundtrip.right - rect.right) < 0.001
    assert abs(roundtrip.top - rect.top) < 0.001


def show_pdf_reader(
    engine_module,
    book: dict[str, Any],
    *,
    parent: tk.Misc | None = None,
    on_change: Callable[[], None] | None = None,
) -> tk.Toplevel:
    if str(book.get("format") or "").strip().lower() != "pdf":
        raise DesktopPdfReaderError("当前书籍不是 PDF")
    book_id = str(book.get("id") or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32}", book_id):
        raise DesktopPdfReaderError("PDF Book ID 无效")

    window = tk.Toplevel(parent) if parent is not None else tk.Toplevel()
    window.title(f"PDF 阅读器 · {str(book.get('title') or 'Untitled')}")
    window.geometry("1280x840")
    window.minsize(900, 620)

    state: dict[str, Any] = {
        "closing": False,
        "pageCount": 0,
        "pageNumber": 1,
        "zoom": 1.0,
        "photo": None,
        "pageWidth": 0.0,
        "pageHeight": 0.0,
        "renderScale": 1.0,
        "origin": (24.0, 24.0),
        "renderBusy": False,
        "renderPending": False,
        "renderToken": 0,
        "searchToken": 0,
        "searchResults": [],
        "bookmarks": [],
        "annotations": [],
        "selection": None,
        "dragStart": None,
        "dragItem": None,
        "activeSearchRects": [],
    }

    settings = dict(book.get("settings") or {})
    focus_var = tk.BooleanVar(value=bool(settings.get("focusMode", False)))
    page_var = tk.StringVar(value="1")
    page_count_var = tk.StringVar(value="/ ?")
    zoom_var = tk.StringVar(value="100%")
    status_var = tk.StringVar(value="正在读取 PDF…")
    search_var = tk.StringVar(value="")

    outer = ttk.Frame(window, padding=10)
    outer.grid(row=0, column=0, sticky="nsew")
    window.rowconfigure(0, weight=1)
    window.columnconfigure(0, weight=1)
    outer.rowconfigure(1, weight=1)
    outer.columnconfigure(0, weight=1)

    header = ttk.Frame(outer)
    header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    header.columnconfigure(8, weight=1)

    previous_button = ttk.Button(header, text="上一页", width=8)
    previous_button.grid(row=0, column=0, padx=(0, 5), ipady=6)
    next_button = ttk.Button(header, text="下一页", width=8)
    next_button.grid(row=0, column=1, padx=(0, 10), ipady=6)
    ttk.Label(header, text="页").grid(row=0, column=2, padx=(0, 4))
    page_entry = ttk.Entry(header, textvariable=page_var, width=6)
    page_entry.grid(row=0, column=3, ipady=6)
    ttk.Label(header, textvariable=page_count_var).grid(row=0, column=4, padx=(4, 12))
    zoom_out_button = ttk.Button(header, text="−", width=3)
    zoom_out_button.grid(row=0, column=5, padx=(0, 3), ipady=6)
    ttk.Label(header, textvariable=zoom_var, width=7, anchor="center").grid(row=0, column=6)
    zoom_in_button = ttk.Button(header, text="+", width=3)
    zoom_in_button.grid(row=0, column=7, padx=(3, 10), ipady=6)
    fit_button = ttk.Button(header, text="适合页面")
    fit_button.grid(row=0, column=8, sticky="w", ipady=6)

    bookmark_button = ttk.Button(header, text="添加书签")
    bookmark_button.grid(row=0, column=9, padx=(8, 4), ipady=6)
    highlight_button = ttk.Button(header, text="高亮选区")
    highlight_button.grid(row=0, column=10, padx=4, ipady=6)
    note_button = ttk.Button(header, text="选区笔记")
    note_button.grid(row=0, column=11, padx=4, ipady=6)
    focus_check = ttk.Checkbutton(header, text="Focus", variable=focus_var)
    focus_check.grid(row=0, column=12, padx=(8, 0))

    body = ttk.Frame(outer)
    body.grid(row=1, column=0, sticky="nsew")
    body.rowconfigure(0, weight=1)
    body.columnconfigure(1, weight=1)

    sidebar = ttk.Frame(body, padding=(0, 0, 8, 0), width=330)
    sidebar.grid(row=0, column=0, sticky="nsew")
    sidebar.rowconfigure(0, weight=1)
    sidebar.columnconfigure(0, weight=1)

    sidebar_tabs = ttk.Notebook(sidebar)
    sidebar_tabs.grid(row=0, column=0, sticky="nsew")
    search_tab = ttk.Frame(sidebar_tabs, padding=8)
    bookmark_tab = ttk.Frame(sidebar_tabs, padding=8)
    annotation_tab = ttk.Frame(sidebar_tabs, padding=8)
    sidebar_tabs.add(search_tab, text="搜索")
    sidebar_tabs.add(bookmark_tab, text="书签")
    sidebar_tabs.add(annotation_tab, text="标注")

    search_tab.rowconfigure(1, weight=1)
    search_tab.columnconfigure(0, weight=1)
    search_row = ttk.Frame(search_tab)
    search_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    search_row.columnconfigure(0, weight=1)
    search_entry = ttk.Entry(search_row, textvariable=search_var)
    search_entry.grid(row=0, column=0, sticky="ew", ipady=6)
    search_button = ttk.Button(search_row, text="搜索")
    search_button.grid(row=0, column=1, padx=(6, 0), ipady=6)
    search_list = tk.Listbox(search_tab, exportselection=False, activestyle="none")
    search_list.grid(row=1, column=0, sticky="nsew")

    bookmark_tab.rowconfigure(0, weight=1)
    bookmark_tab.columnconfigure(0, weight=1)
    bookmark_list = tk.Listbox(bookmark_tab, exportselection=False, activestyle="none")
    bookmark_list.grid(row=0, column=0, sticky="nsew")
    delete_bookmark_button = ttk.Button(bookmark_tab, text="删除所选")
    delete_bookmark_button.grid(row=1, column=0, sticky="e", pady=(6, 0), ipady=5)

    annotation_tab.rowconfigure(0, weight=1)
    annotation_tab.columnconfigure(0, weight=1)
    annotation_list = tk.Listbox(annotation_tab, exportselection=False, activestyle="none")
    annotation_list.grid(row=0, column=0, sticky="nsew")
    delete_annotation_button = ttk.Button(annotation_tab, text="删除所选")
    delete_annotation_button.grid(row=1, column=0, sticky="e", pady=(6, 0), ipady=5)

    reader_panel = ttk.Frame(body)
    reader_panel.grid(row=0, column=1, sticky="nsew")
    reader_panel.rowconfigure(0, weight=1)
    reader_panel.columnconfigure(0, weight=1)
    canvas = tk.Canvas(reader_panel, bg="#5b5f63", highlightthickness=0, takefocus=True)
    x_scroll = ttk.Scrollbar(reader_panel, orient="horizontal", command=canvas.xview)
    y_scroll = ttk.Scrollbar(reader_panel, orient="vertical", command=canvas.yview)
    canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    y_scroll.grid(row=0, column=1, sticky="ns")
    x_scroll.grid(row=1, column=0, sticky="ew")

    footer = ttk.Frame(outer)
    footer.grid(row=2, column=0, sticky="ew", pady=(8, 0))
    footer.columnconfigure(0, weight=1)
    ttk.Label(footer, textvariable=status_var).grid(row=0, column=0, sticky="w")
    ttk.Label(
        footer,
        text="拖拽框选文本 · ←/→ 翻页 · +/- 缩放 · Ctrl+F 搜索 · Ctrl+B 书签 · Ctrl+H 高亮 · Ctrl+N 笔记 · F Focus",
    ).grid(row=0, column=1, sticky="e")

    def safe_after(callback: Callable[[], None]) -> None:
        if state["closing"]:
            return
        try:
            window.after(0, callback)
        except tk.TclError:
            pass

    def worker(function: Callable[[], Any], success: Callable[[Any], None], *, failure_prefix: str) -> None:
        def run() -> None:
            try:
                value = function()
            except (ReaderPdfError, ReaderWorkspaceError) as exc:
                safe_after(lambda: status_var.set(f"{failure_prefix}：{exc}"))
                return
            except Exception:
                safe_after(lambda: status_var.set(f"{failure_prefix}：内部处理失败"))
                return
            safe_after(lambda: success(value))

        threading.Thread(target=run, daemon=True).start()

    def current_page_id() -> str:
        return _page_locator(state["pageNumber"])

    def persist_position() -> None:
        if state["pageCount"] <= 0:
            return
        progress = _progress_percent(state["pageNumber"], state["pageCount"])
        locator = current_page_id()
        try:
            update_reading_position(engine_module, book_id, progress, locator)
            book["progressPercent"] = progress
            book["locator"] = locator
            if on_change is not None:
                on_change()
        except ReaderWorkspaceError:
            status_var.set("阅读位置保存失败")

    def refresh_sidebars() -> None:
        try:
            state["bookmarks"] = list_bookmarks(engine_module, book_id, limit=10_000)
            state["annotations"] = list_annotations(engine_module, book_id, limit=20_000)
        except ReaderWorkspaceError:
            status_var.set("书签/标注读取失败")
            return
        bookmark_list.delete(0, "end")
        for row in state["bookmarks"]:
            bookmark_list.insert("end", str(row.get("label") or row.get("locator") or "书签"))
        annotation_list.delete(0, "end")
        for row in state["annotations"]:
            kind = str(row.get("kind") or "highlight")
            locator = str(row.get("locator") or "")
            preview = " ".join(str(row.get("selectedText") or row.get("note") or "").split())
            if len(preview) > 70:
                preview = preview[:67] + "…"
            annotation_list.insert("end", f"{kind} · {locator} · {preview}")
        draw_overlays()

    def draw_overlays() -> None:
        canvas.delete("annotation-overlay")
        canvas.delete("search-overlay")
        if state["pageHeight"] <= 0 or state["renderScale"] <= 0:
            return
        page_id = current_page_id()
        for row in state["annotations"]:
            parsed = _parse_rect_locator(row.get("locator"))
            if parsed is None or parsed[0] != page_id:
                continue
            coords = _pdf_rect_to_canvas(
                parsed[1],
                origin=state["origin"],
                scale=state["renderScale"],
                page_height=state["pageHeight"],
            )
            canvas.create_rectangle(
                *coords,
                fill="#f5d547" if str(row.get("kind")) == "highlight" else "#85b7ff",
                stipple="gray25",
                outline="#a47b00" if str(row.get("kind")) == "highlight" else "#2f6fb3",
                width=2,
                tags="annotation-overlay",
            )
        for rect_data in state["activeSearchRects"]:
            try:
                rect = PdfRect(
                    float(rect_data["left"]),
                    float(rect_data["bottom"]),
                    float(rect_data["right"]),
                    float(rect_data["top"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            coords = _pdf_rect_to_canvas(
                rect,
                origin=state["origin"],
                scale=state["renderScale"],
                page_height=state["pageHeight"],
            )
            canvas.create_rectangle(*coords, outline="#e53935", width=3, tags="search-overlay")

    def finish_render(rendered, token: int) -> None:  # noqa: ANN001
        state["renderBusy"] = False
        if state["closing"]:
            return
        if token != state["renderToken"]:
            if state["renderPending"]:
                state["renderPending"] = False
                start_render()
            return
        state["pageCount"] = int(rendered.page_count)
        state["pageNumber"] = int(rendered.page_number)
        state["pageWidth"] = float(rendered.width_points)
        state["pageHeight"] = float(rendered.height_points)
        state["renderScale"] = float(rendered.scale)
        photo = ImageTk.PhotoImage(rendered.image)
        state["photo"] = photo
        canvas.delete("all")
        ox, oy = state["origin"]
        canvas.create_image(ox, oy, image=photo, anchor="nw", tags="page-image")
        canvas.configure(scrollregion=(0, 0, max(photo.width() + ox * 2, canvas.winfo_width()), max(photo.height() + oy * 2, canvas.winfo_height())))
        page_var.set(str(state["pageNumber"]))
        page_count_var.set(f"/ {state['pageCount']}")
        zoom_var.set(f"{round(state['renderScale'] * 100):d}%")
        status_var.set(f"第 {state['pageNumber']} / {state['pageCount']} 页")
        draw_overlays()
        persist_position()
        if state["renderPending"]:
            state["renderPending"] = False
            start_render()

    def start_render() -> None:
        if state["pageCount"] <= 0 or state["closing"]:
            return
        if state["renderBusy"]:
            state["renderPending"] = True
            return
        state["renderBusy"] = True
        state["renderToken"] += 1
        token = state["renderToken"]
        page_id = current_page_id()
        requested_zoom = state["zoom"]
        status_var.set("正在渲染 PDF…")

        def success(rendered) -> None:  # noqa: ANN001
            finish_render(rendered, token)

        def render_call():  # noqa: ANN202
            return render_pdf_page(engine_module, book_id, page_id, scale=requested_zoom)

        def run() -> None:
            try:
                rendered = render_call()
            except (ReaderPdfError, ReaderWorkspaceError) as exc:
                safe_after(lambda: render_failed(token, str(exc)))
                return
            except Exception:
                safe_after(lambda: render_failed(token, "内部处理失败"))
                return
            safe_after(lambda: success(rendered))

        threading.Thread(target=run, daemon=True).start()

    def render_failed(token: int, detail: str) -> None:
        state["renderBusy"] = False
        if token == state["renderToken"]:
            status_var.set(f"PDF 渲染失败：{detail}")
        if state["renderPending"]:
            state["renderPending"] = False
            start_render()

    def go_page(value: object, *, search_rects: list[dict[str, float]] | None = None) -> None:
        if state["pageCount"] <= 0:
            return
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = state["pageNumber"]
        number = max(1, min(number, state["pageCount"]))
        state["pageNumber"] = number
        state["selection"] = None
        state["activeSearchRects"] = list(search_rects or [])
        start_render()

    def navigate(delta: int) -> None:
        go_page(state["pageNumber"] + int(delta))

    def set_zoom(value: float) -> None:
        state["zoom"] = _bounded_zoom(value)
        start_render()

    def fit_page() -> None:
        if state["pageWidth"] <= 0 or state["pageHeight"] <= 0:
            return
        canvas.update_idletasks()
        width = max(200, canvas.winfo_width() - 56)
        height = max(200, canvas.winfo_height() - 56)
        scale = min(width / state["pageWidth"], height / state["pageHeight"])
        set_zoom(scale)

    def add_current_bookmark() -> None:
        if state["pageCount"] <= 0:
            return
        try:
            add_bookmark(engine_module, book_id, current_page_id(), label=f"第 {state['pageNumber']} 页")
            status_var.set("书签已添加")
            refresh_sidebars()
        except ReaderWorkspaceError as exc:
            status_var.set(f"书签添加失败：{exc}")

    def remove_selected_bookmark() -> None:
        selection = bookmark_list.curselection()
        if not selection:
            status_var.set("请先选择书签")
            return
        row = state["bookmarks"][selection[0]]
        try:
            if not delete_bookmark(engine_module, row.get("id")):
                raise ReaderWorkspaceError("Bookmark 不存在")
            refresh_sidebars()
            status_var.set("书签已删除")
        except ReaderWorkspaceError as exc:
            status_var.set(f"书签删除失败：{exc}")

    def open_selected_bookmark(*_args) -> None:
        selection = bookmark_list.curselection()
        if not selection:
            return
        row = state["bookmarks"][selection[0]]
        go_page(_page_number_from_locator(row.get("locator"), state["pageCount"]))

    def save_selection(kind: str) -> None:
        selection: PdfSelection | None = state.get("selection")
        if selection is None:
            status_var.set("请先在页面上拖拽框选文本")
            return
        note = ""
        if kind == "note":
            value = simpledialog.askstring("PDF 笔记", "为当前选区添加笔记：", parent=window)
            if value is None:
                return
            note = value.strip()
            if not note:
                status_var.set("笔记内容不能为空")
                return
        try:
            add_annotation(
                engine_module,
                book_id,
                _rect_locator(selection.page_id, selection.rect),
                kind=kind,
                selected_text=selection.text,
                note=note,
            )
            status_var.set("高亮已保存" if kind == "highlight" else "笔记已保存")
            refresh_sidebars()
        except ReaderWorkspaceError as exc:
            status_var.set(f"标注保存失败：{exc}")

    def remove_selected_annotation() -> None:
        selection = annotation_list.curselection()
        if not selection:
            status_var.set("请先选择标注")
            return
        row = state["annotations"][selection[0]]
        try:
            if not delete_annotation(engine_module, row.get("id")):
                raise ReaderWorkspaceError("Annotation 不存在")
            refresh_sidebars()
            status_var.set("标注已删除")
        except ReaderWorkspaceError as exc:
            status_var.set(f"标注删除失败：{exc}")

    def open_selected_annotation(*_args) -> None:
        selection = annotation_list.curselection()
        if not selection:
            return
        row = state["annotations"][selection[0]]
        parsed = _parse_rect_locator(row.get("locator"))
        if parsed is None:
            go_page(_page_number_from_locator(row.get("locator"), state["pageCount"]))
            return
        page_id, rect = parsed
        go_page(_page_number_from_locator(page_id, state["pageCount"]), search_rects=[{
            "left": rect.left,
            "bottom": rect.bottom,
            "right": rect.right,
            "top": rect.top,
        }])

    def run_search() -> None:
        query = " ".join(search_var.get().split()).strip()
        if not query:
            status_var.set("请输入 PDF 搜索关键词")
            return
        state["searchToken"] += 1
        token = state["searchToken"]
        search_list.delete(0, "end")
        state["searchResults"] = []
        status_var.set("正在搜索整个 PDF…")

        def search_call() -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []
            page_number = 1
            char_index = 0
            seen: set[tuple[int, int]] = set()
            while len(results) < _MAX_SEARCH_RESULTS:
                response = pdf_search(
                    engine_module,
                    book_id,
                    query,
                    start_page=page_number,
                    start_char=char_index,
                    max_pages=50,
                    limit=min(100, _MAX_SEARCH_RESULTS - len(results)),
                )
                results.extend(list(response.get("results") or []))
                cursor = response.get("next")
                if not cursor:
                    break
                next_page = int(cursor.get("pageNumber") or 0)
                next_char = int(cursor.get("charIndex") or 0)
                key = (next_page, next_char)
                if next_page <= 0 or key in seen:
                    break
                seen.add(key)
                page_number, char_index = key
            return results[:_MAX_SEARCH_RESULTS]

        def success(results: list[dict[str, Any]]) -> None:
            if token != state["searchToken"] or state["closing"]:
                return
            state["searchResults"] = results
            search_list.delete(0, "end")
            for row in results:
                snippet = " ".join(str(row.get("snippet") or "").split())
                if len(snippet) > 90:
                    snippet = snippet[:87] + "…"
                search_list.insert("end", f"P{row.get('pageNumber')} · {snippet}")
            status_var.set(f"搜索完成：{len(results)} 个结果" + ("（已达 500 上限）" if len(results) >= _MAX_SEARCH_RESULTS else ""))

        worker(search_call, success, failure_prefix="PDF 搜索失败")

    def open_selected_search(*_args) -> None:
        selection = search_list.curselection()
        if not selection:
            return
        row = state["searchResults"][selection[0]]
        go_page(row.get("pageNumber") or 1, search_rects=list(row.get("rects") or []))

    def apply_focus(*_args) -> None:
        enabled = bool(focus_var.get())
        if enabled:
            sidebar.grid_remove()
            body.columnconfigure(0, weight=0)
        else:
            sidebar.grid()
            body.columnconfigure(0, weight=0)
        try:
            saved = update_reader_settings(engine_module, book_id, {"focusMode": enabled})
            book["settings"] = saved
        except ReaderWorkspaceError:
            status_var.set("Focus Mode 保存失败")
        canvas.focus_set()

    def on_canvas_press(event: tk.Event) -> None:
        if state["pageHeight"] <= 0 or state["renderScale"] <= 0:
            return
        x = float(canvas.canvasx(event.x))
        y = float(canvas.canvasy(event.y))
        ox, oy = state["origin"]
        width = state["pageWidth"] * state["renderScale"]
        height = state["pageHeight"] * state["renderScale"]
        if not (ox <= x <= ox + width and oy <= y <= oy + height):
            return
        state["dragStart"] = (x, y)
        state["selection"] = None
        if state["dragItem"] is not None:
            canvas.delete(state["dragItem"])
        state["dragItem"] = canvas.create_rectangle(x, y, x, y, outline="#2f6fb3", width=2, dash=(5, 3))

    def on_canvas_drag(event: tk.Event) -> None:
        start = state.get("dragStart")
        item = state.get("dragItem")
        if start is None or item is None:
            return
        x = float(canvas.canvasx(event.x))
        y = float(canvas.canvasy(event.y))
        canvas.coords(item, start[0], start[1], x, y)

    def on_canvas_release(event: tk.Event) -> None:
        start = state.get("dragStart")
        state["dragStart"] = None
        if start is None:
            return
        end = (float(canvas.canvasx(event.x)), float(canvas.canvasy(event.y)))
        rect = _canvas_rect_to_pdf(
            start,
            end,
            origin=state["origin"],
            scale=state["renderScale"],
            page_width=state["pageWidth"],
            page_height=state["pageHeight"],
        )
        if rect is None:
            status_var.set("选区太小")
            return
        page_id = current_page_id()
        status_var.set("正在提取选区文本…")

        def extract_call():  # noqa: ANN202
            return pdf_text_in_rect(
                engine_module,
                book_id,
                page_id,
                left=rect.left,
                bottom=rect.bottom,
                right=rect.right,
                top=rect.top,
            )

        def success(payload: dict[str, Any]) -> None:
            if page_id != current_page_id() or state["closing"]:
                return
            text = str(payload.get("text") or "").strip()
            if not text:
                state["selection"] = None
                status_var.set("选区没有可提取文本")
                return
            state["selection"] = PdfSelection(page_id, rect, text)
            preview = " ".join(text.split())
            if len(preview) > 100:
                preview = preview[:97] + "…"
            status_var.set(f"已选中文本：{preview}")

        worker(extract_call, success, failure_prefix="PDF 选区失败")

    def load_document() -> None:
        status_var.set("正在读取 PDF…")

        def success(document: dict[str, Any]) -> None:
            state["pageCount"] = int(document.get("pageCount") or 0)
            if state["pageCount"] <= 0:
                status_var.set("PDF 没有可阅读页面")
                return
            state["pageNumber"] = _page_number_from_locator(
                book.get("locator"),
                state["pageCount"],
                book.get("progressPercent"),
            )
            page_count_var.set(f"/ {state['pageCount']}")
            page_var.set(str(state["pageNumber"]))
            refresh_sidebars()
            start_render()
            apply_focus()

        worker(lambda: pdf_document(engine_module, book_id), success, failure_prefix="PDF 打开失败")

    previous_button.configure(command=lambda: navigate(-1))
    next_button.configure(command=lambda: navigate(1))
    zoom_out_button.configure(command=lambda: set_zoom(state["zoom"] / 1.25))
    zoom_in_button.configure(command=lambda: set_zoom(state["zoom"] * 1.25))
    fit_button.configure(command=fit_page)
    bookmark_button.configure(command=add_current_bookmark)
    highlight_button.configure(command=lambda: save_selection("highlight"))
    note_button.configure(command=lambda: save_selection("note"))
    focus_check.configure(command=apply_focus)
    search_button.configure(command=run_search)
    delete_bookmark_button.configure(command=remove_selected_bookmark)
    delete_annotation_button.configure(command=remove_selected_annotation)

    page_entry.bind("<Return>", lambda _event: go_page(page_var.get()))
    search_entry.bind("<Return>", lambda _event: run_search())
    search_list.bind("<Double-Button-1>", open_selected_search)
    search_list.bind("<Return>", open_selected_search)
    bookmark_list.bind("<Double-Button-1>", open_selected_bookmark)
    bookmark_list.bind("<Return>", open_selected_bookmark)
    annotation_list.bind("<Double-Button-1>", open_selected_annotation)
    annotation_list.bind("<Return>", open_selected_annotation)
    canvas.bind("<ButtonPress-1>", on_canvas_press)
    canvas.bind("<B1-Motion>", on_canvas_drag)
    canvas.bind("<ButtonRelease-1>", on_canvas_release)

    def keyboard(event: tk.Event) -> str | None:
        key = str(event.keysym or "")
        lower = key.lower()
        control = bool(event.state & 0x4)
        if control and lower == "f":
            if focus_var.get():
                focus_var.set(False)
                apply_focus()
            sidebar_tabs.select(search_tab)
            search_entry.focus_set()
            return "break"
        if control and lower == "b":
            add_current_bookmark()
            return "break"
        if control and lower == "h":
            save_selection("highlight")
            return "break"
        if control and lower == "n":
            save_selection("note")
            return "break"
        if key in {"Right", "Next"}:
            navigate(1)
            return "break"
        if key in {"Left", "Prior"}:
            navigate(-1)
            return "break"
        if key == "Home":
            go_page(1)
            return "break"
        if key == "End":
            go_page(state["pageCount"])
            return "break"
        if key in {"plus", "equal", "KP_Add"}:
            set_zoom(state["zoom"] * 1.25)
            return "break"
        if key in {"minus", "KP_Subtract"}:
            set_zoom(state["zoom"] / 1.25)
            return "break"
        if key == "0" and control:
            set_zoom(1.0)
            return "break"
        if lower == "f" and not control:
            focus_var.set(not focus_var.get())
            apply_focus()
            return "break"
        if key == "Escape":
            if focus_var.get():
                focus_var.set(False)
                apply_focus()
            else:
                close()
            return "break"
        return None

    window.bind("<Key>", keyboard)

    def close() -> None:
        if state["closing"]:
            return
        state["closing"] = True
        if on_change is not None:
            try:
                on_change()
            except Exception:
                pass
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    load_document()
    canvas.focus_set()
    return window
