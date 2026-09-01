from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

import desktop_extras as extras
import desktop_ui as ui
from job_history import clear_history, load_history
from workspace_policy import (
    DEFAULT_WORKSPACE_PREFERENCES,
    load_workspace_preferences,
    output_template,
    save_workspace_preferences,
)

STYLE_LABELS = {
    "title-id": "标题 [ID]（默认）",
    "title": "仅标题",
    "id-title": "ID - 标题",
}
STYLE_KEYS = {label: key for key, label in STYLE_LABELS.items()}
STATUS_FILTERS = {"全部": "", "完成": "completed", "失败": "failed", "取消": "cancelled"}
STATE_LABELS = {"completed": "完成", "failed": "失败", "cancelled": "取消"}


def _window_exists(window: tk.Misc | None) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def _format_time(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    return text.replace("T", " ").replace("Z", " UTC")[:22]


def _selected_history_item(tree: ttk.Treeview, items: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    selection = tree.selection()
    return items.get(selection[0]) if selection else None


def _retry_history_item(window, engine_module, item: dict[str, Any], parent: tk.Misc) -> None:
    payload = dict(item.get("retryPayload") or {})
    source_url = str(payload.get("sourceUrl") or "").strip()
    if not source_url:
        messagebox.showinfo(
            engine_module.APP_NAME,
            "这个历史任务没有可安全重试的来源地址。\n\n为避免把 token、登录参数或跟踪参数写入历史，Galaxy 不会保存未知查询参数。",
            parent=parent,
        )
        return

    # A deliberate retry must not be suppressed by the optional download archive.
    payload["skipPreviouslyDownloaded"] = False
    payload["displayTitle"] = str(item.get("fileName") or item.get("label") or item.get("sourceHost") or "历史任务重试")[:120]

    def worker() -> None:
        try:
            result = window.submit_bridge_job(payload)
            accepted = bool(getattr(result, "accepted", False))
            message = str(getattr(result, "message", ""))
            code = str(getattr(result, "code", ""))
        except Exception as exc:  # noqa: BLE001
            accepted = False
            message = str(exc)
            code = ""

        def finish() -> None:
            if not _window_exists(parent):
                return
            if accepted:
                window.set_status(
                    window.status_var.get(),
                    "历史任务已重新提交；如果当前任务正在运行，它会进入等待队列。",
                )
            else:
                messagebox.showwarning(
                    engine_module.APP_NAME,
                    f"无法重新提交历史任务。\n\n{message or code or '未知错误'}",
                    parent=parent,
                )

        try:
            window.after(0, finish)
        except tk.TclError:
            pass

    threading.Thread(target=worker, daemon=True).start()


def _show_history_manager(window, engine_module) -> None:
    existing = getattr(window, "_history_window", None)
    if _window_exists(existing):
        existing.deiconify()
        existing.lift()
        try:
            existing.focus_force()
        except tk.TclError:
            pass
        return

    dialog = tk.Toplevel(window)
    window._history_window = dialog
    dialog.title("下载历史 · Galaxy Local Engine")
    dialog.geometry("980x600")
    dialog.minsize(820, 470)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "下载历史", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "支持搜索、状态筛选和安全重试。历史只保存在本机；未知 URL 查询参数不会持久化。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(4, 12))

    filters = tk.Frame(shell, bg=ui.BG)
    filters.pack(fill="x", pady=(0, 10))
    search_var = tk.StringVar()
    status_var = tk.StringVar(value="全部")
    ui._label(filters, "搜索", size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    search = tk.Entry(
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
    search.pack(side="left", padx=(7, 12), ipady=5)
    ui._label(filters, "状态", size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    ttk.Combobox(
        filters,
        textvariable=status_var,
        values=tuple(STATUS_FILTERS),
        width=8,
        state="readonly",
        style="Galaxy.TCombobox",
    ).pack(side="left", padx=(7, 0))
    count_var = tk.StringVar(value="0 条")
    ui._label(filters, variable=count_var, size=8, color=ui.SUBTLE, bg=ui.BG).pack(side="right")

    card = tk.Frame(shell, bg=ui.PANEL, padx=12, pady=12, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)

    style = ttk.Style(dialog)
    style.configure(
        "Galaxy.History.Treeview",
        background=ui.PANEL,
        fieldbackground=ui.PANEL,
        foreground=ui.TEXT,
        rowheight=29,
        borderwidth=0,
    )
    style.configure(
        "Galaxy.History.Treeview.Heading",
        background=ui.PANEL_2,
        foreground=ui.MUTED,
        relief="flat",
        font=("Segoe UI", 8, "bold"),
    )
    style.map(
        "Galaxy.History.Treeview",
        background=[("selected", ui.PANEL_3)],
        foreground=[("selected", ui.TEXT)],
    )

    columns = ("time", "state", "source", "quality", "duration", "file")
    tree = ttk.Treeview(
        card,
        columns=columns,
        show="headings",
        style="Galaxy.History.Treeview",
        selectmode="browse",
    )
    headings = {
        "time": ("完成时间", 145),
        "state": ("状态", 62),
        "source": ("来源", 130),
        "quality": ("画质", 65),
        "duration": ("耗时", 70),
        "file": ("文件 / 任务", 405),
    }
    for key, (title, width) in headings.items():
        tree.heading(key, text=title)
        tree.column(key, width=width, minwidth=55, stretch=key == "file")
    scrollbar = ttk.Scrollbar(card, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)

    item_by_iid: dict[str, dict[str, Any]] = {}
    retry_button: ui.ActionButton | None = None

    def selection_changed(_event=None) -> None:
        if retry_button is None:
            return
        item = _selected_history_item(tree, item_by_iid)
        retry_button.state(["!disabled"] if item and item.get("retryable") else ["disabled"])

    def refresh(*_args) -> None:
        selected_id = None
        current = _selected_history_item(tree, item_by_iid)
        if current:
            selected_id = str(current.get("id") or "")
        for iid in tree.get_children():
            tree.delete(iid)
        item_by_iid.clear()

        query = search_var.get().strip().lower()
        state_filter = STATUS_FILTERS.get(status_var.get(), "")
        shown = 0
        for index, item in enumerate(load_history(engine_module)):
            if state_filter and str(item.get("state")) != state_filter:
                continue
            haystack = " ".join(
                str(item.get(key) or "")
                for key in ("label", "fileName", "sourceHost", "sourceUrl", "detail", "videoQuality")
            ).lower()
            if query and query not in haystack:
                continue
            iid = str(index)
            item_by_iid[iid] = item
            duration = float(item.get("durationSeconds") or 0)
            tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    _format_time(item.get("finishedAt")),
                    STATE_LABELS.get(str(item.get("state")), str(item.get("state") or "—")),
                    item.get("sourceHost") or "—",
                    item.get("videoQuality") or "—",
                    f"{duration:.1f}s" if duration else "—",
                    item.get("fileName") or item.get("label") or "—",
                ),
            )
            shown += 1
        count_var.set(f"{shown} 条")
        if selected_id:
            for iid, item in item_by_iid.items():
                if str(item.get("id") or "") == selected_id:
                    tree.selection_set(iid)
                    break
        if not tree.selection() and tree.get_children():
            tree.selection_set(tree.get_children()[0])
        selection_changed()
        window._history_next_refresh = 0.0
        try:
            extras._sync_history_button(window, engine_module, force=True)
        except Exception:
            pass

    def open_selected_file() -> None:
        item = _selected_history_item(tree, item_by_iid)
        path = Path(str(item.get("filePath"))) if item and item.get("filePath") else None
        if path is None or not path.exists():
            messagebox.showinfo(engine_module.APP_NAME, "这个历史任务没有可用的本地文件。", parent=dialog)
            return
        try:
            extras._open_path(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, f"无法打开文件：\n{exc}", parent=dialog)

    def reveal_selected() -> None:
        item = _selected_history_item(tree, item_by_iid)
        path = Path(str(item.get("filePath"))) if item and item.get("filePath") else None
        if path is None or not path.exists():
            messagebox.showinfo(engine_module.APP_NAME, "这个历史任务没有可定位的本地文件。", parent=dialog)
            return
        try:
            extras._open_path(path, select_file=True)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, f"无法定位文件：\n{exc}", parent=dialog)

    def copy_source() -> None:
        item = _selected_history_item(tree, item_by_iid)
        value = str(item.get("sourceUrl") or "") if item else ""
        if not value:
            return
        dialog.clipboard_clear()
        dialog.clipboard_append(value)
        dialog.update_idletasks()

    def retry_selected() -> None:
        item = _selected_history_item(tree, item_by_iid)
        if item:
            _retry_history_item(window, engine_module, item, dialog)

    def clear_all() -> None:
        if not load_history(engine_module):
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
    retry_button = ui.ActionButton(footer, text="重新下载", command=retry_selected, kind="primary", compact=True)
    retry_button.pack(side="right", padx=(0, 7))
    retry_button.state(["disabled"])

    tree.bind("<<TreeviewSelect>>", selection_changed)
    tree.bind("<Double-1>", lambda _event: open_selected_file())
    search_var.trace_add("write", lambda *_args: refresh())
    status_var.trace_add("write", lambda *_args: refresh())

    def close() -> None:
        window._history_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh()


def _pending_snapshot(window) -> list[Any]:
    lock = getattr(window, "_queue_lock", None)
    if lock is None:
        return list(getattr(window, "pending_jobs", []))
    with lock:
        return list(getattr(window, "pending_jobs", []))


def _show_queue_manager(window, engine_module) -> None:
    existing = getattr(window, "_queue_manager_window", None)
    if _window_exists(existing):
        existing.deiconify()
        existing.lift()
        return

    dialog = tk.Toplevel(window)
    window._queue_manager_window = dialog
    dialog.title("队列管理 · Galaxy Local Engine")
    dialog.geometry("760x520")
    dialog.minsize(650, 420)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "等待队列管理", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "可多选批量移除或整体调整优先级；这些操作不会中断当前正在下载的任务。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(4, 12))

    status_var = tk.StringVar()
    ui._label(shell, variable=status_var, size=8, weight="bold", color=ui.CYAN, bg=ui.BG).pack(anchor="w", pady=(0, 8))

    card = tk.Frame(shell, bg=ui.PANEL, padx=10, pady=10, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)
    columns = ("position", "title", "source")
    tree = ttk.Treeview(card, columns=columns, show="headings", selectmode="extended", style="Galaxy.History.Treeview")
    tree.heading("position", text="#")
    tree.heading("title", text="任务")
    tree.heading("source", text="来源")
    tree.column("position", width=45, stretch=False, anchor="center")
    tree.column("title", width=450, minwidth=250, stretch=True)
    tree.column("source", width=170, minwidth=120, stretch=False)
    scrollbar = ttk.Scrollbar(card, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    id_by_iid: dict[str, str] = {}
    last_signature: tuple[str, ...] = ()

    def selected_ids() -> list[str]:
        return [id_by_iid[iid] for iid in tree.selection() if iid in id_by_iid]

    def refresh(force: bool = False) -> None:
        nonlocal last_signature
        pending = _pending_snapshot(window)
        signature = tuple(str(getattr(item, "job_id", "")) for item in pending)
        paused = bool(getattr(window, "queue_paused", False))
        active = 1 if bool(getattr(window, "running", False)) else 0
        status_var.set(f"当前 {active} · 等待 {len(pending)} · {'队列已暂停' if paused else '自动继续'}")
        if not force and signature == last_signature:
            return
        selected = set(selected_ids())
        for iid in tree.get_children():
            tree.delete(iid)
        id_by_iid.clear()
        for index, queued in enumerate(pending, start=1):
            job_id = str(getattr(queued, "job_id", "") or "")
            iid = str(index - 1)
            id_by_iid[iid] = job_id
            tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    index,
                    str(getattr(queued, "label", "Queued download") or "Queued download"),
                    str(getattr(queued, "source_host", "") or "—"),
                ),
            )
            if job_id in selected:
                tree.selection_add(iid)
        last_signature = signature

    def move_selected(edge: str) -> None:
        ids = selected_ids()
        mover = getattr(window, "move_queued_jobs", None)
        if callable(mover) and ids:
            mover(ids, edge)
            refresh(force=True)

    def nudge_selected(direction: int) -> None:
        ids = selected_ids()
        if not ids:
            return
        mover = getattr(window, "move_queued_job", None)
        if not callable(mover):
            return
        iterable = ids if direction < 0 else list(reversed(ids))
        for job_id in iterable:
            mover(job_id, direction)
        refresh(force=True)

    def remove_selected() -> None:
        ids = selected_ids()
        remover = getattr(window, "remove_queued_jobs", None)
        if callable(remover) and ids:
            removed = int(remover(ids))
            if removed:
                window.set_status(window.status_var.get(), f"已从等待队列移除 {removed} 个任务。")
            refresh(force=True)

    def clear_all() -> None:
        clear = getattr(window, "clear_queued_jobs", None)
        if callable(clear):
            removed = int(clear())
            if removed:
                window.set_status(window.status_var.get(), f"已清空 {removed} 个等待任务；当前任务不受影响。")
            refresh(force=True)

    def toggle_pause() -> None:
        toggle = getattr(window, "toggle_queue_paused", None)
        if callable(toggle):
            toggle()
            refresh(force=True)

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    ui.ActionButton(footer, text="清空全部", command=clear_all, kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(footer, text="移除所选", command=remove_selected, kind="danger", compact=True).pack(side="left", padx=(7, 0))
    ui.ActionButton(footer, text="移到底部", command=lambda: move_selected("bottom"), kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(footer, text="移到顶部", command=lambda: move_selected("top"), kind="ghost", compact=True).pack(side="right", padx=(0, 7))
    ui.ActionButton(footer, text="下移", command=lambda: nudge_selected(1), kind="ghost", compact=True).pack(side="right", padx=(0, 7))
    ui.ActionButton(footer, text="上移", command=lambda: nudge_selected(-1), kind="ghost", compact=True).pack(side="right", padx=(0, 7))
    pause_button = ui.ActionButton(footer, text="暂停/继续", command=toggle_pause, kind="secondary", compact=True)
    pause_button.pack(side="right", padx=(0, 7))

    def tick() -> None:
        if not _window_exists(dialog):
            return
        refresh()
        dialog.after(700, tick)

    def close() -> None:
        window._queue_manager_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh(force=True)
    dialog.after(700, tick)


def _show_settings(window, engine_module) -> None:
    existing = getattr(window, "_settings_window", None)
    if _window_exists(existing):
        existing.deiconify()
        existing.lift()
        return

    preferences = load_workspace_preferences(engine_module)
    dialog = tk.Toplevel(window)
    window._settings_window = dialog
    dialog.title("工作台设置 · Galaxy Local Engine")
    dialog.geometry("610x470")
    dialog.minsize(560, 430)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "工作台设置", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "这里只控制新任务的文件组织方式和本机历史，不改变解析、登录、画质选择或 FFmpeg 行为。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=560,
        justify="left",
    ).pack(anchor="w", pady=(4, 12))

    card = tk.Frame(shell, bg=ui.PANEL, padx=16, pady=14, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)

    style_var = tk.StringVar(value=STYLE_LABELS.get(str(preferences["outputNameStyle"]), STYLE_LABELS["title-id"]))
    source_var = tk.BooleanVar(value=bool(preferences["organizeBySource"]))
    history_var = tk.BooleanVar(value=bool(preferences["historyEnabled"]))
    history_limit_var = tk.StringVar(value=str(preferences["historyLimit"]))

    ui._label(card, "文件命名", size=9, weight="bold").pack(anchor="w")
    ttk.Combobox(
        card,
        textvariable=style_var,
        values=tuple(STYLE_KEYS),
        state="readonly",
        width=24,
        style="Galaxy.TCombobox",
    ).pack(anchor="w", pady=(7, 4))
    ui._label(card, "默认仍是“标题 [ID]”，因此升级不会改变现有文件名。", size=7, color=ui.SUBTLE).pack(anchor="w")

    ui._divider(card).pack(fill="x", pady=(13, 11))
    ui._label(card, "目录整理", size=9, weight="bold").pack(anchor="w")
    tk.Checkbutton(
        card,
        text="按来源解析器建立子目录（例如 YouTube、Bilibili）",
        variable=source_var,
        font=("Segoe UI", 8),
        bg=ui.PANEL,
        fg=ui.MUTED,
        activebackground=ui.PANEL,
        activeforeground=ui.TEXT,
        selectcolor=ui.BG,
        bd=0,
        highlightthickness=0,
    ).pack(anchor="w", pady=(6, 0))

    ui._divider(card).pack(fill="x", pady=(13, 11))
    ui._label(card, "下载历史", size=9, weight="bold").pack(anchor="w")
    history_row = tk.Frame(card, bg=ui.PANEL)
    history_row.pack(fill="x", pady=(6, 0))
    tk.Checkbutton(
        history_row,
        text="记录本机任务历史",
        variable=history_var,
        font=("Segoe UI", 8),
        bg=ui.PANEL,
        fg=ui.MUTED,
        activebackground=ui.PANEL,
        activeforeground=ui.TEXT,
        selectcolor=ui.BG,
        bd=0,
        highlightthickness=0,
    ).pack(side="left")
    ui._label(history_row, "最多保留", size=8, color=ui.MUTED).pack(side="left", padx=(22, 6))
    ttk.Combobox(
        history_row,
        textvariable=history_limit_var,
        values=("20", "50", "80", "150", "300"),
        state="readonly",
        width=5,
        style="Galaxy.TCombobox",
    ).pack(side="left")
    ui._label(history_row, "条", size=8, color=ui.MUTED).pack(side="left", padx=(5, 0))
    ui._label(
        card,
        "关闭历史只会停止新增记录，不会自动删除已有历史或下载文件。",
        size=7,
        color=ui.SUBTLE,
    ).pack(anchor="w", pady=(5, 0))

    preview_var = tk.StringVar()

    def update_preview(*_args) -> None:
        style_key = STYLE_KEYS.get(style_var.get(), "title-id")
        filename = {
            "title": "视频标题.mp4",
            "id-title": "abc123 - 视频标题.mp4",
            "title-id": "视频标题 [abc123].mp4",
        }[style_key]
        prefix = "downloads/YouTube/" if source_var.get() else "downloads/"
        preview_var.set(f"示例：{prefix}{filename}")

    ui._label(card, variable=preview_var, size=8, weight="bold", color=ui.CYAN).pack(anchor="w", pady=(14, 0))
    style_var.trace_add("write", update_preview)
    source_var.trace_add("write", update_preview)
    update_preview()

    def save() -> None:
        cleaned = save_workspace_preferences(
            engine_module,
            {
                "outputNameStyle": STYLE_KEYS.get(style_var.get(), "title-id"),
                "organizeBySource": bool(source_var.get()),
                "historyEnabled": bool(history_var.get()),
                "historyLimit": int(history_limit_var.get() or 80),
            },
        )
        window.set_status(
            window.status_var.get(),
            "工作台设置已保存。文件命名与目录整理从下一项新任务开始生效。",
        )
        try:
            extras._sync_history_button(window, engine_module, force=True)
        except Exception:
            pass
        style_var.set(STYLE_LABELS[str(cleaned["outputNameStyle"])])
        source_var.set(bool(cleaned["organizeBySource"]))
        history_var.set(bool(cleaned["historyEnabled"]))
        history_limit_var.set(str(cleaned["historyLimit"]))

    def reset() -> None:
        defaults = DEFAULT_WORKSPACE_PREFERENCES
        style_var.set(STYLE_LABELS[str(defaults["outputNameStyle"])])
        source_var.set(bool(defaults["organizeBySource"]))
        history_var.set(bool(defaults["historyEnabled"]))
        history_limit_var.set(str(defaults["historyLimit"]))

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    ui.ActionButton(footer, text="恢复默认", command=reset, kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(footer, text="保存设置", command=save, kind="primary", compact=True).pack(side="right")

    def close() -> None:
        window._settings_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)


def install_desktop_manager(engine_module):
    """Layer v0.12 history retry, queue manager and settings over v0.11 UI."""
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_manager_installed", False):
        return window_cls

    # Existing v0.11 buttons resolve these module globals when clicked, so
    # replacing them here upgrades the dialog without touching its stable layout.
    extras._show_history = _show_history_manager
    original_job_lines: Callable[[Any], list[tuple[str, str]]] = extras._job_lines

    def job_lines(window) -> list[tuple[str, str]]:
        lines = original_job_lines(window)
        job = getattr(window, "job", None)
        if job is None:
            return lines
        preferences = load_workspace_preferences(engine_module)
        style_label = STYLE_LABELS.get(str(preferences["outputNameStyle"]), str(preferences["outputNameStyle"]))
        lines.extend(
            [
                ("下载 Archive", "开启" if bool(getattr(job, "skip_previously_downloaded", False)) else "关闭"),
                ("文件命名", style_label),
                ("按来源整理", "开启" if bool(preferences["organizeBySource"]) else "关闭"),
                ("输出模板", output_template(engine_module, job)),
            ]
        )
        return lines

    extras._job_lines = job_lines
    original_build = window_cls._build_ui

    def build_ui(window) -> None:
        original_build(window)
        header_actions = window._copy_diag_button.master
        window._settings_button = ui.ActionButton(
            header_actions,
            text="设置",
            command=lambda: _show_settings(window, engine_module),
            kind="ghost",
            compact=True,
        )
        window._settings_button.pack(side="left", padx=(8, 0))

        queue_head = window._queue_clear_button.master
        window._queue_manager_button = ui.ActionButton(
            queue_head,
            text="管理",
            command=lambda: _show_queue_manager(window, engine_module),
            kind="ghost",
            compact=True,
        )
        window._queue_manager_button.pack(side="right", anchor="n", padx=(0, 5))

    window_cls._build_ui = build_ui
    window_cls._galaxy_desktop_manager_installed = True
    return window_cls
