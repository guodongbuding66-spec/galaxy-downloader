from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook
from reader_workspace import (
    ReaderWorkspaceError,
    add_bookmark,
    import_book,
    list_bookmarks,
    list_books,
    search_reader,
    update_reading_position,
)


def _show_reader(window, engine_module) -> None:
    existing = getattr(window, "_reader_workspace_window", None)
    if existing is not None:
        try:
            existing.deiconify(); existing.lift(); return
        except tk.TclError:
            pass
    dialog = tk.Toplevel(window)
    window._reader_workspace_window = dialog
    dialog.title("Reader · Galaxy Local Engine")
    dialog.geometry("940x650")
    dialog.minsize(800, 540)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=18, pady=16); shell.pack(fill="both", expand=True)
    ui._label(shell, "Reader", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(shell, "PDF / EPUB / CBZ / TXT / HTML 本地阅读库，带搜索、进度和书签。", size=8, color=ui.MUTED, bg=ui.BG).pack(anchor="w", pady=(3, 10))

    toolbar = tk.Frame(shell, bg=ui.BG); toolbar.pack(fill="x")
    query_var = tk.StringVar(); progress_var = tk.StringVar(value="0"); locator_var = tk.StringVar(value="start"); status_var = tk.StringVar(value="就绪")
    query_entry = tk.Entry(toolbar, textvariable=query_var, bg=ui.PANEL, fg=ui.TEXT, insertbackground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER)
    query_entry.pack(side="left", fill="x", expand=True, ipady=5)

    body = tk.Frame(shell, bg=ui.BG); body.pack(fill="both", expand=True, pady=(10, 0))
    books_list = tk.Listbox(body, width=42, bg=ui.PANEL, fg=ui.TEXT, selectbackground=ui.PANEL_3, selectforeground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER)
    books_list.pack(side="left", fill="both", expand=True)
    detail = tk.Frame(body, bg=ui.PANEL, padx=14, pady=12); detail.pack(side="left", fill="both", expand=True, padx=(10, 0))
    title_var = tk.StringVar(value="未选择书籍")
    meta_var = tk.StringVar(value="")
    bookmarks_var = tk.StringVar(value="")
    ui._label(detail, variable=title_var, size=12, weight="bold").pack(anchor="w")
    ui._label(detail, variable=meta_var, size=8, color=ui.MUTED, wraplength=400, justify="left").pack(anchor="w", pady=(5, 12))
    ui._label(detail, "阅读进度 %", size=7, color=ui.SUBTLE).pack(anchor="w")
    tk.Entry(detail, textvariable=progress_var, bg=ui.BG, fg=ui.TEXT, insertbackground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER).pack(fill="x", pady=(4, 8))
    ui._label(detail, "Locator / 位置", size=7, color=ui.SUBTLE).pack(anchor="w")
    tk.Entry(detail, textvariable=locator_var, bg=ui.BG, fg=ui.TEXT, insertbackground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER).pack(fill="x", pady=(4, 8))
    ui._label(detail, "书签", size=7, color=ui.SUBTLE).pack(anchor="w")
    ui._label(detail, variable=bookmarks_var, size=8, color=ui.MUTED, wraplength=400, justify="left").pack(anchor="w", pady=(4, 0))

    rows: list[dict] = []
    def selected() -> dict | None:
        selection = books_list.curselection()
        return rows[selection[0]] if selection else None

    def refresh_detail(*_args) -> None:
        book = selected()
        if not book:
            title_var.set("未选择书籍"); meta_var.set(""); bookmarks_var.set(""); return
        title_var.set(str(book.get("title") or book.get("sourceName") or "Book"))
        progress_var.set(str(book.get("progressPercent") or 0))
        locator_var.set(str(book.get("locator") or "start"))
        meta_var.set(f"{str(book.get('format') or '').upper()} · {int(book.get('sizeBytes') or 0):,} bytes")
        marks = list_bookmarks(engine_module, book["id"], limit=20)
        bookmarks_var.set("\n".join(f"• {item.get('label') or item.get('locator')}" for item in marks) or "暂无书签")

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
                books_list.insert("end", f"{book.get('title')} · {book.get('format')} · {float(book.get('progressPercent') or 0):.1f}%")
            if rows:
                books_list.selection_set(0)
            refresh_detail()
            status_var.set(f"{len(rows)} 本")
        except Exception as exc:
            status_var.set(f"失败：{exc}")

    def import_file() -> None:
        value = filedialog.askopenfilename(parent=dialog, title="导入 Reader", filetypes=(("Reader", "*.pdf *.epub *.cbz *.txt *.html *.htm"), ("All", "*.*")))
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
            return
        try:
            progress = float(progress_var.get() or 0)
            update_reading_position(engine_module, book["id"], progress, locator_var.get())
            status_var.set("进度已保存"); refresh()
        except Exception as exc:
            status_var.set(f"失败：{exc}")

    def bookmark() -> None:
        book = selected()
        if not book:
            return
        try:
            add_bookmark(engine_module, book["id"], locator_var.get(), label=f"{float(progress_var.get() or 0):.1f}%")
            status_var.set("书签已添加"); refresh_detail()
        except Exception as exc:
            status_var.set(f"失败：{exc}")

    footer = tk.Frame(shell, bg=ui.BG); footer.pack(fill="x", pady=(10, 0))
    ui._label(footer, variable=status_var, size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    ui.ActionButton(footer, text="导入", command=import_file, kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(footer, text="添加书签", command=bookmark, kind="ghost", compact=True).pack(side="right", padx=(0, 6))
    ui.ActionButton(footer, text="保存进度", command=save_progress, kind="secondary", compact=True).pack(side="right", padx=(0, 6))
    ui.ActionButton(toolbar, text="搜索/刷新", command=refresh, kind="ghost", compact=True).pack(side="right", padx=(8, 0))

    def close() -> None:
        window._reader_workspace_window = None; dialog.destroy()
    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh()


def _add_reader_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_reader_entry_built", False): return
    card = tk.Frame(panel, bg=ui.PANEL_2); card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2); text.pack(side="left", fill="x", expand=True)
    ui._label(text, "Reader", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(text, "PDF / EPUB / CBZ / TXT / HTML · 搜索 · 进度 · 书签", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(card, text="打开 Reader", command=lambda: _show_reader(window, engine_module), kind="secondary", compact=True).pack(side="right")
    window._galaxy_reader_entry_built = True


def install_desktop_reader(engine_module):
    cls = engine_module.EngineWindow
    if getattr(cls, "_galaxy_desktop_reader_installed", False): return cls
    register_after_build_ui_hook(cls, "desktop-reader", lambda window: _add_reader_entry(window, engine_module), order=54)
    cls._galaxy_desktop_reader_installed = True
    return cls


def run_desktop_reader_self_test() -> None:
    assert callable(import_book) and callable(search_reader) and callable(update_reading_position)
