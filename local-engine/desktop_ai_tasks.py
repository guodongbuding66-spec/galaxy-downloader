from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

import desktop_ui as ui
from ai_history import clear_ai_history, delete_ai_run, get_ai_run, list_ai_runs
from ai_provider_registry import provider_public_status
from ai_task_service import AiTaskService, AiTaskServiceError
from ai_workspace import transcript_path
from desktop_hooks import (
    install_before_close_support,
    register_after_build_ui_hook,
    register_before_close_hook,
)
from media_library import list_media_items
from prompt_library import load_prompt_library

_MODE_LABELS = {"Text": "text", "Transcript": "transcript"}
_STATE_LABELS = {
    "queued": "Queued",
    "running": "Running",
    "cancelling": "Cancelling",
    "completed": "Completed",
    "succeeded": "Succeeded",
    "failed": "Failed",
    "cancelled": "Cancelled",
}


def _window_exists(window: tk.Misc | None) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def _service(window, engine_module) -> AiTaskService:
    current = getattr(window, "_desktop_ai_task_service", None)
    if isinstance(current, AiTaskService):
        return current
    current = AiTaskService(engine_module)
    window._desktop_ai_task_service = current
    return current


def _shutdown_service(window) -> None:
    current = getattr(window, "_desktop_ai_task_service", None)
    if not isinstance(current, AiTaskService):
        return
    try:
        snapshot = current.snapshot()
        for row in [*(snapshot.get("waiting") or []), *(snapshot.get("active") or [])]:
            task_id = str(row.get("id") or "") if isinstance(row, dict) else ""
            if task_id:
                try:
                    current.cancel(task_id)
                except Exception:
                    pass
        current.shutdown(cancel_running=True, timeout=1.5)
    finally:
        window._desktop_ai_task_service = None


def _display_state(value: object) -> str:
    state = str(value or "").strip().lower()
    return _STATE_LABELS.get(state, state.title() or "Unknown")


def _history_preview(row: dict[str, Any]) -> str:
    preview = " ".join(str(row.get("resultPreview") or row.get("errorDetail") or "").split())
    return preview[:120] or "—"


def _show_ai_tasks(window, engine_module) -> None:
    existing = getattr(window, "_ai_tasks_window", None)
    if _window_exists(existing):
        existing.deiconify()
        existing.lift()
        return

    task_service = _service(window, engine_module)
    dialog = tk.Toplevel(window)
    window._ai_tasks_window = dialog
    dialog.title("AI Queue & History · Galaxy Local Engine")
    dialog.geometry("1120x800")
    dialog.minsize(960, 680)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "AI Queue & History", size="title", weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "提交文本或现有 Transcript 到已配置 Provider。Queue 在本机进程内执行，结果与错误写入 immutable AI History。",
        size="body_sm",
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=1020,
        justify="left",
    ).pack(anchor="w", pady=(4, 10))

    status_var = tk.StringVar(value="正在加载 AI 工作区…")
    ui._label(shell, variable=status_var, size="body_sm", color=ui.MUTED, bg=ui.BG).pack(anchor="w", pady=(0, 10))

    composer = tk.Frame(
        shell,
        bg=ui.PANEL,
        padx=12,
        pady=12,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    composer.pack(fill="x")
    ui._label(composer, "New AI Task", size="title_sm", weight="bold").grid(
        row=0, column=0, columnspan=8, sticky="w"
    )

    provider_var = tk.StringVar()
    prompt_var = tk.StringVar()
    mode_var = tk.StringVar(value="Text")
    transcript_var = tk.StringVar()
    label_var = tk.StringVar()
    extra_var = tk.StringVar()

    provider_box = ttk.Combobox(composer, textvariable=provider_var, state="readonly", width=24, style="Galaxy.TCombobox")
    prompt_box = ttk.Combobox(composer, textvariable=prompt_var, state="readonly", width=24, style="Galaxy.TCombobox")
    mode_box = ttk.Combobox(
        composer,
        textvariable=mode_var,
        values=tuple(_MODE_LABELS),
        state="readonly",
        width=14,
        style="Galaxy.TCombobox",
    )
    transcript_box = ttk.Combobox(
        composer,
        textvariable=transcript_var,
        state="readonly",
        width=42,
        style="Galaxy.TCombobox",
    )
    label_entry = ui._entry(composer, label_var, 28)
    extra_entry = ui._entry(composer, extra_var, 42)

    for column, (label, widget) in enumerate(
        (
            ("Provider", provider_box),
            ("Prompt", prompt_box),
            ("Mode", mode_box),
            ("Label", label_entry),
        )
    ):
        ui._label(composer, label, size="body_sm", color=ui.MUTED).grid(
            row=1, column=column * 2, sticky="w", pady=(10, 0)
        )
        widget.grid(row=2, column=column * 2, columnspan=2, sticky="ew", padx=(0, 10), pady=(4, 0))
        composer.grid_columnconfigure(column * 2, weight=1)
        composer.grid_columnconfigure(column * 2 + 1, weight=1)

    source_row = tk.Frame(composer, bg=ui.PANEL)
    source_row.grid(row=3, column=0, columnspan=8, sticky="ew", pady=(10, 0))
    ui._label(source_row, "Transcript media", size="body_sm", color=ui.MUTED).pack(side="left")
    transcript_box.pack(side="left", fill="x", expand=True, padx=(8, 0))

    text_row = tk.Frame(composer, bg=ui.PANEL)
    text_row.grid(row=4, column=0, columnspan=8, sticky="ew", pady=(10, 0))
    ui._label(text_row, "Text", size="body_sm", color=ui.MUTED).pack(anchor="w")
    input_text = tk.Text(
        text_row,
        height=4,
        wrap="word",
        bg=ui.PANEL_2,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        relief="flat",
        borderwidth=0,
        highlightthickness=ui.FOCUS_RING_WIDTH,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.FOCUS,
        padx=10,
        pady=8,
        font=(ui.FONT_FAMILY, ui.TYPE["body_sm"]),
        takefocus=True,
    )
    input_text.pack(fill="x", pady=(4, 0))

    option_row = tk.Frame(composer, bg=ui.PANEL)
    option_row.grid(row=5, column=0, columnspan=8, sticky="ew", pady=(10, 0))
    ui._label(option_row, "Extra instruction", size="body_sm", color=ui.MUTED).pack(side="left")
    extra_entry.pack(side="left", fill="x", expand=True, padx=(8, 12))

    submit_button: ui.ActionButton | None = None

    workspace = tk.PanedWindow(
        shell,
        orient="vertical",
        bg=ui.BG,
        sashwidth=5,
        bd=0,
        relief="flat",
    )
    workspace.pack(fill="both", expand=True, pady=(12, 0))

    queue_card = tk.Frame(
        workspace,
        bg=ui.PANEL,
        padx=12,
        pady=12,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    history_card = tk.Frame(
        workspace,
        bg=ui.PANEL,
        padx=12,
        pady=12,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    workspace.add(queue_card, minsize=190)
    workspace.add(history_card, minsize=240)

    queue_head = tk.Frame(queue_card, bg=ui.PANEL)
    queue_head.pack(fill="x")
    queue_count_var = tk.StringVar(value="0 active · 0 waiting")
    ui._label(queue_head, "AI Queue", size="title_sm", weight="bold").pack(side="left")
    ui._label(queue_head, variable=queue_count_var, size="body_sm", color=ui.MUTED).pack(side="left", padx=(10, 0))

    queue_columns = ("state", "label", "provider", "prompt", "position")
    queue_tree = ttk.Treeview(
        queue_card,
        columns=queue_columns,
        show="headings",
        selectmode="browse",
        height=6,
        style="Galaxy.AITasks.Treeview",
    )
    for key, label, width, stretch in (
        ("state", "State", 100, False),
        ("label", "Label", 260, True),
        ("provider", "Provider", 130, False),
        ("prompt", "Prompt", 130, False),
        ("position", "Position", 80, False),
    ):
        queue_tree.heading(key, text=label)
        queue_tree.column(key, width=width, minwidth=70, stretch=stretch)
    queue_scroll = ttk.Scrollbar(queue_card, orient="vertical", command=queue_tree.yview)
    queue_tree.configure(yscrollcommand=queue_scroll.set)
    queue_scroll.pack(side="right", fill="y", pady=(8, 0))
    queue_tree.pack(fill="both", expand=True, pady=(8, 0))

    queue_actions = tk.Frame(queue_head, bg=ui.PANEL)
    queue_actions.pack(side="right")
    cancel_button = ui.ActionButton(
        queue_actions,
        text="Cancel selected",
        command=lambda: cancel_selected(),
        kind="ghost",
        compact=True,
    )
    cancel_button.pack(side="right")
    cancel_button.state(["disabled"])

    history_head = tk.Frame(history_card, bg=ui.PANEL)
    history_head.pack(fill="x")
    history_count_var = tk.StringVar(value="0 runs")
    ui._label(history_head, "AI History", size="title_sm", weight="bold").pack(side="left")
    ui._label(history_head, variable=history_count_var, size="body_sm", color=ui.MUTED).pack(side="left", padx=(10, 0))

    history_columns = ("status", "provider", "model", "prompt", "preview")
    history_tree = ttk.Treeview(
        history_card,
        columns=history_columns,
        show="headings",
        selectmode="browse",
        height=7,
        style="Galaxy.AITasks.Treeview",
    )
    for key, label, width, stretch in (
        ("status", "Status", 95, False),
        ("provider", "Provider", 115, False),
        ("model", "Model", 150, False),
        ("prompt", "Prompt", 120, False),
        ("preview", "Result / Error", 430, True),
    ):
        history_tree.heading(key, text=label)
        history_tree.column(key, width=width, minwidth=70, stretch=stretch)
    history_scroll = ttk.Scrollbar(history_card, orient="vertical", command=history_tree.yview)
    history_tree.configure(yscrollcommand=history_scroll.set)
    history_scroll.pack(side="right", fill="y", pady=(8, 0))
    history_tree.pack(fill="both", expand=True, pady=(8, 0))

    detail = tk.Text(
        history_card,
        height=5,
        wrap="word",
        bg=ui.PANEL_2,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        relief="flat",
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        padx=10,
        pady=8,
        font=(ui.FONT_FAMILY, ui.TYPE["body_sm"]),
        takefocus=True,
        state="disabled",
    )
    detail.pack(fill="x", pady=(8, 0))

    history_actions = tk.Frame(history_head, bg=ui.PANEL)
    history_actions.pack(side="right")
    clear_button = ui.ActionButton(
        history_actions,
        text="Clear History",
        command=lambda: clear_history(),
        kind="ghost",
        compact=True,
    )
    clear_button.pack(side="right")
    delete_button = ui.ActionButton(
        history_actions,
        text="Delete selected",
        command=lambda: delete_selected_history(),
        kind="ghost",
        compact=True,
    )
    delete_button.pack(side="right", padx=(0, 7))
    delete_button.state(["disabled"])

    style = ttk.Style(dialog)
    style.configure(
        "Galaxy.AITasks.Treeview",
        background=ui.PANEL,
        fieldbackground=ui.PANEL,
        foreground=ui.TEXT,
        rowheight=30,
        borderwidth=0,
    )
    style.configure(
        "Galaxy.AITasks.Treeview.Heading",
        background=ui.PANEL_2,
        foreground=ui.MUTED,
        relief="flat",
        font=(ui.FONT_FAMILY, ui.TYPE["body_sm"], "bold"),
    )
    style.map(
        "Galaxy.AITasks.Treeview",
        background=[("selected", ui.PANEL_3)],
        foreground=[("selected", ui.TEXT)],
    )

    provider_ids: dict[str, str] = {}
    prompt_ids: dict[str, str] = {}
    transcript_ids: dict[str, str] = {}
    queue_rows: dict[str, dict[str, Any]] = {}
    history_rows: dict[str, dict[str, Any]] = {}
    refresh_state = {"busy": False, "closed": False, "generation": 0}
    input_state = {"busy": False}

    def set_detail(value: str) -> None:
        detail.configure(state="normal")
        detail.delete("1.0", "end")
        if value:
            detail.insert("1.0", value)
        detail.configure(state="disabled")

    def sync_mode(*_args) -> None:
        transcript_mode = _MODE_LABELS.get(mode_var.get(), "text") == "transcript"
        if transcript_mode:
            source_row.grid()
            text_row.grid_remove()
        else:
            source_row.grid_remove()
            text_row.grid()
        sync_submit()

    def sync_submit() -> None:
        if submit_button is None:
            return
        provider_id = provider_ids.get(provider_var.get(), "")
        prompt_id = prompt_ids.get(prompt_var.get(), "")
        transcript_mode = _MODE_LABELS.get(mode_var.get(), "text") == "transcript"
        source_ok = bool(transcript_ids.get(transcript_var.get(), "")) if transcript_mode else bool(input_text.get("1.0", "end-1c").strip())
        enabled = bool(provider_id and prompt_id and source_ok and not input_state["busy"])
        submit_button.state(["!disabled"] if enabled else ["disabled"])

    def load_inputs() -> None:
        if input_state["busy"]:
            return
        input_state["busy"] = True
        status_var.set("正在刷新 Provider、Prompt 与 Transcript…")

        def worker() -> None:
            try:
                providers = [
                    row for row in provider_public_status(engine_module)
                    if row.get("enabled") and (row.get("hasApiKey") or row.get("allowLocal"))
                ]
                prompts = load_prompt_library(engine_module)
                media_rows = list_media_items(engine_module, limit=500)
                transcripts: list[tuple[str, str]] = []
                for item in media_rows:
                    media_id = str(item.get("id") or "")
                    if not media_id or not item.get("available") or item.get("mediaType") not in {"video", "audio"}:
                        continue
                    try:
                        source = transcript_path(engine_module, media_id)
                        ready = source.is_file() and not source.is_symlink() and source.stat().st_size > 0
                    except OSError:
                        ready = False
                    if ready:
                        title = str(item.get("title") or item.get("fileName") or media_id)
                        transcripts.append((media_id, title))
                error = ""
            except Exception as exc:  # noqa: BLE001
                providers, prompts, transcripts = [], [], []
                error = str(exc)

            def finish() -> None:
                if not _window_exists(dialog):
                    return
                input_state["busy"] = False
                provider_ids.clear()
                provider_labels: list[str] = []
                for row in providers:
                    provider_id = str(row.get("id") or "")
                    label = f"{row.get('name') or provider_id} · {provider_id}"
                    provider_labels.append(label)
                    provider_ids[label] = provider_id
                provider_box.configure(values=provider_labels)
                if provider_labels and provider_var.get() not in provider_ids:
                    provider_var.set(provider_labels[0])

                prompt_ids.clear()
                prompt_labels: list[str] = []
                for prompt in prompts:
                    label = f"{prompt.title} · {prompt.id}"
                    prompt_labels.append(label)
                    prompt_ids[label] = prompt.id
                prompt_box.configure(values=prompt_labels)
                if prompt_labels and prompt_var.get() not in prompt_ids:
                    prompt_var.set(prompt_labels[0])

                transcript_ids.clear()
                transcript_labels: list[str] = []
                for media_id, title in transcripts:
                    label = f"{title} · {media_id[:8]}"
                    transcript_labels.append(label)
                    transcript_ids[label] = media_id
                transcript_box.configure(values=transcript_labels)
                if transcript_labels and transcript_var.get() not in transcript_ids:
                    transcript_var.set(transcript_labels[0])

                if error:
                    status_var.set(f"AI 工作区刷新失败：{error}")
                else:
                    status_var.set(
                        f"{len(provider_labels)} ready Providers · {len(prompt_labels)} Prompts · {len(transcript_labels)} Transcripts"
                    )
                sync_submit()

            dialog.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def submit_task() -> None:
        provider_id = provider_ids.get(provider_var.get(), "")
        prompt_id = prompt_ids.get(prompt_var.get(), "")
        mode = _MODE_LABELS.get(mode_var.get(), "text")
        content = input_text.get("1.0", "end-1c").strip()
        media_id = transcript_ids.get(transcript_var.get(), "")
        extra = extra_var.get().strip()
        label = label_var.get().strip()
        if not provider_id or not prompt_id:
            status_var.set("请选择可用 Provider 与 Prompt。")
            return
        if mode == "text" and not content:
            status_var.set("Text 模式需要输入内容。")
            return
        if mode == "transcript" and not media_id:
            status_var.set("Transcript 模式需要选择已生成 Transcript 的媒体。")
            return

        input_state["busy"] = True
        sync_submit()
        status_var.set("正在创建 AI 任务…")

        def worker() -> None:
            try:
                if mode == "transcript":
                    result = task_service.submit_media_transcript(
                        provider_id=provider_id,
                        media_id=media_id,
                        prompt_id=prompt_id,
                        extra_instruction=extra,
                        label=label,
                    )
                else:
                    result = task_service.submit_text(
                        provider_id=provider_id,
                        content=content,
                        prompt_id=prompt_id,
                        extra_instruction=extra,
                        label=label,
                    )
                error = ""
            except (AiTaskServiceError, OSError, RuntimeError, ValueError) as exc:
                result = {}
                error = str(exc)
            except Exception as exc:  # noqa: BLE001
                result = {}
                error = str(exc)

            def finish() -> None:
                if not _window_exists(dialog):
                    return
                input_state["busy"] = False
                if error:
                    status_var.set(f"任务创建失败：{error}")
                else:
                    task_id = str(result.get("id") or "")
                    status_var.set(f"已加入 Queue · {task_id[:8]}")
                    label_var.set("")
                    extra_var.set("")
                    if mode == "text":
                        input_text.delete("1.0", "end")
                sync_submit()
                refresh_async(force=True)

            dialog.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    submit_button = ui.ActionButton(
        option_row,
        text="Add to Queue",
        command=submit_task,
        kind="primary",
        compact=True,
    )
    submit_button.pack(side="right")
    submit_button.state(["disabled"])
    ui.ActionButton(
        option_row,
        text="Refresh Sources",
        command=load_inputs,
        kind="ghost",
        compact=True,
    ).pack(side="right", padx=(0, 7))

    def queue_selection(_event=None) -> None:
        selection = queue_tree.selection()
        row = queue_rows.get(selection[0]) if selection else None
        state = str(row.get("state") or "") if row else ""
        cancellable = state in {"queued", "running", "cancelling"}
        cancel_button.state(["!disabled"] if cancellable else ["disabled"])

    def cancel_selected() -> None:
        selection = queue_tree.selection()
        task_id = selection[0] if selection else ""
        if not task_id:
            return
        cancel_button.state(["disabled"])
        status_var.set(f"正在取消任务 {task_id[:8]}…")

        def worker() -> None:
            try:
                result = task_service.cancel(task_id)
                error = ""
            except Exception as exc:  # noqa: BLE001
                result = {}
                error = str(exc)

            def finish() -> None:
                if not _window_exists(dialog):
                    return
                if error:
                    status_var.set(f"取消失败：{error}")
                else:
                    status_var.set(f"取消请求：{result.get('code') or result.get('state') or 'done'}")
                refresh_async(force=True)

            dialog.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def history_selection(_event=None) -> None:
        selection = history_tree.selection()
        run_id = selection[0] if selection else ""
        delete_button.state(["!disabled"] if run_id else ["disabled"])
        if not run_id:
            set_detail("")
            return
        generation = refresh_state["generation"] = refresh_state["generation"] + 1

        def worker() -> None:
            try:
                row = get_ai_run(engine_module, run_id)
            except Exception as exc:  # noqa: BLE001
                row = {"errorDetail": str(exc)}
            def finish() -> None:
                if not _window_exists(dialog) or generation != refresh_state["generation"]:
                    return
                if not row:
                    set_detail("History run not found.")
                    return
                lines = [
                    f"Status: {row.get('status') or '—'}",
                    f"Provider: {row.get('providerId') or '—'} · Model: {row.get('model') or '—'}",
                    f"Prompt: {row.get('promptId') or '—'}",
                ]
                if row.get("resultText"):
                    lines.extend(("", str(row.get("resultText"))))
                elif row.get("errorCode") or row.get("errorDetail"):
                    lines.extend(("", f"{row.get('errorCode') or 'ERROR'}: {row.get('errorDetail') or ''}"))
                else:
                    lines.extend(("", "No result text recorded."))
                set_detail("\n".join(lines))
            dialog.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def delete_selected_history() -> None:
        selection = history_tree.selection()
        run_id = selection[0] if selection else ""
        if not run_id:
            return
        if not messagebox.askyesno(
            engine_module.APP_NAME,
            "删除这条 AI History 记录？\n\n不会删除媒体、Transcript 或 Prompt。",
            parent=dialog,
        ):
            return

        def worker() -> None:
            try:
                deleted = delete_ai_run(engine_module, run_id)
                error = ""
            except Exception as exc:  # noqa: BLE001
                deleted = False
                error = str(exc)
            def finish() -> None:
                if not _window_exists(dialog):
                    return
                set_detail("")
                status_var.set("History 已删除。" if deleted else f"删除失败：{error or '记录不存在'}")
                refresh_async(force=True)
            dialog.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def clear_history() -> None:
        if not messagebox.askyesno(
            engine_module.APP_NAME,
            "清空全部 AI History？\n\n不会删除媒体、Transcript、Prompt 或 Provider 配置。",
            parent=dialog,
        ):
            return

        def worker() -> None:
            try:
                count = clear_ai_history(engine_module)
                error = ""
            except Exception as exc:  # noqa: BLE001
                count = 0
                error = str(exc)
            def finish() -> None:
                if not _window_exists(dialog):
                    return
                set_detail("")
                status_var.set(f"已清空 {count} 条 AI History。" if not error else f"清空失败：{error}")
                refresh_async(force=True)
            dialog.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def render_snapshot(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> None:
        current_queue = queue_tree.selection()
        selected_task = current_queue[0] if current_queue else ""
        queue_rows.clear()
        for iid in queue_tree.get_children():
            queue_tree.delete(iid)
        active = list(snapshot.get("active") or [])
        waiting = list(snapshot.get("waiting") or [])
        for row in [*active, *waiting]:
            if not isinstance(row, dict):
                continue
            task_id = str(row.get("id") or "")
            if not task_id:
                continue
            queue_rows[task_id] = row
            queue_tree.insert(
                "",
                "end",
                iid=task_id,
                values=(
                    _display_state(row.get("state")),
                    row.get("label") or task_id[:8],
                    row.get("providerId") or "—",
                    row.get("promptId") or "—",
                    row.get("position") or ("Active" if row in active else "—"),
                ),
            )
        if selected_task and selected_task in queue_rows:
            queue_tree.selection_set(selected_task)
        queue_count_var.set(
            f"{int(snapshot.get('activeCount') or 0)} active · {int(snapshot.get('waitingCount') or 0)} waiting"
        )
        queue_selection()

        current_history = history_tree.selection()
        selected_run = current_history[0] if current_history else ""
        history_rows.clear()
        for iid in history_tree.get_children():
            history_tree.delete(iid)
        for row in history:
            run_id = str(row.get("id") or "")
            if not run_id:
                continue
            history_rows[run_id] = row
            history_tree.insert(
                "",
                "end",
                iid=run_id,
                values=(
                    _display_state(row.get("status")),
                    row.get("providerId") or "—",
                    row.get("model") or "—",
                    row.get("promptId") or "—",
                    _history_preview(row),
                ),
            )
        if selected_run and selected_run in history_rows:
            history_tree.selection_set(selected_run)
        history_count_var.set(f"{len(history_rows)} runs")
        delete_button.state(["!disabled"] if history_tree.selection() else ["disabled"])

    def refresh_async(*, force: bool = False) -> None:
        if refresh_state["closed"]:
            return
        if refresh_state["busy"] and not force:
            return
        refresh_state["busy"] = True

        def worker() -> None:
            try:
                snapshot = task_service.snapshot()
                history = list_ai_runs(engine_module, limit=100)
                error = ""
            except Exception as exc:  # noqa: BLE001
                snapshot, history = {}, []
                error = str(exc)

            def finish() -> None:
                refresh_state["busy"] = False
                if not _window_exists(dialog) or refresh_state["closed"]:
                    return
                if error:
                    status_var.set(f"Queue / History 刷新失败：{error}")
                else:
                    render_snapshot(snapshot, history)
                dialog.after(900, refresh_async)

            dialog.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    provider_var.trace_add("write", lambda *_args: sync_submit())
    prompt_var.trace_add("write", lambda *_args: sync_submit())
    transcript_var.trace_add("write", lambda *_args: sync_submit())
    mode_var.trace_add("write", lambda *_args: sync_mode())
    input_text.bind("<KeyRelease>", lambda _event: sync_submit())
    queue_tree.bind("<<TreeviewSelect>>", queue_selection)
    history_tree.bind("<<TreeviewSelect>>", history_selection)

    def close() -> None:
        refresh_state["closed"] = True
        refresh_state["generation"] += 1
        window._ai_tasks_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    sync_mode()
    load_inputs()
    refresh_async(force=True)


def _add_tasks_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_ai_tasks_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "AI Queue & History", size="body_sm", weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        text,
        "Provider Queue、取消、结果与 immutable History；任务可在窗口关闭后继续。",
        size="caption",
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(
        card,
        text="打开 AI Queue",
        command=lambda: _show_ai_tasks(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_ai_tasks_entry_built = True


def install_desktop_ai_tasks(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_ai_tasks_installed", False):
        return window_cls
    install_before_close_support(window_cls)
    register_after_build_ui_hook(
        window_cls,
        "desktop-ai-tasks",
        lambda window: _add_tasks_entry(window, engine_module),
        order=54,
    )
    register_before_close_hook(
        window_cls,
        "desktop-ai-tasks",
        _shutdown_service,
        order=54,
    )
    window_cls._galaxy_desktop_ai_tasks_installed = True
    return window_cls


def run_desktop_ai_tasks_self_test() -> None:
    assert _MODE_LABELS == {"Text": "text", "Transcript": "transcript"}
    assert _display_state("queued") == "Queued"
    assert _display_state("running") == "Running"
    assert _history_preview({"resultPreview": "  hello   world  "}) == "hello world"
    assert _history_preview({"errorDetail": "AUTH denied"}) == "AUTH denied"
