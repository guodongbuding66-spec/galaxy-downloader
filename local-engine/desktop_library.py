from __future__ import annotations

import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

import desktop_extras as extras
import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook, register_desktop_presenter, show_desktop_presenter
from media_library import (
    list_media_items,
    media_library_path,
    media_library_summary,
    search_media_items,
    sync_media_library,
)

MEDIA_FILTERS = {
    "全部": None,
    "视频": "video",
    "音频": "audio",
    "图片": "image",
    "其他": "other",
}
MEDIA_LABELS = {
    "video": "视频",
    "audio": "音频",
    "image": "图片",
    "other": "其他",
}


def _window_exists(window: tk.Misc | None) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def _format_bytes(value: object) -> str:
    try:
        size = max(0, int(value or 0))
    except (TypeError, ValueError):
        return "—"
    if size <= 0:
        return "—"
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(size)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    return f"{amount:.1f} {unit}" if unit != "B" else f"{size} B"


def _format_duration(value: object) -> str:
    try:
        seconds = max(0, int(round(float(value or 0))))
    except (TypeError, ValueError):
        return "—"
    if not seconds:
        return "—"
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


def _format_time(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    return text.replace("T", " ").replace("Z", " UTC")[:22]


def _safe_item_path(engine_module, item_id: object) -> Path | None:
    clean_id = str(item_id or "").strip()
    if not clean_id:
        return None
    try:
        database = media_library_path(engine_module)
        with sqlite3.connect(database, timeout=3.0) as connection:
            row = connection.execute("SELECT file_path FROM media_items WHERE id=?", (clean_id,)).fetchone()
        if row is None:
            return None
        candidate = Path(str(row[0])).expanduser().resolve(strict=False)
        root = Path(engine_module.default_download_dir()).expanduser().resolve(strict=False)
        candidate.relative_to(root)
        return candidate
    except (OSError, RuntimeError, sqlite3.Error, ValueError):
        return None


def _selected_item(tree: ttk.Treeview, items: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    selection = tree.selection()
    return items.get(selection[0]) if selection else None


def _show_media_library(window, engine_module) -> None:
    existing = getattr(window, "_media_library_window", None)
    if _window_exists(existing):
        existing.deiconify()
        existing.lift()
        try:
            existing.focus_force()
        except tk.TclError:
            pass
        return

    dialog = tk.Toplevel(window)
    window._media_library_window = dialog
    dialog.title("媒体库 · Galaxy Local Engine")
    dialog.geometry("1080x650")
    dialog.minsize(860, 500)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    header = tk.Frame(shell, bg=ui.BG)
    header.pack(fill="x")
    title = tk.Frame(header, bg=ui.BG)
    title.pack(side="left", fill="x", expand=True)
    ui._label(title, "媒体库", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        title,
        "从本机下载历史建立可搜索目录。数据库只保存 Galaxy 下载目录内的媒体；文件丢失时只标记缺失，不会删除记录。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=760,
        justify="left",
    ).pack(anchor="w", pady=(4, 0))

    summary_var = tk.StringVar(value="同步中…")
    ui._label(header, variable=summary_var, size=8, weight="bold", color=ui.CYAN, bg=ui.BG).pack(side="right", anchor="n")

    filters = tk.Frame(shell, bg=ui.BG)
    filters.pack(fill="x", pady=(12, 10))
    search_var = tk.StringVar()
    type_var = tk.StringVar(value="全部")
    availability_var = tk.StringVar(value="全部文件")
    ui._label(filters, "搜索", size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    search_entry = tk.Entry(
        filters,
        textvariable=search_var,
        width=34,
        font=("Segoe UI", 9),
        bg=ui.PANEL,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
    )
    search_entry.pack(side="left", padx=(7, 12), ipady=5)
    ui._label(filters, "类型", size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    ttk.Combobox(
        filters,
        textvariable=type_var,
        values=tuple(MEDIA_FILTERS),
        width=8,
        state="readonly",
        style="Galaxy.TCombobox",
    ).pack(side="left", padx=(7, 12))
    ttk.Combobox(
        filters,
        textvariable=availability_var,
        values=("全部文件", "本地可用", "文件缺失"),
        width=10,
        state="readonly",
        style="Galaxy.TCombobox",
    ).pack(side="left")
    count_var = tk.StringVar(value="0 项")
    ui._label(filters, variable=count_var, size=8, color=ui.SUBTLE, bg=ui.BG).pack(side="right")

    card = tk.Frame(shell, bg=ui.PANEL, padx=12, pady=12, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)
    style = ttk.Style(dialog)
    style.configure(
        "Galaxy.Library.Treeview",
        background=ui.PANEL,
        fieldbackground=ui.PANEL,
        foreground=ui.TEXT,
        rowheight=30,
        borderwidth=0,
    )
    style.configure(
        "Galaxy.Library.Treeview.Heading",
        background=ui.PANEL_2,
        foreground=ui.MUTED,
        relief="flat",
        font=("Segoe UI", 8, "bold"),
    )
    style.map(
        "Galaxy.Library.Treeview",
        background=[("selected", ui.PANEL_3)],
        foreground=[("selected", ui.TEXT)],
    )

    columns = ("time", "type", "source", "quality", "duration", "size", "state", "title")
    tree = ttk.Treeview(card, columns=columns, show="headings", style="Galaxy.Library.Treeview", selectmode="browse")
    headings = {
        "time": ("完成时间", 145),
        "type": ("类型", 58),
        "source": ("来源", 120),
        "quality": ("画质", 64),
        "duration": ("时长", 62),
        "size": ("大小", 72),
        "state": ("文件", 66),
        "title": ("标题 / 文件名", 410),
    }
    for key, (label, width) in headings.items():
        tree.heading(key, text=label)
        tree.column(key, width=width, minwidth=52, stretch=key == "title")
    scrollbar = ttk.Scrollbar(card, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)

    item_by_iid: dict[str, dict[str, Any]] = {}
    open_button: ui.ActionButton | None = None
    reveal_button: ui.ActionButton | None = None

    def selected() -> dict[str, Any] | None:
        return _selected_item(tree, item_by_iid)

    def selection_changed(_event=None) -> None:
        item = selected()
        usable = bool(item and item.get("available"))
        if open_button is not None:
            open_button.state(["!disabled"] if usable else ["disabled"])
        if reveal_button is not None:
            reveal_button.state(["!disabled"] if usable else ["disabled"])

    def refresh(*_args, sync: bool = False) -> None:
        current = selected()
        selected_id = str(current.get("id") or "") if current else ""
        if sync:
            try:
                sync_media_library(engine_module)
            except Exception as exc:  # noqa: BLE001
                messagebox.showwarning(engine_module.APP_NAME, f"媒体库同步失败：\n{exc}", parent=dialog)

        query = search_var.get().strip()
        media_type = MEDIA_FILTERS.get(type_var.get())
        try:
            if query:
                items = search_media_items(engine_module, query, limit=500)
                if media_type:
                    items = [item for item in items if item.get("mediaType") == media_type]
            else:
                items = list_media_items(engine_module, limit=500, media_type=media_type)
            summary = media_library_summary(engine_module)
        except Exception as exc:  # noqa: BLE001
            items = []
            summary = None
            summary_var.set(f"媒体库不可用 · {exc}")

        availability = availability_var.get()
        if availability == "本地可用":
            items = [item for item in items if item.get("available")]
        elif availability == "文件缺失":
            items = [item for item in items if not item.get("available")]

        for iid in tree.get_children():
            tree.delete(iid)
        item_by_iid.clear()
        for index, item in enumerate(items):
            iid = str(index)
            item_by_iid[iid] = item
            tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    _format_time(item.get("finishedAt")),
                    MEDIA_LABELS.get(str(item.get("mediaType")), str(item.get("mediaType") or "—")),
                    item.get("sourceHost") or "—",
                    item.get("videoQuality") or item.get("audioQuality") or "—",
                    _format_duration(item.get("durationSeconds")),
                    _format_bytes(item.get("sizeBytes")),
                    "可用" if item.get("available") else "缺失",
                    item.get("title") or item.get("fileName") or "—",
                ),
            )
        count_var.set(f"{len(items)} 项")
        if summary is not None:
            summary_var.set(
                f"共 {summary.total} · 可用 {summary.available} · 缺失 {summary.missing} · 视频 {summary.video} · 音频 {summary.audio}"
            )
        if selected_id:
            for iid, item in item_by_iid.items():
                if str(item.get("id") or "") == selected_id:
                    tree.selection_set(iid)
                    break
        if not tree.selection() and tree.get_children():
            tree.selection_set(tree.get_children()[0])
        selection_changed()

    def path_for_selected() -> Path | None:
        item = selected()
        path = _safe_item_path(engine_module, item.get("id")) if item else None
        return path if path is not None and path.exists() else None

    def open_selected() -> None:
        path = path_for_selected()
        if path is None:
            messagebox.showinfo(engine_module.APP_NAME, "这个媒体文件已不可用。点击“重新同步”可刷新缺失状态。", parent=dialog)
            return
        try:
            extras._open_path(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, f"无法打开文件：\n{exc}", parent=dialog)

    def reveal_selected() -> None:
        path = path_for_selected()
        if path is None:
            messagebox.showinfo(engine_module.APP_NAME, "这个媒体文件已不可用。", parent=dialog)
            return
        try:
            extras._open_path(path, select_file=True)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, f"无法定位文件：\n{exc}", parent=dialog)

    def copy_source() -> None:
        item = selected()
        value = str(item.get("sourceUrl") or "") if item else ""
        if not value:
            return
        dialog.clipboard_clear()
        dialog.clipboard_append(value)
        dialog.update_idletasks()

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    ui.ActionButton(footer, text="重新同步", command=lambda: refresh(sync=True), kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(footer, text="复制来源", command=copy_source, kind="ghost", compact=True).pack(side="right")
    reveal_button = ui.ActionButton(footer, text="定位文件", command=reveal_selected, kind="ghost", compact=True)
    reveal_button.pack(side="right", padx=(0, 7))
    open_button = ui.ActionButton(footer, text="打开文件", command=open_selected, kind="primary", compact=True)
    open_button.pack(side="right", padx=(0, 7))

    tree.bind("<<TreeviewSelect>>", selection_changed)
    tree.bind("<Double-1>", lambda _event: open_selected())
    search_var.trace_add("write", lambda *_args: refresh())
    type_var.trace_add("write", lambda *_args: refresh())
    availability_var.trace_add("write", lambda *_args: refresh())

    def close() -> None:
        window._media_library_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh(sync=True)
    search_entry.focus_set()


def install_desktop_library(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_library_installed", False):
        return window_cls

    register_desktop_presenter(
        window_cls,
        "library",
        "desktop-library",
        lambda window: _show_media_library(window, engine_module),
        order=145,
    )

    def after_build_ui(window) -> None:
        queue_head = window._queue_clear_button.master
        window._media_library_button = ui.ActionButton(
            queue_head,
            text="媒体库",
            command=lambda: show_desktop_presenter(window, "library"),
            kind="ghost",
            compact=True,
        )
        window._media_library_button.pack(side="right", anchor="n", padx=(0, 5))

    register_after_build_ui_hook(window_cls, "desktop-library", after_build_ui, order=145)
    window_cls._galaxy_desktop_library_installed = True
    engine_module._galaxy_desktop_library_installed = True
    return window_cls


def run_desktop_library_self_test() -> None:
    assert _format_bytes(1024) == "1.0 KB"
    assert _format_duration(125) == "2:05"
    assert MEDIA_FILTERS["视频"] == "video"

    class Window:
        pass

    class Engine:
        EngineWindow = Window

    install_desktop_library(Engine)
    assert Window._galaxy_desktop_library_installed is True
    assert Engine._galaxy_desktop_library_installed is True
