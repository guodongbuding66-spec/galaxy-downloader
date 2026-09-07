from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook
from reader_workspace import (
    ReaderWorkspaceError,
    add_annotation,
    add_bookmark,
    delete_annotation,
    import_book,
    list_annotations,
    list_bookmarks,
    list_books,
    search_reader,
    update_reader_settings,
    update_reading_position,
)


_READER_THEMES = ("system", "light", "dark", "sepia")
_READING_MODES = ("auto", "vertical", "single", "double", "fit-width")
_MANGA_DIRECTIONS = ("ltr", "rtl")
_ANNOTATION_KINDS = ("highlight", "note")


def _normalize_settings(book: dict[str, Any] | None) -> dict[str, Any]:
    raw = book.get("settings") if isinstance(book, dict) else None
    settings = raw if isinstance(raw, dict) else {}
    format_id = str((book or {}).get("format") or "").strip().lower()
    return {
        "fontSize": max(10, min(int(settings.get("fontSize") or 18), 72)),
        "contentWidth": max(320, min(int(settings.get("contentWidth") or 820), 1800)),
        "theme": str(settings.get("theme") or "system") if str(settings.get("theme") or "system") in _READER_THEMES else "system",
        "focusMode": bool(settings.get("focusMode", False)),
        "readingMode": str(settings.get("readingMode") or ("vertical" if format_id == "cbz" else "auto"))
        if str(settings.get("readingMode") or ("vertical" if format_id == "cbz" else "auto")) in _READING_MODES
        else ("vertical" if format_id == "cbz" else "auto"),
        "mangaDirection": str(settings.get("mangaDirection") or "ltr")
        if str(settings.get("mangaDirection") or "ltr") in _MANGA_DIRECTIONS
        else "ltr",
    }


def _settings_capabilities(format_id: object) -> dict[str, bool]:
    clean = str(format_id or "").strip().lower()
    text_layout = clean in {"epub", "txt", "html", "htm"}
    cbz_layout = clean == "cbz"
    return {
        "font": text_layout,
        "width": text_layout,
        "theme": text_layout,
        "focus": True,
        "readingMode": cbz_layout,
        "mangaDirection": cbz_layout,
    }


def _settings_payload(
    *,
    font_size: object,
    content_width: object,
    theme: object,
    focus_mode: object,
    reading_mode: object,
    manga_direction: object,
) -> dict[str, Any]:
    try:
        font = int(font_size)
    except (TypeError, ValueError):
        font = 18
    try:
        width = int(content_width)
    except (TypeError, ValueError):
        width = 820
    clean_theme = str(theme or "system")
    clean_mode = str(reading_mode or "auto")
    clean_direction = str(manga_direction or "ltr")
    return {
        "fontSize": max(10, min(font, 72)),
        "contentWidth": max(320, min(width, 1800)),
        "theme": clean_theme if clean_theme in _READER_THEMES else "system",
        "focusMode": bool(focus_mode),
        "readingMode": clean_mode if clean_mode in _READING_MODES else "auto",
        "mangaDirection": clean_direction if clean_direction in _MANGA_DIRECTIONS else "ltr",
    }


def _annotation_summary(row: dict[str, Any]) -> str:
    kind = str(row.get("kind") or "note").strip().lower()
    locator = str(row.get("locator") or "start").strip() or "start"
    selected = " ".join(str(row.get("selectedText") or "").split()).strip()
    note = " ".join(str(row.get("note") or "").split()).strip()
    preview = selected or note or "(empty)"
    if len(preview) > 90:
        preview = preview[:87] + "…"
    return f"{kind} · {locator} · {preview}"


def _show_reader(window, engine_module) -> None:
    existing = getattr(window, "_reader_workspace_window", None)
    if existing is not None:
        try:
            existing.deiconify()
            existing.lift()
            return
        except tk.TclError:
            pass

    dialog = tk.Toplevel(window)
    window._reader_workspace_window = dialog
    dialog.title("Reader · Galaxy Local Engine")
    dialog.geometry("1120x760")
    dialog.minsize(900, 620)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=18, pady=16)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "Reader", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "PDF / EPUB / CBZ / TXT / HTML 本地阅读库 · 搜索 · 进度 · 书签 · 阅读设置 · 标注/笔记",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(3, 10))

    toolbar = tk.Frame(shell, bg=ui.BG)
    toolbar.pack(fill="x")
    query_var = tk.StringVar()
    progress_var = tk.StringVar(value="0")
    locator_var = tk.StringVar(value="start")
    status_var = tk.StringVar(value="就绪")
    query_entry = tk.Entry(
        toolbar,
        textvariable=query_var,
        bg=ui.PANEL,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    query_entry.pack(side="left", fill="x", expand=True, ipady=5)

    body = tk.Frame(shell, bg=ui.BG)
    body.pack(fill="both", expand=True, pady=(10, 0))
    books_list = tk.Listbox(
        body,
        width=38,
        bg=ui.PANEL,
        fg=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        activestyle="none",
        exportselection=False,
    )
    books_list.pack(side="left", fill="both", expand=True)

    detail = tk.Frame(body, bg=ui.PANEL, padx=14, pady=12)
    detail.pack(side="left", fill="both", expand=True, padx=(10, 0))
    title_var = tk.StringVar(value="未选择书籍")
    meta_var = tk.StringVar(value="")
    ui._label(detail, variable=title_var, size=12, weight="bold").pack(anchor="w")
    ui._label(detail, variable=meta_var, size=8, color=ui.MUTED, wraplength=620, justify="left").pack(anchor="w", pady=(5, 10))

    notebook = ttk.Notebook(detail)
    notebook.pack(fill="both", expand=True)
    progress_tab = tk.Frame(notebook, bg=ui.PANEL, padx=10, pady=10)
    settings_tab = tk.Frame(notebook, bg=ui.PANEL, padx=10, pady=10)
    annotations_tab = tk.Frame(notebook, bg=ui.PANEL, padx=10, pady=10)
    notebook.add(progress_tab, text="进度与书签")
    notebook.add(settings_tab, text="阅读设置")
    notebook.add(annotations_tab, text="标注与笔记")

    # Progress / bookmark surface.
    ui._label(progress_tab, "阅读进度 %", size=7, color=ui.SUBTLE).pack(anchor="w")
    progress_entry = tk.Entry(
        progress_tab,
        textvariable=progress_var,
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    progress_entry.pack(fill="x", pady=(4, 8), ipady=4)
    ui._label(progress_tab, "Locator / 位置", size=7, color=ui.SUBTLE).pack(anchor="w")
    locator_entry = tk.Entry(
        progress_tab,
        textvariable=locator_var,
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    locator_entry.pack(fill="x", pady=(4, 10), ipady=4)

    progress_actions = tk.Frame(progress_tab, bg=ui.PANEL)
    progress_actions.pack(fill="x")
    bookmarks_var = tk.StringVar(value="暂无书签")
    ui._label(progress_tab, "书签", size=7, color=ui.SUBTLE).pack(anchor="w", pady=(14, 0))
    ui._label(progress_tab, variable=bookmarks_var, size=8, color=ui.MUTED, wraplength=600, justify="left").pack(anchor="w", pady=(4, 0))

    # Settings surface.
    font_size_var = tk.StringVar(value="18")
    content_width_var = tk.StringVar(value="820")
    theme_var = tk.StringVar(value="system")
    focus_mode_var = tk.BooleanVar(value=False)
    reading_mode_var = tk.StringVar(value="auto")
    manga_direction_var = tk.StringVar(value="ltr")
    settings_hint_var = tk.StringVar(value="选择一本书后可编辑阅读偏好。")

    settings_grid = tk.Frame(settings_tab, bg=ui.PANEL)
    settings_grid.pack(fill="x")

    def setting_row(parent, row: int, label: str, variable: tk.Variable, values: tuple[str, ...] | None = None):
        ui._label(parent, label, size=7, color=ui.SUBTLE).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=6)
        if values is None:
            widget = tk.Entry(
                parent,
                textvariable=variable,
                bg=ui.BG,
                fg=ui.TEXT,
                insertbackground=ui.TEXT,
                relief="flat",
                highlightthickness=1,
                highlightbackground=ui.BORDER,
            )
        else:
            widget = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        widget.grid(row=row, column=1, sticky="ew", pady=6, ipady=3 if values is None else 0)
        return widget

    settings_grid.columnconfigure(1, weight=1)
    font_size_entry = setting_row(settings_grid, 0, "字体大小", font_size_var)
    content_width_entry = setting_row(settings_grid, 1, "内容宽度", content_width_var)
    theme_combo = setting_row(settings_grid, 2, "主题", theme_var, _READER_THEMES)
    reading_mode_combo = setting_row(settings_grid, 3, "阅读模式", reading_mode_var, _READING_MODES)
    manga_direction_combo = setting_row(settings_grid, 4, "漫画方向", manga_direction_var, _MANGA_DIRECTIONS)

    focus_row = tk.Frame(settings_tab, bg=ui.PANEL)
    focus_row.pack(fill="x", pady=(8, 0))
    focus_check = tk.Checkbutton(
        focus_row,
        text="Focus Mode",
        variable=focus_mode_var,
        bg=ui.PANEL,
        fg=ui.TEXT,
        selectcolor=ui.BG,
        activebackground=ui.PANEL,
        activeforeground=ui.TEXT,
        anchor="w",
    )
    focus_check.pack(side="left")
    ui._label(
        settings_tab,
        variable=settings_hint_var,
        size=7,
        color=ui.MUTED,
        wraplength=600,
        justify="left",
    ).pack(anchor="w", pady=(10, 0))

    # Annotation surface.
    annotation_rows: list[dict[str, Any]] = []
    annotation_list = tk.Listbox(
        annotations_tab,
        height=8,
        bg=ui.BG,
        fg=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        activestyle="none",
        exportselection=False,
    )
    annotation_list.pack(fill="x")

    annotation_form = tk.Frame(annotations_tab, bg=ui.PANEL)
    annotation_form.pack(fill="both", expand=True, pady=(10, 0))
    annotation_form.columnconfigure(1, weight=1)
    annotation_kind_var = tk.StringVar(value="highlight")
    annotation_locator_var = tk.StringVar(value="start")

    ui._label(annotation_form, "类型", size=7, color=ui.SUBTLE).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
    annotation_kind_combo = ttk.Combobox(
        annotation_form,
        textvariable=annotation_kind_var,
        values=_ANNOTATION_KINDS,
        state="readonly",
        width=14,
    )
    annotation_kind_combo.grid(row=0, column=1, sticky="ew", pady=4)

    ui._label(annotation_form, "Locator / 位置", size=7, color=ui.SUBTLE).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
    annotation_locator_entry = tk.Entry(
        annotation_form,
        textvariable=annotation_locator_var,
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    annotation_locator_entry.grid(row=1, column=1, sticky="ew", pady=4, ipady=3)

    ui._label(annotation_form, "选中文本", size=7, color=ui.SUBTLE).grid(row=2, column=0, sticky="nw", padx=(0, 10), pady=4)
    selected_text_box = ScrolledText(
        annotation_form,
        height=4,
        wrap="word",
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        padx=6,
        pady=6,
    )
    selected_text_box.grid(row=2, column=1, sticky="nsew", pady=4)

    ui._label(annotation_form, "笔记", size=7, color=ui.SUBTLE).grid(row=3, column=0, sticky="nw", padx=(0, 10), pady=4)
    note_box = ScrolledText(
        annotation_form,
        height=4,
        wrap="word",
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        padx=6,
        pady=6,
    )
    note_box.grid(row=3, column=1, sticky="nsew", pady=4)
    annotation_form.rowconfigure(2, weight=1)
    annotation_form.rowconfigure(3, weight=1)

    annotation_actions = tk.Frame(annotations_tab, bg=ui.PANEL)
    annotation_actions.pack(fill="x", pady=(10, 0))

    rows: list[dict[str, Any]] = []

    def selected() -> dict[str, Any] | None:
        selection = books_list.curselection()
        return rows[selection[0]] if selection else None

    def selected_annotation() -> dict[str, Any] | None:
        selection = annotation_list.curselection()
        return annotation_rows[selection[0]] if selection else None

    def set_widget_enabled(widget, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        if isinstance(widget, ttk.Combobox):
            widget.configure(state="readonly" if enabled else "disabled")
        else:
            widget.configure(state=state)

    def apply_format_controls(book: dict[str, Any] | None) -> None:
        format_id = str((book or {}).get("format") or "").strip().lower()
        caps = _settings_capabilities(format_id)
        set_widget_enabled(font_size_entry, caps["font"])
        set_widget_enabled(content_width_entry, caps["width"])
        set_widget_enabled(theme_combo, caps["theme"])
        set_widget_enabled(focus_check, bool(book) and caps["focus"])
        set_widget_enabled(reading_mode_combo, caps["readingMode"])
        set_widget_enabled(manga_direction_combo, caps["mangaDirection"])
        if not book:
            settings_hint_var.set("选择一本书后可编辑阅读偏好。")
        elif format_id == "cbz":
            settings_hint_var.set("CBZ：阅读模式、漫画方向和 Focus Mode 会保存到书籍偏好；视觉阅读器将在后续独立 PR 接入。")
        elif format_id in {"epub", "txt", "html", "htm"}:
            settings_hint_var.set("文本阅读：字体、内容宽度、主题和 Focus Mode 会保存到书籍偏好；渲染阅读器将在后续独立 PR 接入。")
        elif format_id == "pdf":
            settings_hint_var.set("PDF 当前仅保存 Focus Mode；Zoom/Page 专用阅读器将在后续独立 PR 接入。")
        else:
            settings_hint_var.set("当前格式仅保存通用阅读偏好。")

    def refresh_annotations(book: dict[str, Any] | None) -> None:
        annotation_rows.clear()
        annotation_list.delete(0, "end")
        if not book:
            return
        try:
            annotation_rows.extend(list_annotations(engine_module, book["id"], limit=2000))
        except Exception as exc:
            status_var.set(f"标注加载失败：{exc}")
            return
        for item in annotation_rows:
            annotation_list.insert("end", _annotation_summary(item))

    def load_settings(book: dict[str, Any] | None) -> None:
        settings = _normalize_settings(book)
        font_size_var.set(str(settings["fontSize"]))
        content_width_var.set(str(settings["contentWidth"]))
        theme_var.set(str(settings["theme"]))
        focus_mode_var.set(bool(settings["focusMode"]))
        reading_mode_var.set(str(settings["readingMode"]))
        manga_direction_var.set(str(settings["mangaDirection"]))
        apply_format_controls(book)

    def refresh_detail(*_args) -> None:
        book = selected()
        if not book:
            title_var.set("未选择书籍")
            meta_var.set("")
            bookmarks_var.set("")
            refresh_annotations(None)
            load_settings(None)
            return
        title_var.set(str(book.get("title") or book.get("sourceName") or "Book"))
        progress_var.set(str(book.get("progressPercent") or 0))
        locator = str(book.get("locator") or "start")
        locator_var.set(locator)
        annotation_locator_var.set(locator)
        meta_var.set(
            f"{str(book.get('format') or '').upper()} · {int(book.get('sizeBytes') or 0):,} bytes · "
            f"{float(book.get('progressPercent') or 0):.1f}%"
        )
        marks = list_bookmarks(engine_module, book["id"], limit=20)
        bookmarks_var.set("\n".join(f"• {item.get('label') or item.get('locator')}" for item in marks) or "暂无书签")
        load_settings(book)
        refresh_annotations(book)

    books_list.bind("<<ListboxSelect>>", refresh_detail)

    def refresh() -> None:
        text = query_var.get().strip()
        try:
            if text:
                matches = search_reader(engine_module, text, limit=200)
                ids = {str(item.get("bookId") or item.get("id") or "") for item in matches}
                source = list_books(engine_module, limit=500)
                rows[:] = [item for item in source if str(item.get("id") or "") in ids]
            else:
                rows[:] = list_books(engine_module, limit=500)
            books_list.delete(0, "end")
            for book in rows:
                books_list.insert(
                    "end",
                    f"{book.get('title')} · {book.get('format')} · {float(book.get('progressPercent') or 0):.1f}%",
                )
            if rows:
                books_list.selection_set(0)
                books_list.activate(0)
            refresh_detail()
            status_var.set(f"{len(rows)} 本")
        except Exception as exc:
            status_var.set(f"失败：{exc}")

    def import_file() -> None:
        value = filedialog.askopenfilename(
            parent=dialog,
            title="导入 Reader",
            filetypes=(("Reader", "*.pdf *.epub *.cbz *.txt *.html *.htm"), ("All", "*.*")),
        )
        if not value:
            return
        try:
            import_book(engine_module, Path(value))
            status_var.set("已导入")
            refresh()
        except ReaderWorkspaceError as exc:
            messagebox.showerror(engine_module.APP_NAME, str(exc), parent=dialog)

    def save_progress() -> None:
        book = selected()
        if not book:
            status_var.set("请先选择书籍")
            return
        try:
            progress = float(progress_var.get() or 0)
            locator = locator_var.get()
            update_reading_position(engine_module, book["id"], progress, locator)
            book["progressPercent"] = max(0.0, min(progress, 100.0))
            book["locator"] = locator
            annotation_locator_var.set(locator)
            status_var.set("进度已保存")
            refresh()
        except Exception as exc:
            status_var.set(f"失败：{exc}")

    def bookmark() -> None:
        book = selected()
        if not book:
            status_var.set("请先选择书籍")
            return
        try:
            add_bookmark(
                engine_module,
                book["id"],
                locator_var.get(),
                label=f"{float(progress_var.get() or 0):.1f}%",
            )
            status_var.set("书签已添加")
            refresh_detail()
        except Exception as exc:
            status_var.set(f"失败：{exc}")

    def save_settings() -> None:
        book = selected()
        if not book:
            status_var.set("请先选择书籍")
            return
        try:
            payload = _settings_payload(
                font_size=font_size_var.get(),
                content_width=content_width_var.get(),
                theme=theme_var.get(),
                focus_mode=focus_mode_var.get(),
                reading_mode=reading_mode_var.get(),
                manga_direction=manga_direction_var.get(),
            )
            caps = _settings_capabilities(book.get("format"))
            bounded: dict[str, Any] = {"focusMode": payload["focusMode"]}
            if caps["font"]:
                bounded.update(
                    {
                        "fontSize": payload["fontSize"],
                        "contentWidth": payload["contentWidth"],
                        "theme": payload["theme"],
                    }
                )
            if caps["readingMode"]:
                bounded.update(
                    {
                        "readingMode": payload["readingMode"],
                        "mangaDirection": payload["mangaDirection"],
                    }
                )
            saved = update_reader_settings(engine_module, book["id"], bounded)
            book["settings"] = saved
            load_settings(book)
            status_var.set("阅读设置已保存")
        except Exception as exc:
            status_var.set(f"失败：{exc}")

    def add_reader_annotation() -> None:
        book = selected()
        if not book:
            status_var.set("请先选择书籍")
            return
        selected_text = selected_text_box.get("1.0", "end-1c").strip()
        note = note_box.get("1.0", "end-1c").strip()
        try:
            add_annotation(
                engine_module,
                book["id"],
                annotation_locator_var.get(),
                kind=annotation_kind_var.get(),
                selected_text=selected_text,
                note=note,
            )
            selected_text_box.delete("1.0", "end")
            note_box.delete("1.0", "end")
            refresh_annotations(book)
            if annotation_rows:
                annotation_list.selection_clear(0, "end")
                annotation_list.selection_set(len(annotation_rows) - 1)
                annotation_list.see(len(annotation_rows) - 1)
            status_var.set("标注已添加")
        except Exception as exc:
            status_var.set(f"失败：{exc}")

    def remove_reader_annotation() -> None:
        book = selected()
        item = selected_annotation()
        if not book or not item:
            status_var.set("请先选择标注")
            return
        try:
            if not delete_annotation(engine_module, item["id"]):
                raise ReaderWorkspaceError("Annotation 不存在")
            refresh_annotations(book)
            status_var.set("标注已删除")
        except Exception as exc:
            status_var.set(f"失败：{exc}")

    def inspect_annotation(*_args) -> None:
        item = selected_annotation()
        if not item:
            return
        annotation_kind_var.set(str(item.get("kind") or "highlight"))
        annotation_locator_var.set(str(item.get("locator") or "start"))
        selected_text_box.delete("1.0", "end")
        selected_text_box.insert("1.0", str(item.get("selectedText") or ""))
        note_box.delete("1.0", "end")
        note_box.insert("1.0", str(item.get("note") or ""))

    annotation_list.bind("<<ListboxSelect>>", inspect_annotation)

    ui.ActionButton(progress_actions, text="保存进度", command=save_progress, kind="secondary", compact=True).pack(side="left")
    ui.ActionButton(progress_actions, text="添加书签", command=bookmark, kind="ghost", compact=True).pack(side="left", padx=(6, 0))
    ui.ActionButton(settings_tab, text="保存阅读设置", command=save_settings, kind="secondary", compact=True).pack(anchor="e", pady=(14, 0))
    ui.ActionButton(annotation_actions, text="添加标注", command=add_reader_annotation, kind="secondary", compact=True).pack(side="left")
    ui.ActionButton(annotation_actions, text="删除所选", command=remove_reader_annotation, kind="ghost", compact=True).pack(side="left", padx=(6, 0))

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(10, 0))
    ui._label(footer, variable=status_var, size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    ui.ActionButton(footer, text="导入", command=import_file, kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(toolbar, text="搜索/刷新", command=refresh, kind="ghost", compact=True).pack(side="right", padx=(8, 0))

    query_entry.bind("<Return>", lambda _event: refresh())
    dialog.bind("<Control-s>", lambda _event: save_settings() if notebook.index(notebook.select()) == 1 else save_progress())

    def close() -> None:
        window._reader_workspace_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh()


def _add_reader_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_reader_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "Reader", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        text,
        "PDF / EPUB / CBZ / TXT / HTML · 搜索 · 进度 · 书签 · 设置 · 标注",
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(
        card,
        text="打开 Reader",
        command=lambda: _show_reader(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_reader_entry_built = True


def install_desktop_reader(engine_module):
    cls = engine_module.EngineWindow
    if getattr(cls, "_galaxy_desktop_reader_installed", False):
        return cls
    register_after_build_ui_hook(cls, "desktop-reader", lambda window: _add_reader_entry(window, engine_module), order=54)
    cls._galaxy_desktop_reader_installed = True
    return cls


def run_desktop_reader_self_test() -> None:
    assert callable(import_book) and callable(search_reader) and callable(update_reading_position)
    assert callable(update_reader_settings) and callable(add_annotation) and callable(delete_annotation)
    epub_caps = _settings_capabilities("epub")
    assert epub_caps["font"] and epub_caps["width"] and epub_caps["theme"] and not epub_caps["readingMode"]
    cbz_caps = _settings_capabilities("cbz")
    assert cbz_caps["readingMode"] and cbz_caps["mangaDirection"] and not cbz_caps["font"]
    settings = _settings_payload(
        font_size=100,
        content_width=1,
        theme="invalid",
        focus_mode=True,
        reading_mode="double",
        manga_direction="rtl",
    )
    assert settings == {
        "fontSize": 72,
        "contentWidth": 320,
        "theme": "system",
        "focusMode": True,
        "readingMode": "double",
        "mangaDirection": "rtl",
    }
    assert _annotation_summary({"kind": "note", "locator": "page:3", "note": "Remember this"}) == "note · page:3 · Remember this"
