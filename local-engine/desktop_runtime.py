from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

import desktop_extras as extras
import desktop_manager as manager
import desktop_ui as ui
from desktop_hooks import (
    register_after_build_ui_hook,
    register_desktop_presenter,
    register_job_lines_hook,
    register_queue_tick_hook,
    show_desktop_presenter,
)
from runtime_health import (
    clear_diagnostic_log,
    diagnostic_log_path,
    disk_health,
    load_diagnostic_log,
)
from workspace_policy import (
    DEFAULT_WORKSPACE_PREFERENCES,
    load_workspace_preferences,
    output_template,
    retry_profile_settings,
    save_workspace_preferences,
)

RETRY_LABELS = {
    "standard": "标准（10 次重试）",
    "resilient": "弱网增强（20 次重试）",
    "fast-fail": "快速失败（5 次重试）",
}
RETRY_KEYS = {label: key for key, label in RETRY_LABELS.items()}
RATE_LABELS = {
    0: "不限速",
    1: "1 Mbps",
    2: "2 Mbps",
    5: "5 Mbps",
    10: "10 Mbps",
    20: "20 Mbps",
    50: "50 Mbps",
    100: "100 Mbps",
}
RATE_KEYS = {label: value for value, label in RATE_LABELS.items()}


def _window_exists(window: tk.Misc | None) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def _human_gb(value: object) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "—"
    if size <= 0:
        return "—"
    return f"{size / (1024 ** 3):.1f} GB"


def _checkbutton(master, text: str, variable: tk.BooleanVar) -> tk.Checkbutton:
    return tk.Checkbutton(
        master,
        text=text,
        variable=variable,
        font=("Segoe UI", 8),
        bg=ui.PANEL,
        fg=ui.MUTED,
        activebackground=ui.PANEL,
        activeforeground=ui.TEXT,
        selectcolor=ui.BG,
        bd=0,
        highlightthickness=0,
    )


def _show_diagnostic_log(window, engine_module) -> None:
    existing = getattr(window, "_diagnostic_log_window", None)
    if _window_exists(existing):
        existing.deiconify()
        existing.lift()
        return

    dialog = tk.Toplevel(window)
    window._diagnostic_log_window = dialog
    dialog.title("诊断日志 · Galaxy Local Engine")
    dialog.geometry("920x590")
    dialog.minsize(720, 460)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "诊断日志", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "仅在设置中主动开启后记录。URL 会移除凭据、query 和 fragment，常见 token / cookie 字段会再次脱敏。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=840,
        justify="left",
    ).pack(anchor="w", pady=(4, 10))

    toolbar = tk.Frame(shell, bg=ui.BG)
    toolbar.pack(fill="x", pady=(0, 9))
    query_var = tk.StringVar()
    ui._label(toolbar, "筛选", size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    entry = tk.Entry(
        toolbar,
        textvariable=query_var,
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
    entry.pack(side="left", padx=(7, 10), ipady=5)
    count_var = tk.StringVar(value="0 行")
    ui._label(toolbar, variable=count_var, size=8, color=ui.SUBTLE, bg=ui.BG).pack(side="right")

    card = tk.Frame(shell, bg=ui.PANEL, padx=10, pady=10, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)
    text = tk.Text(
        card,
        wrap="none",
        font=("Cascadia Mono", 8),
        bg=ui.PANEL,
        fg=ui.SUBTLE,
        insertbackground=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        relief="flat",
        bd=0,
        highlightthickness=0,
    )
    yscroll = ttk.Scrollbar(card, orient="vertical", command=text.yview)
    xscroll = ttk.Scrollbar(card, orient="horizontal", command=text.xview)
    text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
    yscroll.pack(side="right", fill="y")
    xscroll.pack(side="bottom", fill="x")
    text.pack(side="left", fill="both", expand=True)

    def refresh(*_args) -> None:
        lines = load_diagnostic_log(engine_module, max_lines=1200)
        query = query_var.get().strip().lower()
        shown = [line for line in lines if not query or query in line.lower()]
        text.configure(state="normal")
        text.delete("1.0", "end")
        if shown:
            text.insert("1.0", "\n".join(shown) + "\n")
        text.configure(state="disabled")
        count_var.set(f"{len(shown)} / {len(lines)} 行")
        text.see("end")

    def copy_all() -> None:
        value = text.get("1.0", "end-1c")
        if not value:
            return
        dialog.clipboard_clear()
        dialog.clipboard_append(value)
        dialog.update_idletasks()

    def clear_all() -> None:
        if not messagebox.askyesno(
            engine_module.APP_NAME,
            "清空本机诊断日志？\n\n不会删除下载文件、下载历史或任何设置。",
            parent=dialog,
        ):
            return
        clear_diagnostic_log(engine_module)
        refresh()

    def open_location() -> None:
        try:
            extras._open_path(diagnostic_log_path(engine_module).parent)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, f"无法打开日志目录：\n{exc}", parent=dialog)

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(10, 0))
    ui.ActionButton(footer, text="清空日志", command=clear_all, kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(footer, text="打开日志目录", command=open_location, kind="ghost", compact=True).pack(side="left", padx=(7, 0))
    ui.ActionButton(footer, text="复制当前视图", command=copy_all, kind="secondary", compact=True).pack(side="right")
    ui.ActionButton(footer, text="刷新", command=refresh, kind="ghost", compact=True).pack(side="right", padx=(0, 7))
    query_var.trace_add("write", lambda *_args: refresh())

    def close() -> None:
        window._diagnostic_log_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh()


def _show_settings(window, engine_module) -> None:
    existing = getattr(window, "_settings_window", None)
    if _window_exists(existing):
        existing.deiconify()
        existing.lift()
        return

    preferences = load_workspace_preferences(engine_module)
    health = disk_health(engine_module)
    dialog = tk.Toplevel(window)
    window._settings_window = dialog
    dialog.title("工作台设置 · Galaxy Local Engine")
    dialog.geometry("760x720")
    dialog.minsize(680, 640)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "工作台设置", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "下载核心默认行为保持 0.12 一致；限速、弱网策略、提醒和诊断日志都由你显式控制。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(4, 12))

    card = tk.Frame(shell, bg=ui.PANEL, padx=16, pady=14, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)

    style_var = tk.StringVar(value=manager.STYLE_LABELS.get(str(preferences["outputNameStyle"]), manager.STYLE_LABELS["title-id"]))
    source_var = tk.BooleanVar(value=bool(preferences["organizeBySource"]))
    history_var = tk.BooleanVar(value=bool(preferences["historyEnabled"]))
    history_limit_var = tk.StringVar(value=str(preferences["historyLimit"]))
    retry_var = tk.StringVar(value=RETRY_LABELS.get(str(preferences["networkRetryProfile"]), RETRY_LABELS["standard"]))
    rate_var = tk.StringVar(value=RATE_LABELS.get(int(preferences["rateLimitMbps"]), "不限速"))
    fragments_var = tk.StringVar(value=str(preferences["concurrentFragments"]))
    completion_var = tk.BooleanVar(value=bool(preferences["completionAlert"]))
    log_var = tk.BooleanVar(value=bool(preferences["diagnosticLogEnabled"]))
    log_limit_var = tk.StringVar(value=str(preferences["diagnosticLogLimitKb"]))
    disk_warning_var = tk.StringVar(value=str(preferences["lowDiskWarningGb"]))

    file_row = tk.Frame(card, bg=ui.PANEL)
    file_row.pack(fill="x")
    left = tk.Frame(file_row, bg=ui.PANEL)
    left.pack(side="left", fill="x", expand=True)
    right = tk.Frame(file_row, bg=ui.PANEL)
    right.pack(side="left", fill="x", expand=True, padx=(28, 0))
    ui._label(left, "文件命名", size=9, weight="bold").pack(anchor="w")
    ttk.Combobox(left, textvariable=style_var, values=tuple(manager.STYLE_KEYS), state="readonly", width=24, style="Galaxy.TCombobox").pack(anchor="w", pady=(6, 0))
    ui._label(right, "下载历史", size=9, weight="bold").pack(anchor="w")
    history_line = tk.Frame(right, bg=ui.PANEL)
    history_line.pack(anchor="w", pady=(5, 0))
    _checkbutton(history_line, "记录历史", history_var).pack(side="left")
    ttk.Combobox(history_line, textvariable=history_limit_var, values=("20", "50", "80", "150", "300"), state="readonly", width=5, style="Galaxy.TCombobox").pack(side="left", padx=(8, 0))
    ui._label(history_line, "条", size=8, color=ui.MUTED).pack(side="left", padx=(4, 0))
    _checkbutton(card, "按来源解析器建立子目录（例如 YouTube、Bilibili）", source_var).pack(anchor="w", pady=(8, 0))

    ui._divider(card).pack(fill="x", pady=(13, 11))
    ui._label(card, "网络与重试", size=9, weight="bold").pack(anchor="w")
    network = tk.Frame(card, bg=ui.PANEL)
    network.pack(fill="x", pady=(7, 0))
    for index in range(3):
        network.grid_columnconfigure(index, weight=1)
    retry_cell = tk.Frame(network, bg=ui.PANEL)
    retry_cell.grid(row=0, column=0, sticky="w")
    ui._label(retry_cell, "重试策略", size=7, color=ui.MUTED).pack(anchor="w")
    ttk.Combobox(retry_cell, textvariable=retry_var, values=tuple(RETRY_KEYS), state="readonly", width=19, style="Galaxy.TCombobox").pack(anchor="w", pady=(4, 0))
    fragments_cell = tk.Frame(network, bg=ui.PANEL)
    fragments_cell.grid(row=0, column=1, sticky="w", padx=(18, 0))
    ui._label(fragments_cell, "并发分片", size=7, color=ui.MUTED).pack(anchor="w")
    ttk.Combobox(fragments_cell, textvariable=fragments_var, values=("1", "2", "4", "8", "16"), state="readonly", width=8, style="Galaxy.TCombobox").pack(anchor="w", pady=(4, 0))
    rate_cell = tk.Frame(network, bg=ui.PANEL)
    rate_cell.grid(row=0, column=2, sticky="w", padx=(18, 0))
    ui._label(rate_cell, "速度上限", size=7, color=ui.MUTED).pack(anchor="w")
    ttk.Combobox(rate_cell, textvariable=rate_var, values=tuple(RATE_KEYS), state="readonly", width=12, style="Galaxy.TCombobox").pack(anchor="w", pady=(4, 0))
    ui._label(card, "默认：标准重试 / 4 分片 / 不限速，和 0.12 完全一致。弱网增强只在你选择后生效。", size=7, color=ui.SUBTLE).pack(anchor="w", pady=(6, 0))

    ui._divider(card).pack(fill="x", pady=(13, 11))
    ui._label(card, "本机运行与诊断", size=9, weight="bold").pack(anchor="w")
    health_line = tk.Frame(card, bg=ui.PANEL)
    health_line.pack(fill="x", pady=(6, 0))
    color = ui.DANGER if bool(health["warning"]) else ui.CYAN
    ui._label(health_line, f"downloads 可用空间 {_human_gb(health['freeBytes'])}", size=8, weight="bold", color=color).pack(side="left")
    ui._label(health_line, f"总容量 {_human_gb(health['totalBytes'])}", size=7, color=ui.SUBTLE).pack(side="left", padx=(12, 0))
    runtime_row = tk.Frame(card, bg=ui.PANEL)
    runtime_row.pack(fill="x", pady=(8, 0))
    _checkbutton(runtime_row, "任务完成/失败时提示音 + 任务栏闪烁", completion_var).pack(side="left")
    ui._label(runtime_row, "低空间提醒", size=8, color=ui.MUTED).pack(side="left", padx=(22, 5))
    ttk.Combobox(runtime_row, textvariable=disk_warning_var, values=("0", "1", "2", "5", "10", "20", "50"), state="readonly", width=5, style="Galaxy.TCombobox").pack(side="left")
    ui._label(runtime_row, "GB", size=8, color=ui.MUTED).pack(side="left", padx=(4, 0))
    log_row = tk.Frame(card, bg=ui.PANEL)
    log_row.pack(fill="x", pady=(7, 0))
    _checkbutton(log_row, "启用本机诊断日志（默认关闭）", log_var).pack(side="left")
    ui._label(log_row, "上限", size=8, color=ui.MUTED).pack(side="left", padx=(22, 5))
    ttk.Combobox(log_row, textvariable=log_limit_var, values=("128", "256", "512", "1024", "2048"), state="readonly", width=7, style="Galaxy.TCombobox").pack(side="left")
    ui._label(log_row, "KB", size=8, color=ui.MUTED).pack(side="left", padx=(4, 0))
    ui._label(card, "诊断日志会自动移除 URL 凭据、query、fragment 和常见 token/cookie 字段；关闭后不再新增日志。", size=7, color=ui.SUBTLE).pack(anchor="w", pady=(5, 0))

    ui._divider(card).pack(fill="x", pady=(13, 10))
    preview_var = tk.StringVar()
    ui._label(card, "输出预览", size=8, weight="bold", color=ui.MUTED).pack(anchor="w")
    ui._label(card, variable=preview_var, size=7, color=ui.SUBTLE, wraplength=675, justify="left").pack(anchor="w", pady=(5, 0))

    def update_preview(*_args) -> None:
        style_key = manager.STYLE_KEYS.get(style_var.get(), "title-id")
        filename = {
            "title": "示例标题.mp4",
            "id-title": "abc123 - 示例标题.mp4",
            "title-id": "示例标题 [abc123].mp4",
        }[style_key]
        path = f"downloads/YouTube/{filename}" if source_var.get() else f"downloads/{filename}"
        retry = RETRY_KEYS.get(retry_var.get(), "standard")
        retry_settings = retry_profile_settings(retry)
        preview_var.set(
            f"{path}   ·   {fragments_var.get()} 分片   ·   {rate_var.get()}   ·   "
            f"重试 {retry_settings['retries']} / 分片 {retry_settings['fragmentRetries']}"
        )

    for variable in (style_var, source_var, retry_var, rate_var, fragments_var):
        variable.trace_add("write", update_preview)
    update_preview()

    def save() -> None:
        cleaned = save_workspace_preferences(
            engine_module,
            {
                "outputNameStyle": manager.STYLE_KEYS.get(style_var.get(), "title-id"),
                "organizeBySource": bool(source_var.get()),
                "historyEnabled": bool(history_var.get()),
                "historyLimit": int(history_limit_var.get() or 80),
                "networkRetryProfile": RETRY_KEYS.get(retry_var.get(), "standard"),
                "rateLimitMbps": int(RATE_KEYS.get(rate_var.get(), 0)),
                "concurrentFragments": int(fragments_var.get() or 4),
                "completionAlert": bool(completion_var.get()),
                "diagnosticLogEnabled": bool(log_var.get()),
                "diagnosticLogLimitKb": int(log_limit_var.get() or 512),
                "lowDiskWarningGb": int(disk_warning_var.get() or 0),
            },
        )
        window.set_status(
            window.status_var.get(),
            "工作台设置已保存。网络、文件组织和提醒选项从下一项新任务开始生效。",
        )
        style_var.set(manager.STYLE_LABELS[str(cleaned["outputNameStyle"])])
        source_var.set(bool(cleaned["organizeBySource"]))
        history_var.set(bool(cleaned["historyEnabled"]))
        history_limit_var.set(str(cleaned["historyLimit"]))
        retry_var.set(RETRY_LABELS[str(cleaned["networkRetryProfile"])])
        rate_var.set(RATE_LABELS[int(cleaned["rateLimitMbps"])])
        fragments_var.set(str(cleaned["concurrentFragments"]))
        completion_var.set(bool(cleaned["completionAlert"]))
        log_var.set(bool(cleaned["diagnosticLogEnabled"]))
        log_limit_var.set(str(cleaned["diagnosticLogLimitKb"]))
        disk_warning_var.set(str(cleaned["lowDiskWarningGb"]))

    def reset() -> None:
        defaults = DEFAULT_WORKSPACE_PREFERENCES
        style_var.set(manager.STYLE_LABELS[str(defaults["outputNameStyle"])])
        source_var.set(bool(defaults["organizeBySource"]))
        history_var.set(bool(defaults["historyEnabled"]))
        history_limit_var.set(str(defaults["historyLimit"]))
        retry_var.set(RETRY_LABELS[str(defaults["networkRetryProfile"])])
        rate_var.set(RATE_LABELS[int(defaults["rateLimitMbps"])])
        fragments_var.set(str(defaults["concurrentFragments"]))
        completion_var.set(bool(defaults["completionAlert"]))
        log_var.set(bool(defaults["diagnosticLogEnabled"]))
        log_limit_var.set(str(defaults["diagnosticLogLimitKb"]))
        disk_warning_var.set(str(defaults["lowDiskWarningGb"]))

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    ui.ActionButton(footer, text="恢复默认", command=reset, kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(footer, text="查看诊断日志", command=lambda: _show_diagnostic_log(window, engine_module), kind="ghost", compact=True).pack(side="left", padx=(7, 0))
    ui.ActionButton(footer, text="保存设置", command=save, kind="primary", compact=True).pack(side="right")

    def close() -> None:
        window._settings_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)


def install_desktop_runtime(engine_module):
    """Layer v0.13 network controls, storage health and diagnostics on v0.12."""
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_runtime_installed", False):
        return window_cls

    register_desktop_presenter(
        window_cls, "settings", "desktop-runtime", lambda window: _show_settings(window, engine_module), order=130
    )

    def job_lines_hook(window, lines: list[tuple[str, str]]) -> list[tuple[str, str]]:
        if getattr(window, "job", None) is None:
            return lines
        preferences = load_workspace_preferences(engine_module)
        retry_key = str(preferences["networkRetryProfile"])
        rate = int(preferences["rateLimitMbps"])
        return [
            *lines,
            ("网络重试", RETRY_LABELS.get(retry_key, retry_key)),
            ("并发分片", str(preferences["concurrentFragments"])),
            ("速度上限", RATE_LABELS.get(rate, f"{rate} Mbps")),
        ]

    register_job_lines_hook(window_cls, "desktop-runtime", job_lines_hook, order=130)

    def sync_storage(window, force: bool = False) -> None:
        now = __import__("time").monotonic()
        if not force and now < float(getattr(window, "_storage_next_refresh", 0.0) or 0.0):
            return
        window._storage_next_refresh = now + 5.0
        health = disk_health(engine_module)
        button = getattr(window, "_storage_button", None)
        if button is None:
            return
        label = f"磁盘 {_human_gb(health['freeBytes'])}"
        if health["warning"]:
            label = f"磁盘不足 {_human_gb(health['freeBytes'])}"
        button.configure(text=label)

    def after_build_ui(window) -> None:
        actions = window._copy_diag_button.master
        window._diagnostic_log_button = ui.ActionButton(
            actions,
            text="日志",
            command=lambda: _show_diagnostic_log(window, engine_module),
            kind="ghost",
            compact=True,
        )
        window._diagnostic_log_button.pack(side="left", padx=(8, 0))
        window._storage_button = ui.ActionButton(
            actions,
            text="磁盘 —",
            command=lambda: show_desktop_presenter(window, "settings"),
            kind="ghost",
            compact=True,
        )
        window._storage_button.pack(side="left", padx=(8, 0))
        window._storage_next_refresh = 0.0
        sync_storage(window, force=True)

    def queue_tick_hook(window) -> None:
        sync_storage(window)

    register_after_build_ui_hook(window_cls, "desktop-runtime", after_build_ui, order=130)
    register_queue_tick_hook(window_cls, "desktop-runtime", queue_tick_hook, order=130)
    window_cls._galaxy_desktop_runtime_installed = True
    return window_cls
