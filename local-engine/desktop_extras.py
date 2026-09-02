from __future__ import annotations

import os
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

import desktop_ui as ui
from desktop_hooks import (
    register_after_build_ui_hook,
    register_desktop_presenter,
    register_queue_tick_hook,
    run_history_button_hooks,
    run_job_lines_hooks,
    show_desktop_presenter,
)
from job_history import clear_history, load_history


STATE_LABELS = {
    "completed": "完成",
    "failed": "失败",
    "cancelled": "取消",
}


def _tiny_button(master, text: str, command: Callable[[], None], *, disabled: bool = False) -> tk.Button:
    button = tk.Button(
        master,
        text=text,
        command=command,
        font=("Segoe UI", 8, "bold"),
        bg=ui.PANEL_2,
        fg=ui.SUBTLE,
        activebackground=ui.PANEL_3,
        activeforeground=ui.TEXT,
        disabledforeground=ui.BORDER,
        relief="flat",
        bd=0,
        highlightthickness=0,
        cursor="hand2" if not disabled else "arrow",
        padx=3,
        pady=2,
    )
    if disabled:
        button.configure(state="disabled")
    return button


def _open_path(path: Path, *, select_file: bool = False) -> None:
    target = path
    if select_file and path.exists() and path.is_file():
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
            return
        target = path.parent
    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])


def _current_file(window) -> Path | None:
    value = getattr(window, "last_path", None)
    if not value:
        return None
    try:
        path = Path(value)
        return path if path.exists() else None
    except (OSError, TypeError, ValueError):
        return None


def _open_current_file(window, engine_module) -> None:
    path = _current_file(window)
    if path is None:
        messagebox.showinfo(engine_module.APP_NAME, "当前没有可打开的已完成文件。", parent=window)
        return
    try:
        _open_path(path)
    except Exception as exc:  # noqa: BLE001
        messagebox.showerror(engine_module.APP_NAME, f"无法打开文件：\n{exc}", parent=window)


def _format_time(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    return text.replace("T", " ").replace("Z", " UTC")[:22]


def _show_history(window, engine_module) -> None:
    existing = getattr(window, "_history_window", None)
    if existing is not None:
        try:
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return
        except tk.TclError:
            pass

    dialog = tk.Toplevel(window)
    window._history_window = dialog
    dialog.title("下载历史 · Galaxy Local Engine")
    dialog.geometry("900x540")
    dialog.minsize(760, 430)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "下载历史", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "仅保存在本机 state/download-history.json；来源链接自动移除查询参数、片段和凭据。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(4, 12))

    card = tk.Frame(shell, bg=ui.PANEL, padx=12, pady=12, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)

    style = ttk.Style(dialog)
    style.configure(
        "Galaxy.Treeview",
        background=ui.PANEL,
        fieldbackground=ui.PANEL,
        foreground=ui.TEXT,
        rowheight=28,
        borderwidth=0,
    )
    style.configure(
        "Galaxy.Treeview.Heading",
        background=ui.PANEL_2,
        foreground=ui.MUTED,
        relief="flat",
        font=("Segoe UI", 8, "bold"),
    )
    style.map("Galaxy.Treeview", background=[("selected", ui.PANEL_3)], foreground=[("selected", ui.TEXT)])

    columns = ("time", "state", "source", "quality", "file")
    tree = ttk.Treeview(card, columns=columns, show="headings", style="Galaxy.Treeview", selectmode="browse")
    headings = {
        "time": ("完成时间", 145),
        "state": ("状态", 65),
        "source": ("来源", 135),
        "quality": ("画质", 70),
        "file": ("文件", 380),
    }
    for key, (title, width) in headings.items():
        tree.heading(key, text=title)
        tree.column(key, width=width, minwidth=55, stretch=key == "file")
    scrollbar = ttk.Scrollbar(card, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)

    item_by_iid: dict[str, dict[str, Any]] = {}

    def refresh() -> None:
        for iid in tree.get_children():
            tree.delete(iid)
        item_by_iid.clear()
        history = load_history(engine_module)
        for index, item in enumerate(history):
            iid = str(index)
            item_by_iid[iid] = item
            tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    _format_time(item.get("finishedAt")),
                    STATE_LABELS.get(str(item.get("state")), str(item.get("state") or "—")),
                    item.get("sourceHost") or "—",
                    item.get("videoQuality") or "—",
                    item.get("fileName") or item.get("label") or "—",
                ),
            )
        if history:
            tree.selection_set("0")
        window._history_next_refresh = 0.0
        _sync_history_button(window, engine_module, force=True)

    def selected_item() -> dict[str, Any] | None:
        selection = tree.selection()
        return item_by_iid.get(selection[0]) if selection else None

    def open_selected_file() -> None:
        item = selected_item()
        path = Path(str(item.get("filePath"))) if item and item.get("filePath") else None
        if path is None or not path.exists():
            messagebox.showinfo(engine_module.APP_NAME, "这个历史任务没有可用的本地文件。", parent=dialog)
            return
        try:
            _open_path(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, f"无法打开文件：\n{exc}", parent=dialog)

    def reveal_selected() -> None:
        item = selected_item()
        path = Path(str(item.get("filePath"))) if item and item.get("filePath") else None
        if path is None or not path.exists():
            messagebox.showinfo(engine_module.APP_NAME, "这个历史任务没有可定位的本地文件。", parent=dialog)
            return
        try:
            _open_path(path, select_file=True)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, f"无法定位文件：\n{exc}", parent=dialog)

    def copy_source() -> None:
        item = selected_item()
        value = str(item.get("sourceUrl") or "") if item else ""
        if not value:
            return
        dialog.clipboard_clear()
        dialog.clipboard_append(value)
        dialog.update_idletasks()

    def clear_all() -> None:
        if not tree.get_children():
            return
        if not messagebox.askyesno(
            engine_module.APP_NAME,
            "清空本机下载历史？\n\n不会删除任何已经下载的媒体文件。",
            parent=dialog,
        ):
            return
        clear_history(engine_module)
        refresh()

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    ui.ActionButton(footer, text="清空历史", command=clear_all, kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(footer, text="复制来源", command=copy_source, kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(footer, text="定位文件", command=reveal_selected, kind="ghost", compact=True).pack(side="right", padx=(0, 7))
    ui.ActionButton(footer, text="打开文件", command=open_selected_file, kind="secondary", compact=True).pack(side="right", padx=(0, 7))
    tree.bind("<Double-1>", lambda _event: open_selected_file())

    def close() -> None:
        window._history_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh()


def _job_lines(window) -> list[tuple[str, str]]:
    job = getattr(window, "job", None)
    if job is None:
        return run_job_lines_hooks(window, [("状态", "当前没有任务")])

    start = getattr(job, "segment_start", None)
    end = getattr(job, "segment_end", None)
    segment = "完整视频" if start is None or end is None else f"{start:g}s → {end:g}s"
    sponsors = ", ".join(getattr(job, "sponsorblock_categories", ()) or ()) or "关闭"
    subtitle_languages = ", ".join(getattr(job, "subtitle_languages", ()) or ()) or "自动"
    audio_languages = ", ".join(getattr(job, "audio_languages", ()) or ()) or "自动"
    source = str(getattr(job, "source_url", "") or "")
    try:
        from job_history import _redacted_source_url

        source = _redacted_source_url(source)[0] or source
    except Exception:
        pass
    lines = [
        ("来源", source),
        ("视频画质", str(getattr(job, "video_quality", "best") or "best")),
        ("音频质量", str(getattr(job, "audio_quality", "best") or "best")),
        ("包含音频", "是" if bool(getattr(job, "include_audio", True)) else "否"),
        ("字幕", "是" if bool(getattr(job, "include_subtitle", False)) else "否"),
        ("字幕来源", str(getattr(job, "subtitle_mode", "both") or "both")),
        ("字幕语言", subtitle_languages),
        ("音轨语言", audio_languages),
        ("片段", segment),
        ("章节拆分", "开启" if bool(getattr(job, "split_chapters", False)) else "关闭"),
        ("SponsorBlock", sponsors),
        ("aria2c", "开启" if bool(getattr(job, "use_aria2c", False)) else "关闭"),
        ("集合模式", str(getattr(job, "collection_mode", "single") or "single")),
    ]
    return run_job_lines_hooks(window, lines)


def _show_job_details(window, engine_module) -> None:
    dialog = tk.Toplevel(window)
    dialog.title("任务详情 · Galaxy Local Engine")
    dialog.geometry("650x520")
    dialog.minsize(560, 430)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "当前任务详情", size=15, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(shell, "展示最终交给本机下载器的关键参数。", size=8, color=ui.MUTED, bg=ui.BG).pack(anchor="w", pady=(3, 12))

    card = tk.Frame(shell, bg=ui.PANEL, padx=14, pady=10, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)
    lines = _job_lines(window)
    for index, (name, value) in enumerate(lines):
        row = tk.Frame(card, bg=ui.PANEL, pady=5)
        row.pack(fill="x")
        ui._label(row, name, size=8, weight="bold", color=ui.SUBTLE).pack(side="left", anchor="n")
        ui._label(
            row,
            value or "—",
            size=8,
            color=ui.TEXT,
            wraplength=460,
            justify="right",
        ).pack(side="right", anchor="n")
        if index < len(lines) - 1:
            ui._divider(card).pack(fill="x")

    def copy_details() -> None:
        text = "\n".join(f"{name}: {value}" for name, value in lines)
        dialog.clipboard_clear()
        dialog.clipboard_append(text)
        dialog.update_idletasks()

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    ui.ActionButton(footer, text="复制任务信息", command=copy_details, kind="secondary", compact=True).pack(side="right")


def _toggle_queue_pause(window) -> None:
    toggle = getattr(window, "toggle_queue_paused", None)
    if callable(toggle):
        toggle()
        _sync_pause_state(window)


def _sync_pause_state(window) -> None:
    paused = bool(getattr(window, "queue_paused", False))
    button = getattr(window, "_queue_pause_button", None)
    if button is not None:
        if paused:
            button.configure(text="继续队列")
        elif bool(getattr(window, "running", False)):
            button.configure(text="完成后暂停")
        else:
            button.configure(text="暂停队列")
    if paused:
        try:
            waiting = len(getattr(window, "pending_jobs", []))
            active = 1 if bool(getattr(window, "running", False)) else 0
            window._queue_count_var.set(f"当前 {active} · 等待 {waiting} · 已暂停")
            window._queue_summary_var.set(f"等待 {waiting} 项 · 暂停")
        except Exception:
            pass


def _sync_history_button(window, engine_module, *, force: bool = False) -> None:
    button = getattr(window, "_history_button", None)
    if button is None:
        return
    now = time.monotonic()
    if not force and now < float(getattr(window, "_history_next_refresh", 0.0) or 0.0):
        return
    window._history_next_refresh = now + 5.0
    try:
        count = len(load_history(engine_module))
    except Exception:
        count = 0
    text = run_history_button_hooks(window, engine_module, count, f"历史 {count}")
    button.configure(text=text)


def _augment_queue_rows(original_render: Callable[[Any, list[Any]], None]):
    def render(window, pending: list[Any]) -> None:
        original_render(window, pending)
        if len(pending) < 2:
            return
        panel = window._queue_panel
        rows = [child for child in panel.winfo_children() if isinstance(child, tk.Frame)]
        for index, queued in enumerate(pending[:8]):
            if index >= len(rows):
                break
            row = rows[index]
            job_id = str(getattr(queued, "job_id", "") or "")
            if not job_id:
                continue
            down_disabled = index >= len(pending) - 1
            _tiny_button(
                row,
                "↓",
                lambda value=job_id: getattr(window, "move_queued_job")(value, 1),
                disabled=down_disabled,
            ).pack(side="right", padx=(1, 0))
            _tiny_button(
                row,
                "↑",
                lambda value=job_id: getattr(window, "move_queued_job")(value, -1),
                disabled=index == 0,
            ).pack(side="right", padx=(5, 0))

    return render


def install_desktop_extras(engine_module):
    """Layer v0.11 workbench controls on top of the v0.10 desktop UI."""
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_extras_installed", False):
        return window_cls

    ui._render_queue = _augment_queue_rows(ui._render_queue)
    register_desktop_presenter(
        window_cls,
        "history",
        "desktop-extras",
        lambda window: _show_history(window, engine_module),
        order=110,
    )

    def after_build_ui(window) -> None:
        queue_head = window._queue_clear_button.master
        window._history_button = ui.ActionButton(
            queue_head,
            text="历史 0",
            command=lambda: show_desktop_presenter(window, "history"),
            kind="ghost",
            compact=True,
        )
        window._history_button.pack(side="right", anchor="n", padx=(0, 5))
        window._queue_pause_button = ui.ActionButton(
            queue_head,
            text="完成后暂停" if bool(getattr(window, "running", False)) else "暂停队列",
            command=lambda: _toggle_queue_pause(window),
            kind="ghost",
            compact=True,
        )
        window._queue_pause_button.pack(side="right", anchor="n", padx=(0, 5))

        actions = window.cancel_button.master
        window._job_detail_button = ui.ActionButton(
            actions,
            text="任务详情",
            command=lambda: _show_job_details(window, engine_module),
            kind="ghost",
            compact=True,
        )
        window._job_detail_button.pack(side="right", padx=(0, 7))
        window._open_file_button = ui.ActionButton(
            actions,
            text="打开文件",
            command=lambda: _open_current_file(window, engine_module),
            kind="secondary",
            compact=True,
        )
        window._open_file_button.pack(side="right", padx=(0, 7))
        window._history_next_refresh = 0.0
        _sync_pause_state(window)
        _sync_history_button(window, engine_module, force=True)

    def queue_tick_hook(window) -> None:
        _sync_pause_state(window)
        _sync_history_button(window, engine_module)

    register_after_build_ui_hook(window_cls, "desktop-extras", after_build_ui, order=110)
    register_queue_tick_hook(window_cls, "desktop-extras", queue_tick_hook, order=110)
    window_cls._galaxy_desktop_extras_installed = True
    return window_cls
