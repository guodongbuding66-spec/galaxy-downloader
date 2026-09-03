from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook, register_desktop_presenter, show_desktop_presenter
from subscription_scheduler import due_subscription_ids, run_auto_check
from subscriptions import (
    ALLOWED_INTERVALS,
    add_subscription,
    check_subscription,
    delete_subscription,
    load_subscriptions,
    update_subscription,
)

BROWSER_LABELS = {
    "不使用浏览器登录": "none",
    "Microsoft Edge": "edge",
    "Google Chrome": "chrome",
    "Firefox": "firefox",
    "Brave": "brave",
}
BROWSER_KEYS = {value: label for label, value in BROWSER_LABELS.items()}
INTERVAL_LABELS = {
    15: "15 分钟",
    30: "30 分钟",
    60: "1 小时",
    180: "3 小时",
    360: "6 小时",
    720: "12 小时",
    1440: "24 小时",
}
INTERVAL_KEYS = {label: value for value, label in INTERVAL_LABELS.items()}


def _window_exists(window: tk.Misc | None) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def _format_time(value: object) -> str:
    text = str(value or "").strip()
    return text.replace("T", " ").replace("Z", " UTC")[:22] if text else "未检查"


def _selected(tree: ttk.Treeview, items: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    selection = tree.selection()
    return items.get(selection[0]) if selection else None


def _edit_subscription_dialog(parent, engine_module, existing: dict[str, Any] | None = None) -> dict[str, Any] | None:
    dialog = tk.Toplevel(parent)
    dialog.title(("编辑" if existing else "新增") + "订阅 · Galaxy Local Engine")
    dialog.geometry("650x560")
    dialog.minsize(600, 520)
    dialog.configure(bg=ui.BG)
    dialog.transient(parent)
    dialog.grab_set()

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "订阅来源", size=15, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "支持 yt-dlp 可识别的频道、播放列表和用户主页。新增时不会联网；首次检查只建立当前内容基线，不会批量下载旧内容。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=590,
        justify="left",
    ).pack(anchor="w", pady=(4, 12))

    card = tk.Frame(shell, bg=ui.PANEL, padx=16, pady=14, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)

    source_var = tk.StringVar(value=str((existing or {}).get("sourceUrl") or ""))
    title_var = tk.StringVar(value=str((existing or {}).get("title") or ""))
    browser_key = str((existing or {}).get("browser") or "none")
    browser_var = tk.StringVar(value=BROWSER_KEYS.get(browser_key, BROWSER_KEYS["none"]))
    enabled_var = tk.BooleanVar(value=bool((existing or {}).get("enabled", True)))
    auto_var = tk.BooleanVar(value=bool((existing or {}).get("autoDownload", False)))
    interval = int((existing or {}).get("intervalMinutes") or 60)
    interval_var = tk.StringVar(value=INTERVAL_LABELS.get(interval, INTERVAL_LABELS[60]))
    video_var = tk.StringVar(value=str((existing or {}).get("videoQuality") or "best"))
    audio_var = tk.StringVar(value=str((existing or {}).get("audioQuality") or "best"))
    include_audio_var = tk.BooleanVar(value=bool((existing or {}).get("includeAudio", True)))

    def label(text: str) -> None:
        ui._label(card, text, size=8, weight="bold", color=ui.MUTED).pack(anchor="w", pady=(9 if card.winfo_children() else 0, 4))

    def entry(variable: tk.StringVar) -> tk.Entry:
        widget = tk.Entry(
            card,
            textvariable=variable,
            font=("Segoe UI", 9),
            bg=ui.BG,
            fg=ui.TEXT,
            insertbackground=ui.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=ui.BORDER,
            highlightcolor=ui.ACCENT,
        )
        widget.pack(fill="x", ipady=6)
        return widget

    label("频道 / 播放列表 URL")
    source_entry = entry(source_var)
    label("显示名称（可留空，首次检查后自动读取）")
    entry(title_var)

    row = tk.Frame(card, bg=ui.PANEL)
    row.pack(fill="x", pady=(12, 0))
    left = tk.Frame(row, bg=ui.PANEL)
    left.pack(side="left", fill="x", expand=True)
    right = tk.Frame(row, bg=ui.PANEL)
    right.pack(side="left", fill="x", expand=True, padx=(18, 0))
    ui._label(left, "浏览器登录态", size=8, weight="bold", color=ui.MUTED).pack(anchor="w")
    ttk.Combobox(left, textvariable=browser_var, values=tuple(BROWSER_LABELS), state="readonly", width=22, style="Galaxy.TCombobox").pack(anchor="w", pady=(4, 0))
    ui._label(right, "自动检查间隔", size=8, weight="bold", color=ui.MUTED).pack(anchor="w")
    ttk.Combobox(right, textvariable=interval_var, values=tuple(INTERVAL_KEYS), state="readonly", width=12, style="Galaxy.TCombobox").pack(anchor="w", pady=(4, 0))

    quality = tk.Frame(card, bg=ui.PANEL)
    quality.pack(fill="x", pady=(12, 0))
    q1 = tk.Frame(quality, bg=ui.PANEL)
    q1.pack(side="left", fill="x", expand=True)
    q2 = tk.Frame(quality, bg=ui.PANEL)
    q2.pack(side="left", fill="x", expand=True, padx=(18, 0))
    ui._label(q1, "视频画质", size=8, weight="bold", color=ui.MUTED).pack(anchor="w")
    ttk.Combobox(q1, textvariable=video_var, values=("best", "2160", "1440", "1080", "720", "480"), width=10, style="Galaxy.TCombobox").pack(anchor="w", pady=(4, 0))
    ui._label(q2, "音频质量", size=8, weight="bold", color=ui.MUTED).pack(anchor="w")
    ttk.Combobox(q2, textvariable=audio_var, values=("best", "320", "256", "192", "160", "128"), width=10, style="Galaxy.TCombobox").pack(anchor="w", pady=(4, 0))

    options = tk.Frame(card, bg=ui.PANEL)
    options.pack(fill="x", pady=(14, 0))
    for text, variable in (
        ("启用这个订阅", enabled_var),
        ("发现新内容后自动加入下载队列", auto_var),
        ("下载视频时包含音频", include_audio_var),
    ):
        tk.Checkbutton(
            options,
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
        ).pack(anchor="w", pady=2)

    ui._label(
        card,
        "自动下载只有在你明确勾选后才会产生后台网络检查；Galaxy 关闭时不会继续轮询。",
        size=7,
        color=ui.SUBTLE,
        wraplength=560,
        justify="left",
    ).pack(anchor="w", pady=(9, 0))

    result: dict[str, Any] | None = None

    def save() -> None:
        nonlocal result
        source = source_var.get().strip()
        if not source:
            messagebox.showwarning(engine_module.APP_NAME, "请输入订阅 URL。", parent=dialog)
            return
        result = {
            "sourceUrl": source,
            "title": title_var.get().strip(),
            "browser": BROWSER_LABELS.get(browser_var.get(), "none"),
            "enabled": bool(enabled_var.get()),
            "autoDownload": bool(auto_var.get()),
            "intervalMinutes": int(INTERVAL_KEYS.get(interval_var.get(), 60)),
            "videoQuality": video_var.get().strip() or "best",
            "audioQuality": audio_var.get().strip() or "best",
            "includeAudio": bool(include_audio_var.get()),
        }
        dialog.destroy()

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    ui.ActionButton(footer, text="取消", command=dialog.destroy, kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(footer, text="保存订阅", command=save, kind="primary", compact=True).pack(side="right", padx=(0, 7))
    source_entry.focus_set()
    parent.wait_window(dialog)
    return result


def _show_subscriptions(window, engine_module) -> None:
    existing = getattr(window, "_subscriptions_window", None)
    if _window_exists(existing):
        existing.deiconify()
        existing.lift()
        return

    dialog = tk.Toplevel(window)
    window._subscriptions_window = dialog
    dialog.title("订阅与自动下载 · Galaxy Local Engine")
    dialog.geometry("1020x620")
    dialog.minsize(820, 480)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "订阅与自动下载", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "频道/播放列表订阅保存在本机。首次检查只建立基线；之后仅处理新条目。自动下载关闭时不会自动联网检查。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=900,
        justify="left",
    ).pack(anchor="w", pady=(4, 12))

    status_var = tk.StringVar(value="")
    ui._label(shell, variable=status_var, size=8, weight="bold", color=ui.CYAN, bg=ui.BG).pack(anchor="w", pady=(0, 8))

    card = tk.Frame(shell, bg=ui.PANEL, padx=12, pady=12, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)
    style = ttk.Style(dialog)
    style.configure("Galaxy.Subscriptions.Treeview", background=ui.PANEL, fieldbackground=ui.PANEL, foreground=ui.TEXT, rowheight=31, borderwidth=0)
    style.configure("Galaxy.Subscriptions.Treeview.Heading", background=ui.PANEL_2, foreground=ui.MUTED, relief="flat", font=("Segoe UI", 8, "bold"))
    style.map("Galaxy.Subscriptions.Treeview", background=[("selected", ui.PANEL_3)], foreground=[("selected", ui.TEXT)])
    columns = ("title", "source", "enabled", "auto", "interval", "last", "result")
    tree = ttk.Treeview(card, columns=columns, show="headings", style="Galaxy.Subscriptions.Treeview", selectmode="browse")
    headings = {
        "title": ("名称", 190), "source": ("来源", 150), "enabled": ("启用", 55),
        "auto": ("自动下载", 72), "interval": ("间隔", 70), "last": ("最近检查", 150), "result": ("状态", 250),
    }
    for key, (label, width) in headings.items():
        tree.heading(key, text=label)
        tree.column(key, width=width, minwidth=50, stretch=key in {"title", "result"})
    scrollbar = ttk.Scrollbar(card, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)

    item_by_iid: dict[str, dict[str, Any]] = {}
    busy = False
    check_button: ui.ActionButton | None = None
    edit_button: ui.ActionButton | None = None
    delete_button: ui.ActionButton | None = None

    def selected() -> dict[str, Any] | None:
        return _selected(tree, item_by_iid)

    def selection_changed(_event=None) -> None:
        item = selected()
        state = ["!disabled"] if item and not busy else ["disabled"]
        for button in (check_button, edit_button, delete_button):
            if button is not None:
                button.state(state)

    def refresh() -> None:
        current = selected()
        selected_id = str(current.get("id") or "") if current else ""
        items = load_subscriptions(engine_module)
        for iid in tree.get_children():
            tree.delete(iid)
        item_by_iid.clear()
        for index, item in enumerate(items):
            iid = str(index)
            item_by_iid[iid] = item
            try:
                host = item.get("sourceUrl", "").split("//", 1)[-1].split("/", 1)[0]
            except Exception:
                host = "—"
            interval = int(item.get("intervalMinutes") or 60)
            error = str(item.get("lastError") or "")
            state_text = error[:80] if error else ("正常" if item.get("lastCheckedAt") else "等待首次检查")
            tree.insert("", "end", iid=iid, values=(
                item.get("title") or "未命名订阅",
                host or "—",
                "是" if item.get("enabled") else "否",
                "是" if item.get("autoDownload") else "否",
                INTERVAL_LABELS.get(interval, f"{interval} 分钟"),
                _format_time(item.get("lastCheckedAt")),
                state_text,
            ))
        if selected_id:
            for iid, item in item_by_iid.items():
                if str(item.get("id") or "") == selected_id:
                    tree.selection_set(iid)
                    break
        if not tree.selection() and tree.get_children():
            tree.selection_set(tree.get_children()[0])
        status_var.set(f"共 {len(items)} 个订阅 · 自动下载 {sum(1 for item in items if item.get('enabled') and item.get('autoDownload'))} 个")
        selection_changed()

    def add_new() -> None:
        values = _edit_subscription_dialog(dialog, engine_module)
        if values is None:
            return
        try:
            add_subscription(engine_module, values)
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning(engine_module.APP_NAME, f"无法保存订阅：\n{exc}", parent=dialog)
            return
        refresh()

    def edit_selected() -> None:
        item = selected()
        if not item:
            return
        values = _edit_subscription_dialog(dialog, engine_module, item)
        if values is None:
            return
        try:
            update_subscription(engine_module, item["id"], values)
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning(engine_module.APP_NAME, f"无法更新订阅：\n{exc}", parent=dialog)
            return
        refresh()

    def delete_selected() -> None:
        item = selected()
        if not item:
            return
        if not messagebox.askyesno(engine_module.APP_NAME, f"删除订阅“{item.get('title') or '未命名订阅'}”？\n\n不会删除已经下载的文件。", parent=dialog):
            return
        delete_subscription(engine_module, item["id"])
        refresh()

    def check_selected() -> None:
        nonlocal busy
        item = selected()
        if not item or busy:
            return
        busy = True
        selection_changed()
        status_var.set("正在检查订阅源…")
        subscription_id = str(item["id"])
        auto_download = bool(item.get("autoDownload"))

        def worker() -> None:
            try:
                if auto_download:
                    result = run_auto_check(engine_module, subscription_id, window.submit_bridge_job)
                    if result.baseline:
                        message = "首次检查完成：已建立当前内容基线，不会批量下载旧内容。"
                    else:
                        message = f"检查完成：发现 {result.discovered} 项新内容，已加入队列 {result.submitted} 项。"
                        if result.failed:
                            message += f" {result.failed} 项因队列/提交失败保留到下次重试。"
                else:
                    result = check_subscription(engine_module, subscription_id, mark_seen=True, max_entries=30)
                    if result.baseline:
                        message = "首次检查完成：已建立当前内容基线。"
                    else:
                        message = f"检查完成：发现 {len(result.new_entries)} 项新内容；自动下载未开启，因此仅标记为已查看。"
                error = ""
            except Exception as exc:  # noqa: BLE001
                message = ""
                error = str(exc)

            def finish() -> None:
                nonlocal busy
                busy = False
                refresh()
                if error:
                    messagebox.showwarning(engine_module.APP_NAME, f"订阅检查失败：\n{error}", parent=dialog)
                else:
                    status_var.set(message)
                selection_changed()

            try:
                window.after(0, finish)
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="GalaxySubscriptionCheck", daemon=True).start()

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    ui.ActionButton(footer, text="新增订阅", command=add_new, kind="primary", compact=True).pack(side="left")
    edit_button = ui.ActionButton(footer, text="编辑", command=edit_selected, kind="secondary", compact=True)
    edit_button.pack(side="left", padx=(7, 0))
    delete_button = ui.ActionButton(footer, text="删除", command=delete_selected, kind="ghost", compact=True)
    delete_button.pack(side="left", padx=(7, 0))
    check_button = ui.ActionButton(footer, text="立即检查", command=check_selected, kind="secondary", compact=True)
    check_button.pack(side="right")
    ui.ActionButton(footer, text="刷新", command=refresh, kind="ghost", compact=True).pack(side="right", padx=(0, 7))

    tree.bind("<<TreeviewSelect>>", selection_changed)
    tree.bind("<Double-1>", lambda _event: edit_selected())

    def close() -> None:
        window._subscriptions_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh()


def _install_scheduler(window, engine_module) -> None:
    if getattr(window, "_subscription_scheduler_installed", False):
        return
    window._subscription_scheduler_installed = True
    window._subscription_scheduler_busy = False

    def tick() -> None:
        if not _window_exists(window):
            return
        if not bool(getattr(window, "_subscription_scheduler_busy", False)):
            due = due_subscription_ids(engine_module, limit=3)
            if due:
                window._subscription_scheduler_busy = True

                def worker() -> None:
                    total_submitted = 0
                    total_failed = 0
                    for subscription_id in due:
                        try:
                            result = run_auto_check(engine_module, subscription_id, window.submit_bridge_job)
                            total_submitted += result.submitted
                            total_failed += result.failed
                        except Exception:
                            total_failed += 1

                    def finish() -> None:
                        window._subscription_scheduler_busy = False
                        if total_submitted:
                            window.set_status(window.status_var.get(), f"订阅自动下载已加入队列 {total_submitted} 项。")
                        elif total_failed:
                            window.set_status(window.status_var.get(), "部分订阅检查失败；将在下一个检查周期重试。")

                    try:
                        window.after(0, finish)
                    except tk.TclError:
                        pass

                threading.Thread(target=worker, name="GalaxySubscriptionScheduler", daemon=True).start()
        try:
            window.after(60_000, tick)
        except tk.TclError:
            pass

    window.after(10_000, tick)


def install_desktop_subscriptions(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_subscriptions_installed", False):
        return window_cls
    register_desktop_presenter(window_cls, "subscriptions", "desktop-subscriptions", lambda window: _show_subscriptions(window, engine_module), order=150)

    def after_build_ui(window) -> None:
        queue_head = window._queue_clear_button.master
        window._subscriptions_button = ui.ActionButton(
            queue_head,
            text="订阅",
            command=lambda: show_desktop_presenter(window, "subscriptions"),
            kind="ghost",
            compact=True,
        )
        window._subscriptions_button.pack(side="right", anchor="n", padx=(0, 5))
        _install_scheduler(window, engine_module)

    register_after_build_ui_hook(window_cls, "desktop-subscriptions", after_build_ui, order=150)
    window_cls._galaxy_desktop_subscriptions_installed = True
    engine_module._galaxy_desktop_subscriptions_installed = True
    return window_cls


def run_desktop_subscriptions_self_test() -> None:
    assert BROWSER_LABELS["Microsoft Edge"] == "edge"
    assert INTERVAL_KEYS["1 小时"] == 60
    assert 60 in ALLOWED_INTERVALS
