from __future__ import annotations

import re
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable

from reader_epub import EpubDocumentError, epub_chapter, epub_document
from reader_epub_search import EpubSearchError, epub_search
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

_POSITION_RE = re.compile(r"^(epub-chapter:\d{1,5})@char:(\d{1,8})$")
_RANGE_RE = re.compile(r"^(epub-chapter:\d{1,5})@chars:(\d{1,8})-(\d{1,8})$")
_THEMES = ("system", "light", "dark", "sepia")
_MAX_BOOKMARKS = 10_000
_MAX_ANNOTATIONS = 20_000


class DesktopEpubReaderError(RuntimeError):
    pass


@dataclass(frozen=True)
class EpubPosition:
    chapter_id: str
    offset: int


@dataclass(frozen=True)
class EpubRange:
    chapter_id: str
    start: int
    end: int


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(parsed, high))


def _normalize_settings(book: dict[str, Any]) -> dict[str, Any]:
    settings = dict(book.get("settings") or {})
    theme = str(settings.get("theme") or "system").strip().lower()
    if theme not in _THEMES:
        theme = "system"
    return {
        "fontSize": _bounded_int(settings.get("fontSize"), 18, 10, 72),
        "contentWidth": _bounded_int(settings.get("contentWidth"), 820, 320, 1800),
        "theme": theme,
        "focusMode": bool(settings.get("focusMode", False)),
    }


def _position_locator(chapter_id: str, offset: int) -> str:
    return f"{chapter_id}@char:{max(0, int(offset))}"


def _range_locator(chapter_id: str, start: int, end: int) -> str:
    low = max(0, int(start))
    high = max(low, int(end))
    return f"{chapter_id}@chars:{low}-{high}"


def _parse_position_locator(value: object, chapter_ids: set[str]) -> EpubPosition | None:
    match = _POSITION_RE.fullmatch(str(value or "").strip())
    if match is None or match.group(1) not in chapter_ids:
        return None
    return EpubPosition(match.group(1), max(0, int(match.group(2))))


def _parse_range_locator(value: object, chapter_ids: set[str], text_length: int | None = None) -> EpubRange | None:
    match = _RANGE_RE.fullmatch(str(value or "").strip())
    if match is None or match.group(1) not in chapter_ids:
        return None
    start = max(0, int(match.group(2)))
    end = max(start, int(match.group(3)))
    if text_length is not None:
        if start > text_length:
            return None
        end = min(end, text_length)
    if end <= start:
        return None
    return EpubRange(match.group(1), start, end)


def _progress_percent(chapter_index: int, chapter_count: int, offset: int, text_length: int) -> float:
    total = max(1, int(chapter_count))
    index = max(0, min(int(chapter_index), total - 1))
    fraction = 0.0 if text_length <= 0 else max(0.0, min(float(offset) / float(text_length), 1.0))
    return round(((index + fraction) / total) * 100.0, 4)


def _initial_chapter(book: dict[str, Any], chapter_ids: list[str]) -> EpubPosition:
    if not chapter_ids:
        raise DesktopEpubReaderError("EPUB 没有可阅读章节")
    parsed = _parse_position_locator(book.get("locator"), set(chapter_ids))
    if parsed is not None:
        return parsed
    try:
        progress = float(book.get("progressPercent") or 0.0)
    except (TypeError, ValueError):
        progress = 0.0
    progress = max(0.0, min(progress, 100.0))
    index = min(len(chapter_ids) - 1, int((progress / 100.0) * len(chapter_ids)))
    return EpubPosition(chapter_ids[index], 0)


def _text_columns(content_width: int, font_size: int) -> int:
    estimated = int(content_width / max(6.0, font_size * 0.58))
    return max(32, min(180, estimated))


def _theme_palette(theme: str, system_bg: str = "#ffffff", system_fg: str = "#202124") -> tuple[str, str, str, str]:
    clean = theme if theme in _THEMES else "system"
    if clean == "dark":
        return "#202124", "#f1f3f4", "#5f531f", "#3a4b62"
    if clean == "sepia":
        return "#f4ecd8", "#3b2f2f", "#ead58b", "#d8e0c2"
    if clean == "light":
        return "#ffffff", "#202124", "#fff1a8", "#dbeafe"
    return system_bg, system_fg, "#fff1a8", "#dbeafe"


def run_desktop_epub_reader_self_test() -> None:
    ids = {"epub-chapter:1", "epub-chapter:2"}
    assert _position_locator("epub-chapter:1", 12) == "epub-chapter:1@char:12"
    assert _range_locator("epub-chapter:2", 10, 20) == "epub-chapter:2@chars:10-20"
    assert _parse_position_locator("epub-chapter:1@char:99", ids) == EpubPosition("epub-chapter:1", 99)
    assert _parse_position_locator("epub-chapter:9@char:1", ids) is None
    assert _parse_range_locator("epub-chapter:2@chars:3-9", ids, 20) == EpubRange("epub-chapter:2", 3, 9)
    assert _parse_range_locator("epub-chapter:2@chars:9-9", ids, 20) is None
    assert _progress_percent(0, 2, 50, 100) == 25.0
    assert _progress_percent(1, 2, 100, 100) == 100.0
    assert _text_columns(820, 18) >= 32
    assert _normalize_settings({"settings": {"fontSize": 500, "contentWidth": 1, "theme": "bad"}}) == {
        "fontSize": 72,
        "contentWidth": 320,
        "theme": "system",
        "focusMode": False,
    }


def show_epub_reader(
    engine_module,
    book: dict[str, Any],
    *,
    parent: tk.Misc | None = None,
    on_change: Callable[[], None] | None = None,
) -> tk.Toplevel:
    if str(book.get("format") or "").strip().lower() != "epub":
        raise DesktopEpubReaderError("当前书籍不是 EPUB")
    book_id = str(book.get("id") or "").strip()
    if not book_id:
        raise DesktopEpubReaderError("EPUB Book ID 无效")

    try:
        document = epub_document(engine_module, book_id)
    except (EpubDocumentError, ReaderWorkspaceError) as exc:
        raise DesktopEpubReaderError(str(exc)) from exc
    chapters = list(document.get("chapters") or [])
    if not chapters:
        raise DesktopEpubReaderError("EPUB 没有可阅读章节")
    chapter_ids = [str(row.get("id") or "") for row in chapters]
    chapter_id_set = set(chapter_ids)
    chapter_index = {chapter_id: index for index, chapter_id in enumerate(chapter_ids)}
    toc_rows = list(document.get("toc") or [])
    settings = _normalize_settings(book)

    window = tk.Toplevel(parent) if parent is not None else tk.Toplevel()
    window.title(f"EPUB 阅读器 · {str(book.get('title') or 'Untitled')}")
    window.geometry("1240x820")
    window.minsize(900, 620)

    state: dict[str, Any] = {
        "chapterId": "",
        "chapterIndex": 0,
        "text": "",
        "bookmarks": [],
        "annotations": [],
        "searchResults": [],
        "sidebarVisible": True,
        "closing": False,
    }

    font_var = tk.IntVar(value=settings["fontSize"])
    width_var = tk.IntVar(value=settings["contentWidth"])
    theme_var = tk.StringVar(value=settings["theme"])
    focus_var = tk.BooleanVar(value=settings["focusMode"])
    chapter_var = tk.StringVar(value="")
    status_var = tk.StringVar(value="")
    search_var = tk.StringVar(value="")

    outer = ttk.Frame(window, padding=12)
    outer.grid(row=0, column=0, sticky="nsew")
    window.rowconfigure(0, weight=1)
    window.columnconfigure(0, weight=1)
    outer.rowconfigure(1, weight=1)
    outer.columnconfigure(0, weight=1)

    header = ttk.Frame(outer)
    header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    header.columnconfigure(2, weight=1)
    previous_button = ttk.Button(header, text="上一章")
    previous_button.grid(row=0, column=0, padx=(0, 6), ipady=7)
    next_button = ttk.Button(header, text="下一章")
    next_button.grid(row=0, column=1, padx=(0, 10), ipady=7)
    ttk.Label(header, textvariable=chapter_var).grid(row=0, column=2, sticky="w")

    settings_frame = ttk.Frame(header)
    settings_frame.grid(row=0, column=3, sticky="e")
    ttk.Label(settings_frame, text="字号").grid(row=0, column=0, padx=(0, 4))
    font_spin = ttk.Spinbox(settings_frame, from_=10, to=72, width=4, textvariable=font_var)
    font_spin.grid(row=0, column=1, padx=(0, 8), ipady=5)
    ttk.Label(settings_frame, text="宽度").grid(row=0, column=2, padx=(0, 4))
    width_spin = ttk.Spinbox(settings_frame, from_=320, to=1800, increment=20, width=6, textvariable=width_var)
    width_spin.grid(row=0, column=3, padx=(0, 8), ipady=5)
    ttk.Label(settings_frame, text="主题").grid(row=0, column=4, padx=(0, 4))
    theme_combo = ttk.Combobox(settings_frame, values=_THEMES, state="readonly", width=8, textvariable=theme_var)
    theme_combo.grid(row=0, column=5, padx=(0, 8), ipady=5)
    focus_check = ttk.Checkbutton(settings_frame, text="Focus", variable=focus_var)
    focus_check.grid(row=0, column=6, padx=(0, 4))

    body = ttk.Panedwindow(outer, orient="horizontal")
    body.grid(row=1, column=0, sticky="nsew")

    sidebar = ttk.Frame(body, padding=(0, 0, 8, 0), width=330)
    reader_panel = ttk.Frame(body)
    body.add(sidebar, weight=0)
    body.add(reader_panel, weight=1)
    sidebar.rowconfigure(0, weight=1)
    sidebar.columnconfigure(0, weight=1)
    reader_panel.rowconfigure(0, weight=1)
    reader_panel.columnconfigure(0, weight=1)

    sidebar_tabs = ttk.Notebook(sidebar)
    sidebar_tabs.grid(row=0, column=0, sticky="nsew")
    toc_tab = ttk.Frame(sidebar_tabs, padding=8)
    search_tab = ttk.Frame(sidebar_tabs, padding=8)
    bookmark_tab = ttk.Frame(sidebar_tabs, padding=8)
    annotation_tab = ttk.Frame(sidebar_tabs, padding=8)
    sidebar_tabs.add(toc_tab, text="目录")
    sidebar_tabs.add(search_tab, text="搜索")
    sidebar_tabs.add(bookmark_tab, text="书签")
    sidebar_tabs.add(annotation_tab, text="标注")

    toc_tab.rowconfigure(0, weight=1)
    toc_tab.columnconfigure(0, weight=1)
    toc_list = tk.Listbox(toc_tab, exportselection=False, activestyle="dotbox")
    toc_list.grid(row=0, column=0, sticky="nsew")
    toc_scroll = ttk.Scrollbar(toc_tab, orient="vertical", command=toc_list.yview)
    toc_scroll.grid(row=0, column=1, sticky="ns")
    toc_list.configure(yscrollcommand=toc_scroll.set)
    toc_targets: list[str] = []
    for row in toc_rows:
        target = str(row.get("chapterId") or "")
        if target not in chapter_id_set:
            continue
        depth = _bounded_int(row.get("depth"), 0, 0, 32)
        title = str(row.get("title") or target).strip()[:240]
        toc_list.insert("end", ("  " * depth) + title)
        toc_targets.append(target)

    search_tab.rowconfigure(1, weight=1)
    search_tab.columnconfigure(0, weight=1)
    search_bar = ttk.Frame(search_tab)
    search_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    search_bar.columnconfigure(0, weight=1)
    search_entry = ttk.Entry(search_bar, textvariable=search_var)
    search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6), ipady=6)
    search_button = ttk.Button(search_bar, text="搜索")
    search_button.grid(row=0, column=1, ipady=6)
    search_list = tk.Listbox(search_tab, exportselection=False, activestyle="dotbox")
    search_list.grid(row=1, column=0, sticky="nsew")
    search_scroll = ttk.Scrollbar(search_tab, orient="vertical", command=search_list.yview)
    search_scroll.grid(row=1, column=1, sticky="ns")
    search_list.configure(yscrollcommand=search_scroll.set)

    bookmark_tab.rowconfigure(0, weight=1)
    bookmark_tab.columnconfigure(0, weight=1)
    bookmark_list = tk.Listbox(bookmark_tab, exportselection=False, activestyle="dotbox")
    bookmark_list.grid(row=0, column=0, columnspan=2, sticky="nsew")
    bookmark_scroll = ttk.Scrollbar(bookmark_tab, orient="vertical", command=bookmark_list.yview)
    bookmark_scroll.grid(row=0, column=2, sticky="ns")
    bookmark_list.configure(yscrollcommand=bookmark_scroll.set)
    add_bookmark_button = ttk.Button(bookmark_tab, text="添加当前书签")
    add_bookmark_button.grid(row=1, column=0, sticky="ew", pady=(8, 0), padx=(0, 4), ipady=7)
    delete_bookmark_button = ttk.Button(bookmark_tab, text="删除")
    delete_bookmark_button.grid(row=1, column=1, sticky="ew", pady=(8, 0), ipady=7)

    annotation_tab.rowconfigure(0, weight=1)
    annotation_tab.columnconfigure(0, weight=1)
    annotation_list = tk.Listbox(annotation_tab, exportselection=False, activestyle="dotbox")
    annotation_list.grid(row=0, column=0, columnspan=3, sticky="nsew")
    annotation_scroll = ttk.Scrollbar(annotation_tab, orient="vertical", command=annotation_list.yview)
    annotation_scroll.grid(row=0, column=3, sticky="ns")
    annotation_list.configure(yscrollcommand=annotation_scroll.set)
    highlight_button = ttk.Button(annotation_tab, text="高亮选中")
    highlight_button.grid(row=1, column=0, sticky="ew", pady=(8, 0), padx=(0, 4), ipady=7)
    note_button = ttk.Button(annotation_tab, text="添加笔记")
    note_button.grid(row=1, column=1, sticky="ew", pady=(8, 0), padx=(0, 4), ipady=7)
    delete_annotation_button = ttk.Button(annotation_tab, text="删除")
    delete_annotation_button.grid(row=1, column=2, sticky="ew", pady=(8, 0), ipady=7)

    text_host = ttk.Frame(reader_panel)
    text_host.grid(row=0, column=0, sticky="nsew")
    text_host.rowconfigure(0, weight=1)
    text_host.columnconfigure(0, weight=1)
    reader_text = tk.Text(
        text_host,
        wrap="word",
        undo=False,
        exportselection=True,
        padx=24,
        pady=24,
        relief="flat",
        borderwidth=0,
        cursor="arrow",
    )
    reader_text.grid(row=0, column=0, sticky="nsew")
    text_scroll = ttk.Scrollbar(text_host, orient="vertical", command=reader_text.yview)
    text_scroll.grid(row=0, column=1, sticky="ns")
    reader_text.configure(yscrollcommand=text_scroll.set)

    footer = ttk.Frame(outer)
    footer.grid(row=2, column=0, sticky="ew", pady=(8, 0))
    footer.columnconfigure(0, weight=1)
    ttk.Label(footer, textvariable=status_var).grid(row=0, column=0, sticky="w")
    ttk.Label(footer, text="Ctrl+F 搜索 · Ctrl+B 书签 · Ctrl+H 高亮 · Ctrl+N 笔记 · Esc 退出 Focus").grid(row=0, column=1, sticky="e")

    def notify_change() -> None:
        if callable(on_change):
            try:
                on_change()
            except Exception:
                pass

    def current_offset() -> int:
        try:
            visible_top = reader_text.index("@0,0")
            return max(0, int(reader_text.count("1.0", visible_top, "chars")[0]))
        except Exception:
            return 0

    def select_range(start: int, end: int, tag: str = "search_hit") -> None:
        length = len(state["text"])
        low = max(0, min(int(start), length))
        high = max(low, min(int(end), length))
        reader_text.tag_remove("search_hit", "1.0", "end")
        if high > low:
            start_index = f"1.0+{low}c"
            end_index = f"1.0+{high}c"
            reader_text.tag_add(tag, start_index, end_index)
            reader_text.mark_set("insert", start_index)
            reader_text.see(start_index)
            reader_text.focus_set()

    def apply_theme_and_width(*_args) -> None:
        font_size = _bounded_int(font_var.get(), 18, 10, 72)
        width = _bounded_int(width_var.get(), 820, 320, 1800)
        theme = str(theme_var.get() or "system").strip().lower()
        if theme not in _THEMES:
            theme = "system"
            theme_var.set(theme)
        try:
            style = ttk.Style(window)
            system_bg = str(style.lookup("TFrame", "background") or "#ffffff")
            system_fg = str(style.lookup("TLabel", "foreground") or "#202124")
        except Exception:
            system_bg = "#ffffff"
            system_fg = "#202124"
        bg, fg, highlight_bg, search_bg = _theme_palette(theme, system_bg, system_fg)
        reader_text.configure(
            font=("TkDefaultFont", font_size),
            width=_text_columns(width, font_size),
            background=bg,
            foreground=fg,
            insertbackground=fg,
            selectbackground=search_bg,
        )
        reader_text.tag_configure("saved_highlight", background=highlight_bg)
        reader_text.tag_configure("saved_note", underline=True)
        reader_text.tag_configure("search_hit", background=search_bg, underline=True)

    def refresh_bookmarks() -> None:
        try:
            rows = list_bookmarks(engine_module, book_id, limit=_MAX_BOOKMARKS)
        except ReaderWorkspaceError:
            rows = []
        state["bookmarks"] = rows
        bookmark_list.delete(0, "end")
        for item in rows:
            label = str(item.get("label") or item.get("locator") or "书签").strip()[:240]
            bookmark_list.insert("end", label)

    def refresh_annotations() -> None:
        try:
            rows = list_annotations(engine_module, book_id, limit=_MAX_ANNOTATIONS)
        except ReaderWorkspaceError:
            rows = []
        state["annotations"] = rows
        annotation_list.delete(0, "end")
        for item in rows:
            kind = "高亮" if item.get("kind") == "highlight" else "笔记"
            preview = str(item.get("selectedText") or item.get("note") or item.get("locator") or "").replace("\n", " ").strip()
            annotation_list.insert("end", f"{kind} · {preview[:100]}")
        render_saved_annotations()

    def render_saved_annotations() -> None:
        reader_text.tag_remove("saved_highlight", "1.0", "end")
        reader_text.tag_remove("saved_note", "1.0", "end")
        chapter_id = state["chapterId"]
        if not chapter_id:
            return
        for item in state.get("annotations", []):
            parsed = _parse_range_locator(item.get("locator"), chapter_id_set, len(state["text"]))
            if parsed is None or parsed.chapter_id != chapter_id:
                continue
            tag = "saved_highlight" if item.get("kind") == "highlight" else "saved_note"
            reader_text.tag_add(tag, f"1.0+{parsed.start}c", f"1.0+{parsed.end}c")

    def persist_position() -> None:
        chapter_id = state["chapterId"]
        if not chapter_id:
            return
        offset = current_offset()
        index = chapter_index.get(chapter_id, 0)
        progress = _progress_percent(index, len(chapters), offset, len(state["text"]))
        try:
            update_reading_position(engine_module, book_id, progress, _position_locator(chapter_id, offset))
        except ReaderWorkspaceError:
            return
        status_var.set(f"进度 {progress:.1f}% · 第 {index + 1}/{len(chapters)} 章")
        notify_change()

    def persist_settings() -> None:
        values = {
            "fontSize": _bounded_int(font_var.get(), 18, 10, 72),
            "contentWidth": _bounded_int(width_var.get(), 820, 320, 1800),
            "theme": theme_var.get() if theme_var.get() in _THEMES else "system",
            "focusMode": bool(focus_var.get()),
        }
        try:
            update_reader_settings(engine_module, book_id, values)
        except ReaderWorkspaceError as exc:
            messagebox.showerror("EPUB 阅读器", str(exc), parent=window)
            return
        apply_theme_and_width()
        notify_change()

    def set_focus_mode(enabled: bool, *, persist: bool = True) -> None:
        focus_var.set(bool(enabled))
        if enabled and state["sidebarVisible"]:
            try:
                body.forget(sidebar)
            except tk.TclError:
                pass
            settings_frame.grid_remove()
            state["sidebarVisible"] = False
        elif not enabled and not state["sidebarVisible"]:
            try:
                body.insert(0, sidebar, weight=0)
            except tk.TclError:
                body.add(sidebar, weight=0)
            settings_frame.grid()
            state["sidebarVisible"] = True
        if persist:
            persist_settings()

    def load_chapter(chapter_id: str, offset: int = 0, selection: tuple[int, int] | None = None) -> None:
        if chapter_id not in chapter_id_set:
            return
        if state["chapterId"] and state["chapterId"] != chapter_id:
            persist_position()
        try:
            payload = epub_chapter(engine_module, book_id, chapter_id)
        except (EpubDocumentError, ReaderWorkspaceError) as exc:
            messagebox.showerror("EPUB 阅读器", str(exc), parent=window)
            return
        text = str(payload.get("text") or "")
        state["chapterId"] = chapter_id
        state["chapterIndex"] = int(payload.get("index") or chapter_index[chapter_id])
        state["text"] = text
        reader_text.configure(state="normal")
        reader_text.delete("1.0", "end")
        reader_text.insert("1.0", text)
        reader_text.configure(state="disabled")
        chapter_var.set(f"{payload.get('title') or chapter_id} · {state['chapterIndex'] + 1}/{len(chapters)}")
        previous_button.configure(state="normal" if payload.get("previousChapterId") else "disabled")
        next_button.configure(state="normal" if payload.get("nextChapterId") else "disabled")
        apply_theme_and_width()
        render_saved_annotations()
        safe_offset = max(0, min(int(offset), len(text)))
        reader_text.mark_set("insert", f"1.0+{safe_offset}c")
        reader_text.see(f"1.0+{safe_offset}c")
        if selection is not None:
            select_range(selection[0], selection[1])
        progress = _progress_percent(state["chapterIndex"], len(chapters), safe_offset, len(text))
        status_var.set(f"进度 {progress:.1f}% · 第 {state['chapterIndex'] + 1}/{len(chapters)} 章")

    def move_chapter(delta: int) -> None:
        index = chapter_index.get(state["chapterId"], 0) + int(delta)
        if 0 <= index < len(chapter_ids):
            load_chapter(chapter_ids[index], 0)

    def run_search() -> None:
        query = search_var.get().strip()
        if not query:
            search_entry.focus_set()
            return
        try:
            result = epub_search(engine_module, book_id, query, limit=500)
        except (EpubSearchError, ReaderWorkspaceError) as exc:
            messagebox.showerror("EPUB 搜索", str(exc), parent=window)
            return
        rows = list(result.get("results") or [])
        state["searchResults"] = rows
        search_list.delete(0, "end")
        for row in rows:
            preview = str(row.get("snippet") or "").replace("\n", " ").strip()
            title = str(row.get("chapterTitle") or row.get("chapterId") or "")
            search_list.insert("end", f"{title} · {preview[:180]}")
        status_var.set(f"搜索“{result.get('query')}”：{len(rows)} 个结果" + ("（已截断）" if result.get("truncated") else ""))
        if rows:
            search_list.selection_clear(0, "end")
            search_list.selection_set(0)
            search_list.see(0)

    def open_selected_search(_event=None) -> None:  # noqa: ANN001
        selection = search_list.curselection()
        if not selection:
            return
        row = state["searchResults"][int(selection[0])]
        start = _bounded_int(row.get("offset"), 0, 0, 100_000_000)
        length = _bounded_int(row.get("length"), 1, 1, 100_000)
        load_chapter(str(row.get("chapterId") or ""), start, (start, start + length))

    def selected_text_range() -> tuple[int, int, str] | None:
        try:
            start_index = reader_text.index("sel.first")
            end_index = reader_text.index("sel.last")
        except tk.TclError:
            return None
        start = int(reader_text.count("1.0", start_index, "chars")[0])
        end = int(reader_text.count("1.0", end_index, "chars")[0])
        if end <= start:
            return None
        return start, end, state["text"][start:end]

    def add_current_bookmark() -> None:
        chapter_id = state["chapterId"]
        if not chapter_id:
            return
        offset = current_offset()
        title = chapters[chapter_index[chapter_id]].get("title") or chapter_id
        progress = _progress_percent(chapter_index[chapter_id], len(chapters), offset, len(state["text"]))
        try:
            add_bookmark(
                engine_module,
                book_id,
                _position_locator(chapter_id, offset),
                label=f"{title} · {progress:.1f}%",
            )
        except ReaderWorkspaceError as exc:
            messagebox.showerror("EPUB 书签", str(exc), parent=window)
            return
        refresh_bookmarks()
        notify_change()

    def open_selected_bookmark(_event=None) -> None:  # noqa: ANN001
        selection = bookmark_list.curselection()
        if not selection:
            return
        item = state["bookmarks"][int(selection[0])]
        parsed = _parse_position_locator(item.get("locator"), chapter_id_set)
        if parsed is not None:
            load_chapter(parsed.chapter_id, parsed.offset)

    def delete_selected_bookmark() -> None:
        selection = bookmark_list.curselection()
        if not selection:
            return
        item = state["bookmarks"][int(selection[0])]
        try:
            delete_bookmark(engine_module, item["id"])
        except ReaderWorkspaceError as exc:
            messagebox.showerror("EPUB 书签", str(exc), parent=window)
            return
        refresh_bookmarks()
        notify_change()

    def add_highlight() -> None:
        selected = selected_text_range()
        if selected is None:
            messagebox.showinfo("EPUB 高亮", "请先在正文中选择要高亮的文字。", parent=window)
            return
        start, end, text = selected
        try:
            add_annotation(
                engine_module,
                book_id,
                _range_locator(state["chapterId"], start, end),
                kind="highlight",
                selected_text=text,
            )
        except ReaderWorkspaceError as exc:
            messagebox.showerror("EPUB 高亮", str(exc), parent=window)
            return
        refresh_annotations()
        notify_change()

    def add_note() -> None:
        selected = selected_text_range()
        if selected is None:
            start = current_offset()
            end = min(len(state["text"]), start + 1)
            selected_text = ""
        else:
            start, end, selected_text = selected
        if end <= start:
            messagebox.showinfo("EPUB 笔记", "当前章节没有可标注内容。", parent=window)
            return
        note = simpledialog.askstring("EPUB 笔记", "输入笔记内容：", parent=window)
        if note is None or not note.strip():
            return
        try:
            add_annotation(
                engine_module,
                book_id,
                _range_locator(state["chapterId"], start, end),
                kind="note",
                selected_text=selected_text,
                note=note.strip(),
            )
        except ReaderWorkspaceError as exc:
            messagebox.showerror("EPUB 笔记", str(exc), parent=window)
            return
        refresh_annotations()
        notify_change()

    def open_selected_annotation(_event=None) -> None:  # noqa: ANN001
        selection = annotation_list.curselection()
        if not selection:
            return
        item = state["annotations"][int(selection[0])]
        parsed = _parse_range_locator(item.get("locator"), chapter_id_set)
        if parsed is not None:
            load_chapter(parsed.chapter_id, parsed.start, (parsed.start, parsed.end))

    def delete_selected_annotation() -> None:
        selection = annotation_list.curselection()
        if not selection:
            return
        item = state["annotations"][int(selection[0])]
        try:
            delete_annotation(engine_module, item["id"])
        except ReaderWorkspaceError as exc:
            messagebox.showerror("EPUB 标注", str(exc), parent=window)
            return
        refresh_annotations()
        notify_change()

    def open_selected_toc(_event=None) -> None:  # noqa: ANN001
        selection = toc_list.curselection()
        if not selection:
            return
        index = int(selection[0])
        if 0 <= index < len(toc_targets):
            load_chapter(toc_targets[index], 0)

    def focus_search(_event=None):  # noqa: ANN001
        if focus_var.get():
            set_focus_mode(False, persist=False)
        sidebar_tabs.select(search_tab)
        search_entry.focus_set()
        search_entry.selection_range(0, "end")
        return "break"

    def close_reader() -> None:
        if state["closing"]:
            return
        state["closing"] = True
        persist_position()
        persist_settings()
        window.destroy()

    previous_button.configure(command=lambda: move_chapter(-1))
    next_button.configure(command=lambda: move_chapter(1))
    search_button.configure(command=run_search)
    add_bookmark_button.configure(command=add_current_bookmark)
    delete_bookmark_button.configure(command=delete_selected_bookmark)
    highlight_button.configure(command=add_highlight)
    note_button.configure(command=add_note)
    delete_annotation_button.configure(command=delete_selected_annotation)
    focus_check.configure(command=lambda: set_focus_mode(bool(focus_var.get())))

    toc_list.bind("<Double-Button-1>", open_selected_toc)
    toc_list.bind("<Return>", open_selected_toc)
    search_list.bind("<Double-Button-1>", open_selected_search)
    search_list.bind("<Return>", open_selected_search)
    bookmark_list.bind("<Double-Button-1>", open_selected_bookmark)
    bookmark_list.bind("<Return>", open_selected_bookmark)
    annotation_list.bind("<Double-Button-1>", open_selected_annotation)
    annotation_list.bind("<Return>", open_selected_annotation)
    search_entry.bind("<Return>", lambda _event: run_search())
    font_spin.bind("<Return>", lambda _event: persist_settings())
    width_spin.bind("<Return>", lambda _event: persist_settings())
    theme_combo.bind("<<ComboboxSelected>>", lambda _event: persist_settings())
    window.bind("<Control-f>", focus_search)
    window.bind("<Control-F>", focus_search)
    window.bind("<Control-b>", lambda _event: (add_current_bookmark(), "break")[1])
    window.bind("<Control-B>", lambda _event: (add_current_bookmark(), "break")[1])
    window.bind("<Control-h>", lambda _event: (add_highlight(), "break")[1])
    window.bind("<Control-H>", lambda _event: (add_highlight(), "break")[1])
    window.bind("<Control-n>", lambda _event: (add_note(), "break")[1])
    window.bind("<Control-N>", lambda _event: (add_note(), "break")[1])
    window.bind("<Prior>", lambda _event: (move_chapter(-1), "break")[1])
    window.bind("<Next>", lambda _event: (move_chapter(1), "break")[1])
    window.bind("<Escape>", lambda _event: (set_focus_mode(False) if focus_var.get() else close_reader(), "break")[1])
    window.protocol("WM_DELETE_WINDOW", close_reader)

    refresh_bookmarks()
    refresh_annotations()
    initial = _initial_chapter(book, chapter_ids)
    load_chapter(initial.chapter_id, initial.offset)
    apply_theme_and_width()
    if focus_var.get():
        set_focus_mode(True, persist=False)
    reader_text.focus_set()
    return window
