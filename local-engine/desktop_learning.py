from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook
from learning_workspace import (
    LearningWorkspaceError,
    add_media_to_course,
    add_timestamp_note,
    course_download_payload,
    create_course,
    create_flashcard,
    due_flashcards,
    export_course_notes,
    import_epub,
    list_books,
    list_course_items,
    list_courses,
    list_notes,
    music_library,
    open_local_player,
    review_flashcard,
    update_book_progress,
    update_course_progress,
)
from media_library import list_media_items, sync_media_library


def _open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _entry(master, variable, width=24):
    return tk.Entry(
        master,
        textvariable=variable,
        width=width,
        font=("Segoe UI", 8),
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
    )


def _listbox(master, height=10):
    return tk.Listbox(
        master,
        height=height,
        bg=ui.BG,
        fg=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        relief="flat",
        font=("Segoe UI", 8),
    )


def _show_learning_workspace(window, engine_module) -> None:
    existing = getattr(window, "_learning_workspace_window", None)
    if existing is not None:
        try:
            existing.deiconify()
            existing.lift()
            return
        except tk.TclError:
            pass

    dialog = tk.Toplevel(window)
    window._learning_workspace_window = dialog
    dialog.title("学习工作台 · Galaxy Local Engine")
    dialog.geometry("1000x720")
    dialog.minsize(880, 620)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=18, pady=16)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "学习工作台", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "课程 · 时间戳笔记 · PDF 导出 · 音乐库 · EPUB · 间隔重复，数据全部保存在 Galaxy 本机运行目录。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(3, 10))

    style = ttk.Style(dialog)
    style.configure("Galaxy.TNotebook", background=ui.BG, borderwidth=0)
    style.configure("Galaxy.TNotebook.Tab", background=ui.PANEL_2, foreground=ui.MUTED, padding=(12, 7))
    style.map("Galaxy.TNotebook.Tab", background=[("selected", ui.PANEL_3)], foreground=[("selected", ui.TEXT)])
    notebook = ttk.Notebook(shell, style="Galaxy.TNotebook")
    notebook.pack(fill="both", expand=True)

    # Courses
    course_tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14)
    notebook.add(course_tab, text="课程")
    course_name_var = tk.StringVar(value="新课程")
    course_url_var = tk.StringVar()
    course_status_var = tk.StringVar(value="就绪")
    course_rows: list[dict] = []
    library_rows: list[dict] = []
    item_rows: list[dict] = []

    create_row = tk.Frame(course_tab, bg=ui.PANEL)
    create_row.pack(fill="x")
    ui._label(create_row, "课程名", size=7, color=ui.MUTED).pack(side="left")
    _entry(create_row, course_name_var, 18).pack(side="left", padx=(6, 12))
    ui._label(create_row, "在线课程/播放列表", size=7, color=ui.MUTED).pack(side="left")
    _entry(create_row, course_url_var, 42).pack(side="left", fill="x", expand=True, padx=(6, 8))

    columns = tk.Frame(course_tab, bg=ui.PANEL)
    columns.pack(fill="both", expand=True, pady=(12, 0))
    for index in range(3):
        columns.grid_columnconfigure(index, weight=1, uniform="learning")
    columns.grid_rowconfigure(1, weight=1)
    ui._label(columns, "课程", size=8, weight="bold").grid(row=0, column=0, sticky="w")
    ui._label(columns, "媒体库", size=8, weight="bold").grid(row=0, column=1, sticky="w", padx=(10, 0))
    ui._label(columns, "课程内容", size=8, weight="bold").grid(row=0, column=2, sticky="w", padx=(10, 0))
    course_list = _listbox(columns, 13)
    library_list = _listbox(columns, 13)
    item_list = _listbox(columns, 13)
    course_list.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
    library_list.grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=(6, 0))
    item_list.grid(row=1, column=2, sticky="nsew", padx=(10, 0), pady=(6, 0))

    def selected_course() -> dict | None:
        selection = course_list.curselection()
        return course_rows[selection[0]] if selection else None

    def selected_library() -> dict | None:
        selection = library_list.curselection()
        return library_rows[selection[0]] if selection else None

    def selected_item() -> dict | None:
        selection = item_list.curselection()
        return item_rows[selection[0]] if selection else None

    def refresh_course_items(*_args) -> None:
        item_rows.clear()
        item_list.delete(0, "end")
        course = selected_course()
        if course is None:
            return
        for item in list_course_items(engine_module, course["id"]):
            item_rows.append(item)
            progress = "✓" if item["completed"] else f"{item['progressSeconds']:.0f}s"
            item_list.insert("end", f"{item['position']:02d} · {progress} · {item['title']}")
        if item_rows:
            item_list.selection_set(0)

    course_list.bind("<<ListboxSelect>>", refresh_course_items)

    def refresh_courses() -> None:
        course_rows[:] = list_courses(engine_module)
        course_list.delete(0, "end")
        for course in course_rows:
            course_list.insert("end", f"{course['name']}  ({course['completedCount']}/{course['itemCount']})")
        if course_rows:
            course_list.selection_set(0)
        refresh_course_items()

    def refresh_library() -> None:
        try:
            sync_media_library(engine_module)
        except Exception:
            pass
        library_rows[:] = [
            item for item in list_media_items(engine_module, limit=500)
            if item.get("available") and item.get("mediaType") in {"video", "audio"}
        ]
        library_list.delete(0, "end")
        for item in library_rows:
            library_list.insert("end", f"{item.get('mediaType')} · {item.get('title') or item.get('fileName')}")
        if library_rows:
            library_list.selection_set(0)

    def create_only() -> None:
        try:
            create_course(engine_module, course_name_var.get(), course_url_var.get())
            course_status_var.set("课程已创建")
            refresh_courses()
        except Exception as exc:  # noqa: BLE001
            course_status_var.set(f"失败：{exc}")

    def create_and_download() -> None:
        url = course_url_var.get().strip()
        try:
            create_course(engine_module, course_name_var.get(), url)
            payload = course_download_payload(url)
        except Exception as exc:  # noqa: BLE001
            course_status_var.set(f"失败：{exc}")
            return
        course_status_var.set("正在提交课程下载…")

        def worker() -> None:
            response = window.submit_bridge_job(payload)
            message = str(getattr(response, "message", response))
            dialog.after(0, lambda: course_status_var.set(message))
            dialog.after(0, refresh_courses)

        threading.Thread(target=worker, daemon=True).start()

    def add_selected_media() -> None:
        course = selected_course()
        media = selected_library()
        if not course or not media:
            return
        try:
            add_media_to_course(engine_module, course["id"], media["id"])
            course_status_var.set("已加入课程")
            refresh_courses()
        except Exception as exc:  # noqa: BLE001
            course_status_var.set(f"失败：{exc}")

    progress_row = tk.Frame(course_tab, bg=ui.PANEL)
    progress_row.pack(fill="x", pady=(10, 0))
    timestamp_var = tk.StringVar(value="0")
    note_var = tk.StringVar()
    ui._label(progress_row, "时间/进度(s)", size=7, color=ui.MUTED).pack(side="left")
    _entry(progress_row, timestamp_var, 10).pack(side="left", padx=(6, 10))
    ui._label(progress_row, "笔记", size=7, color=ui.MUTED).pack(side="left")
    _entry(progress_row, note_var, 38).pack(side="left", fill="x", expand=True, padx=(6, 8))

    def save_progress(completed=False) -> None:
        item = selected_item()
        if not item:
            return
        try:
            value = float(timestamp_var.get() or 0)
            update_course_progress(engine_module, item["id"], value, completed=completed)
            course_status_var.set("进度已保存")
            refresh_courses()
        except Exception as exc:  # noqa: BLE001
            course_status_var.set(f"失败：{exc}")

    def save_note() -> None:
        item = selected_item()
        if not item:
            return
        try:
            add_timestamp_note(engine_module, item["id"], timestamp_var.get(), note_var.get())
            note_var.set("")
            course_status_var.set("时间戳笔记已保存")
        except Exception as exc:  # noqa: BLE001
            course_status_var.set(f"失败：{exc}")

    def open_player() -> None:
        item = selected_item()
        if not item:
            return
        try:
            open_local_player(engine_module, item["mediaId"], start_seconds=timestamp_var.get())
        except Exception as exc:  # noqa: BLE001
            course_status_var.set(f"失败：{exc}")

    def export_notes() -> None:
        course = selected_course()
        if not course:
            return
        try:
            result = export_course_notes(engine_module, course["id"])
            path = Path(result["pdf"] or result["html"])
            _open_path(path)
            course_status_var.set("已导出 PDF" if result["pdf"] else "已导出 HTML（未检测到可用于 PDF 的 Chromium）")
        except Exception as exc:  # noqa: BLE001
            course_status_var.set(f"失败：{exc}")

    course_actions = tk.Frame(course_tab, bg=ui.PANEL)
    course_actions.pack(fill="x", pady=(9, 0))
    ui.ActionButton(course_actions, text="创建课程", command=create_only, kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(course_actions, text="创建并下载在线课程", command=create_and_download, kind="secondary", compact=True).pack(side="left", padx=(6, 0))
    ui.ActionButton(course_actions, text="加入所选媒体", command=add_selected_media, kind="ghost", compact=True).pack(side="left", padx=(6, 0))
    ui.ActionButton(course_actions, text="播放器", command=open_player, kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(course_actions, text="导出笔记/PDF", command=export_notes, kind="ghost", compact=True).pack(side="right", padx=(0, 6))
    ui.ActionButton(course_actions, text="记笔记", command=save_note, kind="ghost", compact=True).pack(side="right", padx=(0, 6))
    ui.ActionButton(course_actions, text="完成", command=lambda: save_progress(True), kind="ghost", compact=True).pack(side="right", padx=(0, 6))
    ui.ActionButton(course_actions, text="保存进度", command=lambda: save_progress(False), kind="ghost", compact=True).pack(side="right", padx=(0, 6))
    ui._label(course_tab, variable=course_status_var, size=7, color=ui.MUTED).pack(anchor="w", pady=(7, 0))

    # Music
    music_tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14)
    notebook.add(music_tab, text="音乐")
    music_list = _listbox(music_tab, 20)
    music_list.pack(fill="both", expand=True)
    music_rows: list[dict] = []

    def refresh_music() -> None:
        music_rows[:] = music_library(engine_module)
        music_list.delete(0, "end")
        for item in music_rows:
            music_list.insert("end", f"{item.get('title') or item.get('fileName')} · {item.get('sourceHost') or 'local'}")
        if music_rows:
            music_list.selection_set(0)

    def play_music() -> None:
        selection = music_list.curselection()
        if not selection:
            return
        item = music_rows[selection[0]]
        try:
            open_local_player(engine_module, item["id"])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, str(exc), parent=dialog)

    music_actions = tk.Frame(music_tab, bg=ui.PANEL)
    music_actions.pack(fill="x", pady=(10, 0))
    ui.ActionButton(music_actions, text="刷新音乐库", command=refresh_music, kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(music_actions, text="播放", command=play_music, kind="secondary", compact=True).pack(side="right")

    # Books
    books_tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14)
    notebook.add(books_tab, text="EPUB")
    books_list = _listbox(books_tab, 18)
    books_list.pack(fill="both", expand=True)
    book_rows: list[dict] = []
    book_progress_var = tk.StringVar(value="0")

    def refresh_books() -> None:
        book_rows[:] = list_books(engine_module)
        books_list.delete(0, "end")
        for book in book_rows:
            books_list.insert("end", f"{book['title']} · {book['progressPercent']:.0f}%")
        if book_rows:
            books_list.selection_set(0)

    def import_book() -> None:
        value = filedialog.askopenfilename(parent=dialog, title="导入 EPUB", filetypes=(("EPUB", "*.epub"),))
        if not value:
            return
        try:
            import_epub(engine_module, Path(value))
            refresh_books()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, str(exc), parent=dialog)

    def selected_book() -> dict | None:
        selection = books_list.curselection()
        return book_rows[selection[0]] if selection else None

    def open_book() -> None:
        book = selected_book()
        if not book:
            return
        path = Path(book["readerHtml"])
        if path.is_file():
            webbrowser.open(path.resolve().as_uri())

    def save_book_progress() -> None:
        book = selected_book()
        if not book:
            return
        update_book_progress(engine_module, book["id"], book_progress_var.get())
        refresh_books()

    book_actions = tk.Frame(books_tab, bg=ui.PANEL)
    book_actions.pack(fill="x", pady=(10, 0))
    ui.ActionButton(book_actions, text="导入 EPUB", command=import_book, kind="secondary", compact=True).pack(side="left")
    ui.ActionButton(book_actions, text="阅读", command=open_book, kind="ghost", compact=True).pack(side="left", padx=(6, 0))
    ui._label(book_actions, "进度 %", size=7, color=ui.MUTED).pack(side="right", padx=(8, 0))
    _entry(book_actions, book_progress_var, 7).pack(side="right", padx=(6, 0))
    ui.ActionButton(book_actions, text="保存进度", command=save_book_progress, kind="ghost", compact=True).pack(side="right")

    # Spaced repetition
    review_tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14)
    notebook.add(review_tab, text="复习")
    due_list = _listbox(review_tab, 14)
    due_list.pack(fill="both", expand=True)
    due_rows: list[dict] = []
    front_var = tk.StringVar()
    back_var = tk.StringVar()
    reveal_var = tk.StringVar(value="选择卡片后点击显示答案")

    form = tk.Frame(review_tab, bg=ui.PANEL)
    form.pack(fill="x", pady=(10, 0))
    ui._label(form, "正面", size=7, color=ui.MUTED).grid(row=0, column=0, sticky="w")
    _entry(form, front_var, 34).grid(row=0, column=1, padx=(6, 12), sticky="ew")
    ui._label(form, "背面", size=7, color=ui.MUTED).grid(row=0, column=2, sticky="w")
    _entry(form, back_var, 34).grid(row=0, column=3, padx=(6, 0), sticky="ew")
    form.grid_columnconfigure(1, weight=1)
    form.grid_columnconfigure(3, weight=1)
    ui._label(review_tab, variable=reveal_var, size=9, color=ui.CYAN).pack(anchor="w", pady=(9, 0))

    def refresh_due() -> None:
        due_rows[:] = due_flashcards(engine_module, limit=100)
        due_list.delete(0, "end")
        for card in due_rows:
            due_list.insert("end", card["front"][:150])
        if due_rows:
            due_list.selection_set(0)
        reveal_var.set("选择卡片后点击显示答案")

    def add_card() -> None:
        try:
            create_flashcard(engine_module, front_var.get(), back_var.get())
            front_var.set("")
            back_var.set("")
            refresh_due()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, str(exc), parent=dialog)

    def selected_card() -> dict | None:
        selection = due_list.curselection()
        return due_rows[selection[0]] if selection else None

    def reveal_card() -> None:
        card = selected_card()
        if card:
            reveal_var.set(card["back"])

    def rate(value: int) -> None:
        card = selected_card()
        if not card:
            return
        review_flashcard(engine_module, card["id"], value)
        refresh_due()

    review_actions = tk.Frame(review_tab, bg=ui.PANEL)
    review_actions.pack(fill="x", pady=(9, 0))
    ui.ActionButton(review_actions, text="新增卡片", command=add_card, kind="secondary", compact=True).pack(side="left")
    ui.ActionButton(review_actions, text="显示答案", command=reveal_card, kind="ghost", compact=True).pack(side="left", padx=(6, 0))
    for rating, label in ((0, "忘记"), (3, "困难"), (4, "良好"), (5, "简单")):
        ui.ActionButton(review_actions, text=label, command=lambda value=rating: rate(value), kind="ghost", compact=True).pack(side="right", padx=(6, 0))

    def close() -> None:
        window._learning_workspace_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh_courses()
    refresh_library()
    refresh_music()
    refresh_books()
    refresh_due()


def _add_learning_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_learning_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "学习工作台", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(text, "课程/播放器/时间戳笔记/PDF · 音乐 · EPUB · 间隔重复", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(
        card,
        text="打开学习工作台",
        command=lambda: _show_learning_workspace(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_learning_entry_built = True


def install_desktop_learning(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_learning_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-learning",
        lambda window: _add_learning_entry(window, engine_module),
        order=60,
    )
    window_cls._galaxy_desktop_learning_installed = True
    return window_cls


def run_desktop_learning_self_test() -> None:
    assert callable(create_course)
    assert callable(create_flashcard)
