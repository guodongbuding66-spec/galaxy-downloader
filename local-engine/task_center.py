from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any
from urllib.parse import urlparse

import desktop_extras as extras
import desktop_manager as manager
import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook, register_desktop_presenter, register_history_button_hook
from failure_policy import smart_retry_payload
from job_history import _redacted_source_url, load_history

FILTERS = {
    "全部": "",
    "当前": "active",
    "等待": "queued",
    "暂停": "paused",
    "中断": "interrupted",
    "完成": "completed",
    "失败": "failed",
    "取消": "cancelled",
}
STATE_LABELS = {
    "active": "进行中",
    "queued": "等待",
    "paused": "暂停",
    "interrupted": "中断",
    "completed": "完成",
    "failed": "失败",
    "cancelled": "取消",
}


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


def _safe_host(source_url: object) -> str:
    try:
        return (urlparse(str(source_url or "")).hostname or "").lower()[:160]
    except ValueError:
        return ""


def _pending_snapshot(window) -> list[Any]:
    lock = getattr(window, "_queue_lock", None)
    if lock is None:
        return list(getattr(window, "pending_jobs", []))
    with lock:
        return list(getattr(window, "pending_jobs", []))


def _active_row(window) -> dict[str, Any] | None:
    job = getattr(window, "job", None)
    if job is None or not bool(getattr(window, "running", False)):
        return None
    source = str(getattr(job, "source_url", "") or "")
    display_source, source_host = _redacted_source_url(source)
    detail = ""
    try:
        detail = str(window.detail_var.get() or "")
    except Exception:
        pass
    label = source_host or "当前下载"
    if detail and not detail.startswith("http"):
        label = detail[:180]
    progress = 0.0
    try:
        progress = float(window.percent_var.get() or 0)
    except Exception:
        pass
    return {
        "key": "active",
        "kind": "active",
        "state": "active",
        "sourceHost": source_host,
        "sourceUrl": display_source,
        "videoQuality": str(getattr(job, "video_quality", "best") or "best"),
        "when": f"{max(0.0, min(progress, 100.0)):.1f}%",
        "label": label,
        "detail": detail,
        "advice": "当前任务正在运行。任务中心只查看状态；队列操作不会改变这一项。",
        "job": job,
    }


def _queued_rows(window) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position, queued in enumerate(_pending_snapshot(window), start=1):
        job = getattr(queued, "job", None)
        source = str(getattr(job, "source_url", "") or "") if job is not None else ""
        display_source, _host = _redacted_source_url(source)
        rows.append(
            {
                "key": f"q:{getattr(queued, 'job_id', position)}",
                "kind": "queued",
                "state": "queued",
                "jobId": str(getattr(queued, "job_id", "") or ""),
                "sourceHost": str(getattr(queued, "source_host", "") or _safe_host(source)),
                "sourceUrl": display_source,
                "videoQuality": str(getattr(job, "video_quality", "best") or "best") if job is not None else "—",
                "when": f"#{position}",
                "label": str(getattr(queued, "label", "") or "等待任务")[:180],
                "detail": "等待当前任务完成后自动开始。" if not bool(getattr(window, "queue_paused", False)) else "等待队列已暂停。",
                "advice": "可在任务中心调整优先级、批量移到顶部/底部或移除等待任务。",
                "queued": queued,
            }
        )
    return rows


def _resume_rows(window) -> list[dict[str, Any]]:
    getter = getattr(window, "get_resume_jobs", None)
    if not callable(getter):
        return []
    try:
        records = list(getter())
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        state = str(record.get("state") or "").lower()
        if state not in {"paused", "interrupted"}:
            continue
        try:
            progress = max(0.0, min(100.0, float(record.get("progress") or 0.0)))
        except (TypeError, ValueError):
            progress = 0.0
        resume_mode = str(record.get("resumeMode") or "continue").lower()
        continue_mode = resume_mode == "continue"
        downloaded = str(record.get("downloaded") or "").strip()
        rows.append(
            {
                "key": f"r:{record.get('id')}",
                "kind": "resume",
                "state": state,
                "jobId": str(record.get("id") or ""),
                "sourceHost": str(record.get("sourceHost") or ""),
                "sourceUrl": "",
                "videoQuality": str(record.get("videoQuality") or "—"),
                "when": f"{progress:.1f}%",
                "label": str(record.get("label") or record.get("sourceHost") or "未完成任务")[:220],
                "detail": f"已保留本机进度 {progress:.1f}%" + (f" · {downloaded}" if downloaded else ""),
                "advice": (
                    "继续时会复用 yt-dlp 的 .part/fragment，从源站允许的最近检查点续传。"
                    if continue_mode
                    else "该来源不能可靠字节续传；继续操作会重新开始该任务，不会伪装成精确断点。"
                ),
                "failureLabel": "断点续传" if continue_mode else "重新开始",
                "resume": record,
            }
        )
    return rows


def _history_rows(engine_module) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in load_history(engine_module):
        state = str(item.get("state") or "")
        rows.append(
            {
                "key": f"h:{item.get('id')}",
                "kind": "history",
                "state": state,
                "sourceHost": str(item.get("sourceHost") or ""),
                "sourceUrl": str(item.get("sourceUrl") or ""),
                "videoQuality": str(item.get("videoQuality") or "—"),
                "when": _format_time(item.get("finishedAt")),
                "label": str(item.get("fileName") or item.get("label") or "历史任务")[:220],
                "detail": str(item.get("detail") or ""),
                "advice": str(item.get("failureAdvice") or ""),
                "failureLabel": str(item.get("failureLabel") or ""),
                "item": item,
            }
        )
    return rows


def _task_rows(window, engine_module) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    active = _active_row(window)
    if active is not None:
        rows.append(active)
    rows.extend(_queued_rows(window))
    rows.extend(_resume_rows(window))
    rows.extend(_history_rows(engine_module))
    return rows


def _row_search_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in (
            "state",
            "sourceHost",
            "sourceUrl",
            "videoQuality",
            "label",
            "detail",
            "advice",
            "failureLabel",
        )
    ).lower()


def _matches_filter(row: dict[str, Any], filter_key: str, query: str) -> bool:
    if filter_key and str(row.get("state") or "") != filter_key:
        return False
    return not query or query in _row_search_text(row)


def _submit_retry_payload(window, engine_module, payload: dict[str, Any], parent: tk.Misc, success_text: str) -> None:
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
                window.set_status(window.status_var.get(), success_text)
            else:
                messagebox.showwarning(
                    engine_module.APP_NAME,
                    f"无法提交任务。\n\n{message or code or '未知错误'}",
                    parent=parent,
                )

        try:
            window.after(0, finish)
        except tk.TclError:
            pass

    threading.Thread(target=worker, daemon=True).start()


def _standard_retry(window, engine_module, item: dict[str, Any], parent: tk.Misc) -> None:
    manager._retry_history_item(window, engine_module, item, parent)


def _smart_retry(window, engine_module, item: dict[str, Any], parent: tk.Misc) -> None:
    payload = smart_retry_payload(item)
    if payload is None:
        advice = str(item.get("failureAdvice") or "当前失败类型不适合自动改变参数后重试。")
        messagebox.showinfo(
            engine_module.APP_NAME,
            f"这个失败需要先处理原因，再重新下载。\n\n{advice}",
            parent=parent,
        )
        return
    _submit_retry_payload(
        window,
        engine_module,
        payload,
        parent,
        "智能重试已提交；恢复参数只作用于这一项任务，不会修改工作台全局设置。",
    )


def _show_task_center(window, engine_module, initial_filter: str | None = None) -> None:
    existing = getattr(window, "_task_center_window", None)
    if _window_exists(existing):
        if initial_filter and hasattr(existing, "_task_center_filter_var"):
            existing._task_center_filter_var.set(initial_filter)
        existing.deiconify()
        existing.lift()
        try:
            existing.focus_force()
        except tk.TclError:
            pass
        return

    dialog = tk.Toplevel(window)
    window._task_center_window = dialog
    dialog.title("任务中心 · Galaxy Local Engine")
    dialog.geometry("1120x720")
    dialog.minsize(900, 580)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)

    heading = tk.Frame(shell, bg=ui.BG)
    heading.pack(fill="x")
    heading_left = tk.Frame(heading, bg=ui.BG)
    heading_left.pack(side="left", fill="x", expand=True)
    ui._label(heading_left, "任务中心", size=17, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        heading_left,
        "当前下载、等待队列、可恢复任务和本机历史放在一个工作区；暂停/异常退出后不会自动偷偷重新下载。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(4, 0))
    summary_var = tk.StringVar(value="当前 0 · 等待 0 · 可恢复 0 · 完成 0 · 失败 0")
    ui._label(heading, variable=summary_var, size=9, weight="bold", color=ui.CYAN, bg=ui.BG).pack(side="right", anchor="n", pady=(4, 0))

    filters = tk.Frame(shell, bg=ui.BG)
    filters.pack(fill="x", pady=(14, 10))
    query_var = tk.StringVar()
    filter_var = tk.StringVar(value=initial_filter if initial_filter in FILTERS else "全部")
    dialog._task_center_filter_var = filter_var
    ui._label(filters, "搜索", size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    search = tk.Entry(
        filters,
        textvariable=query_var,
        width=35,
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
    ui._label(filters, "范围", size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    ttk.Combobox(
        filters,
        textvariable=filter_var,
        values=tuple(FILTERS),
        width=8,
        state="readonly",
        style="Galaxy.TCombobox",
    ).pack(side="left", padx=(7, 0))
    count_var = tk.StringVar(value="0 项")
    ui._label(filters, variable=count_var, size=8, color=ui.SUBTLE, bg=ui.BG).pack(side="right")

    style = ttk.Style(dialog)
    style.configure(
        "Galaxy.TaskCenter.Treeview",
        background=ui.PANEL,
        fieldbackground=ui.PANEL,
        foreground=ui.TEXT,
        rowheight=30,
        borderwidth=0,
    )
    style.configure(
        "Galaxy.TaskCenter.Treeview.Heading",
        background=ui.PANEL_2,
        foreground=ui.MUTED,
        relief="flat",
        font=("Segoe UI", 8, "bold"),
    )
    style.map(
        "Galaxy.TaskCenter.Treeview",
        background=[("selected", ui.PANEL_3)],
        foreground=[("selected", ui.TEXT)],
    )

    card = tk.Frame(shell, bg=ui.PANEL, padx=10, pady=10, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)
    columns = ("state", "source", "quality", "when", "task", "recovery")
    tree = ttk.Treeview(
        card,
        columns=columns,
        show="headings",
        selectmode="extended",
        style="Galaxy.TaskCenter.Treeview",
    )
    headings = {
        "state": ("状态", 72),
        "source": ("来源", 135),
        "quality": ("画质", 72),
        "when": ("进度 / 时间", 145),
        "task": ("任务 / 文件", 430),
        "recovery": ("恢复判断", 150),
    }
    for key, (title, width) in headings.items():
        tree.heading(key, text=title)
        tree.column(key, width=width, minwidth=60, stretch=key == "task")
    scrollbar = ttk.Scrollbar(card, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)

    detail_card = tk.Frame(shell, bg=ui.PANEL, padx=14, pady=10, highlightthickness=1, highlightbackground=ui.BORDER)
    detail_card.pack(fill="x", pady=(10, 0))
    detail_var = tk.StringVar(value="选择一个任务查看详情。")
    advice_var = tk.StringVar(value="")
    ui._label(detail_card, variable=detail_var, size=8, color=ui.TEXT, wraplength=1040, justify="left").pack(anchor="w")
    ui._label(detail_card, variable=advice_var, size=8, color=ui.CYAN, wraplength=1040, justify="left").pack(anchor="w", pady=(4, 0))

    row_by_iid: dict[str, dict[str, Any]] = {}
    last_signature: tuple[str, ...] = ()

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(10, 0))

    active_pause_button: ui.ActionButton | None = None
    resume_button: ui.ActionButton | None = None
    discard_resume_button: ui.ActionButton | None = None
    pause_button: ui.ActionButton | None = None
    top_button: ui.ActionButton | None = None
    up_button: ui.ActionButton | None = None
    down_button: ui.ActionButton | None = None
    remove_button: ui.ActionButton | None = None
    details_button: ui.ActionButton | None = None
    copy_button: ui.ActionButton | None = None
    open_button: ui.ActionButton | None = None
    reveal_button: ui.ActionButton | None = None
    retry_button: ui.ActionButton | None = None
    smart_button: ui.ActionButton | None = None

    def selected_rows() -> list[dict[str, Any]]:
        return [row_by_iid[iid] for iid in tree.selection() if iid in row_by_iid]

    def selected_history() -> dict[str, Any] | None:
        rows = selected_rows()
        if len(rows) != 1 or rows[0].get("kind") != "history":
            return None
        return rows[0].get("item")

    def selected_resume() -> dict[str, Any] | None:
        rows = selected_rows()
        if len(rows) != 1 or rows[0].get("kind") != "resume":
            return None
        return rows[0]

    def selected_queue_ids() -> list[str]:
        rows = selected_rows()
        if not rows or any(row.get("kind") != "queued" for row in rows):
            return []
        return [str(row.get("jobId") or "") for row in rows if row.get("jobId")]

    def update_actions(_event=None) -> None:
        rows = selected_rows()
        one = rows[0] if len(rows) == 1 else None
        item = selected_history()
        resume = selected_resume()
        queue_ids = selected_queue_ids()

        for button in (top_button, remove_button):
            if button is not None:
                button.state(["!disabled"] if queue_ids else ["disabled"])
        for button in (up_button, down_button):
            if button is not None:
                button.state(["!disabled"] if len(queue_ids) == 1 else ["disabled"])
        if active_pause_button is not None:
            pause_event = getattr(window, "pause_event", None)
            can_pause = bool(one and one.get("kind") == "active" and getattr(window, "running", False))
            if pause_event is not None and pause_event.is_set():
                can_pause = False
            active_pause_button.state(["!disabled"] if can_pause else ["disabled"])
        if resume_button is not None:
            resume_button.state(["!disabled"] if resume and not bool(getattr(window, "running", False)) else ["disabled"])
        if discard_resume_button is not None:
            discard_resume_button.state(["!disabled"] if resume and not bool(getattr(window, "running", False)) else ["disabled"])
        if details_button is not None:
            details_button.state(["!disabled"] if one and one.get("kind") == "active" else ["disabled"])
        if copy_button is not None:
            copy_button.state(["!disabled"] if one and one.get("sourceUrl") else ["disabled"])
        if open_button is not None or reveal_button is not None:
            path = Path(str(item.get("filePath"))) if item and item.get("filePath") else None
            enabled = bool(path and path.exists())
            if open_button is not None:
                open_button.state(["!disabled"] if enabled else ["disabled"])
            if reveal_button is not None:
                reveal_button.state(["!disabled"] if enabled else ["disabled"])
        if retry_button is not None:
            retry_button.state(["!disabled"] if item and item.get("retryable") else ["disabled"])
        if smart_button is not None:
            smart_button.state(["!disabled"] if item and item.get("smartRetryable") else ["disabled"])

        if one is None:
            detail_var.set(f"已选择 {len(rows)} 项。多选时只开放批量队列操作。" if rows else "选择一个任务查看详情。")
            advice_var.set("")
            return
        detail = str(one.get("detail") or "").strip()
        source = str(one.get("sourceUrl") or one.get("sourceHost") or "—")
        detail_var.set(f"{STATE_LABELS.get(str(one.get('state')), str(one.get('state')))} · {source}" + (f" · {detail}" if detail else ""))
        advice = str(one.get("advice") or "").strip()
        failure = str(one.get("failureLabel") or "").strip()
        advice_var.set((f"{failure}：" if failure else "") + advice if advice else "")

    def refresh(force: bool = False) -> None:
        nonlocal last_signature
        rows = _task_rows(window, engine_module)
        history = [row for row in rows if row.get("kind") == "history"]
        active_count = sum(1 for row in rows if row.get("state") == "active")
        queued_count = sum(1 for row in rows if row.get("state") == "queued")
        recoverable_count = sum(1 for row in rows if row.get("kind") == "resume")
        completed_count = sum(1 for row in history if row.get("state") == "completed")
        failed_count = sum(1 for row in history if row.get("state") == "failed")
        summary_var.set(f"当前 {active_count} · 等待 {queued_count} · 可恢复 {recoverable_count} · 完成 {completed_count} · 失败 {failed_count}")
        if pause_button is not None:
            pause_button.configure(text="继续队列" if bool(getattr(window, "queue_paused", False)) else "完成后暂停")

        query = query_var.get().strip().lower()
        filter_key = FILTERS.get(filter_var.get(), "")
        visible = [row for row in rows if _matches_filter(row, filter_key, query)]
        signature = tuple(
            f"{row.get('key')}:{row.get('state')}:{row.get('when')}:{row.get('label')}:{row.get('failureLabel')}"
            for row in visible
        )
        if not force and signature == last_signature:
            count_var.set(f"{len(visible)} / {len(rows)} 项")
            update_actions()
            return

        selected_keys = {row_by_iid[iid].get("key") for iid in tree.selection() if iid in row_by_iid}
        for iid in tree.get_children():
            tree.delete(iid)
        row_by_iid.clear()
        for index, row in enumerate(visible):
            iid = str(index)
            row_by_iid[iid] = row
            tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    STATE_LABELS.get(str(row.get("state")), str(row.get("state") or "—")),
                    row.get("sourceHost") or "—",
                    row.get("videoQuality") or "—",
                    row.get("when") or "—",
                    row.get("label") or "—",
                    row.get("failureLabel") or "—",
                ),
            )
            if row.get("key") in selected_keys:
                tree.selection_add(iid)
        count_var.set(f"{len(visible)} / {len(rows)} 项")
        last_signature = signature
        update_actions()
        try:
            extras._sync_history_button(window, engine_module, force=True)
        except Exception:
            pass

    def toggle_pause() -> None:
        toggle = getattr(window, "toggle_queue_paused", None)
        if callable(toggle):
            toggle()
            refresh(force=True)

    def pause_active_selected() -> None:
        rows = selected_rows()
        pause = getattr(window, "pause_active_job", None)
        if len(rows) == 1 and rows[0].get("kind") == "active" and callable(pause):
            if pause():
                window.set_status("Pausing", "正在保存可恢复状态并停止到安全检查点…")
            refresh(force=True)

    def resume_selected() -> None:
        row = selected_resume()
        resume = getattr(window, "resume_job", None)
        if row and callable(resume):
            job_id = str(row.get("jobId") or "")
            if job_id and resume(job_id):
                refresh(force=True)
            elif job_id:
                messagebox.showwarning(engine_module.APP_NAME, "当前无法继续这个任务；请确认没有其他下载正在运行。", parent=dialog)

    def discard_resume_selected() -> None:
        row = selected_resume()
        discard = getattr(window, "discard_resume_job", None)
        if not row or not callable(discard):
            return
        job_id = str(row.get("jobId") or "")
        if not job_id:
            return
        if not messagebox.askyesno(
            engine_module.APP_NAME,
            "放弃这个可恢复任务？\n\n下载临时文件不会在这里主动删除，但任务中心将不再提供继续入口。",
            parent=dialog,
        ):
            return
        if discard(job_id):
            refresh(force=True)

    def move_queue(edge: str) -> None:
        ids = selected_queue_ids()
        mover = getattr(window, "move_queued_jobs", None)
        if callable(mover) and ids:
            mover(ids, edge)
            refresh(force=True)

    def nudge_queue(direction: int) -> None:
        ids = selected_queue_ids()
        mover = getattr(window, "move_queued_job", None)
        if callable(mover) and len(ids) == 1:
            mover(ids[0], direction)
            refresh(force=True)

    def remove_queue() -> None:
        ids = selected_queue_ids()
        remover = getattr(window, "remove_queued_jobs", None)
        if callable(remover) and ids:
            removed = int(remover(ids))
            if removed:
                window.set_status(window.status_var.get(), f"已从等待队列移除 {removed} 个任务。")
            refresh(force=True)

    def show_details() -> None:
        rows = selected_rows()
        if len(rows) == 1 and rows[0].get("kind") == "active":
            extras._show_job_details(window, engine_module)

    def copy_source() -> None:
        rows = selected_rows()
        if len(rows) != 1:
            return
        value = str(rows[0].get("sourceUrl") or "")
        if not value:
            return
        dialog.clipboard_clear()
        dialog.clipboard_append(value)
        dialog.update_idletasks()

    def open_file(select_file: bool = False) -> None:
        item = selected_history()
        path = Path(str(item.get("filePath"))) if item and item.get("filePath") else None
        if path is None or not path.exists():
            return
        try:
            extras._open_path(path, select_file=select_file)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, f"无法打开文件：\n{exc}", parent=dialog)

    def retry_selected(smart: bool = False) -> None:
        item = selected_history()
        if not item:
            return
        if smart:
            _smart_retry(window, engine_module, item, dialog)
        else:
            _standard_retry(window, engine_module, item, dialog)

    active_pause_button = ui.ActionButton(footer, text="暂停当前", command=pause_active_selected, kind="secondary", compact=True)
    active_pause_button.pack(side="left")
    pause_button = ui.ActionButton(footer, text="完成后暂停", command=toggle_pause, kind="ghost", compact=True)
    pause_button.pack(side="left", padx=(6, 0))
    top_button = ui.ActionButton(footer, text="移到顶部", command=lambda: move_queue("top"), kind="ghost", compact=True)
    top_button.pack(side="left", padx=(6, 0))
    up_button = ui.ActionButton(footer, text="上移", command=lambda: nudge_queue(-1), kind="ghost", compact=True)
    up_button.pack(side="left", padx=(6, 0))
    down_button = ui.ActionButton(footer, text="下移", command=lambda: nudge_queue(1), kind="ghost", compact=True)
    down_button.pack(side="left", padx=(6, 0))
    remove_button = ui.ActionButton(footer, text="移除等待", command=remove_queue, kind="danger", compact=True)
    remove_button.pack(side="left", padx=(6, 0))

    resume_button = ui.ActionButton(footer, text="继续任务", command=resume_selected, kind="primary", compact=True)
    resume_button.pack(side="right")
    discard_resume_button = ui.ActionButton(footer, text="放弃恢复", command=discard_resume_selected, kind="danger", compact=True)
    discard_resume_button.pack(side="right", padx=(0, 6))
    smart_button = ui.ActionButton(footer, text="智能重试", command=lambda: retry_selected(True), kind="primary", compact=True)
    smart_button.pack(side="right")
    retry_button = ui.ActionButton(footer, text="原参数重试", command=lambda: retry_selected(False), kind="secondary", compact=True)
    retry_button.pack(side="right", padx=(0, 6))
    open_button = ui.ActionButton(footer, text="打开文件", command=lambda: open_file(False), kind="ghost", compact=True)
    open_button.pack(side="right", padx=(0, 6))
    reveal_button = ui.ActionButton(footer, text="定位文件", command=lambda: open_file(True), kind="ghost", compact=True)
    reveal_button.pack(side="right", padx=(0, 6))
    copy_button = ui.ActionButton(footer, text="复制来源", command=copy_source, kind="ghost", compact=True)
    copy_button.pack(side="right", padx=(0, 6))
    details_button = ui.ActionButton(footer, text="任务详情", command=show_details, kind="ghost", compact=True)
    details_button.pack(side="right", padx=(0, 6))

    for button in (active_pause_button, resume_button, discard_resume_button, top_button, up_button, down_button, remove_button, details_button, copy_button, open_button, reveal_button, retry_button, smart_button):
        button.state(["disabled"])

    tree.bind("<<TreeviewSelect>>", update_actions)
    def activate_selected(_event=None) -> None:
        rows = selected_rows()
        if len(rows) != 1:
            return
        if rows[0].get("kind") == "resume":
            resume_selected()
        elif rows[0].get("kind") == "history":
            open_file(False)
        elif rows[0].get("kind") == "active":
            show_details()

    tree.bind("<Double-1>", activate_selected)
    query_var.trace_add("write", lambda *_args: refresh(force=True))
    filter_var.trace_add("write", lambda *_args: refresh(force=True))

    def tick() -> None:
        if not _window_exists(dialog):
            return
        refresh()
        dialog.after(750, tick)

    def close() -> None:
        window._task_center_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh(force=True)
    dialog.after(750, tick)


def install_task_center(engine_module):
    """Replace split history/queue dialogs with one IDM-style local task center."""
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_task_center_installed", False):
        return window_cls

    register_desktop_presenter(
        window_cls, "history", "task-center", lambda window: _show_task_center(window, engine_module), order=150
    )
    register_desktop_presenter(
        window_cls, "queue", "task-center", lambda window: _show_task_center(window, engine_module, "等待"), order=150
    )

    def history_button_hook(window, _module, history_count: int, _text: str) -> str:
        try:
            total = history_count + len(_pending_snapshot(window)) + len(_resume_rows(window)) + (1 if bool(getattr(window, "running", False)) else 0)
        except Exception:
            total = history_count
        return f"任务 {total}"

    register_history_button_hook(window_cls, "task-center", history_button_hook, order=150)

    def after_build_ui(window) -> None:
        queue_button = getattr(window, "_queue_manager_button", None)
        if queue_button is not None:
            queue_button.configure(text="队列")
        extras._sync_history_button(window, engine_module, force=True)

    register_after_build_ui_hook(window_cls, "task-center", after_build_ui, order=150)
    window_cls._galaxy_task_center_installed = True
    engine_module._galaxy_task_center_installed = True
    return window_cls


def run_task_center_self_test() -> None:
    row = {
        "state": "failed",
        "sourceHost": "example.com",
        "label": "Demo task",
        "failureLabel": "网络连接异常",
        "detail": "HTTP Error 503",
    }
    assert _matches_filter(row, "failed", "") is True
    assert _matches_filter(row, "completed", "") is False
    assert _matches_filter(row, "failed", "network") is False
    assert _matches_filter(row, "failed", "503") is True
    assert "example.com" in _row_search_text(row)
    resume = {"state": "paused", "sourceHost": "video.example", "failureLabel": "断点续传"}
    assert _matches_filter(resume, "paused", "") is True
    assert "断点续传" in _row_search_text(resume)
