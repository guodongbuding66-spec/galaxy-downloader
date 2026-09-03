from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

import desktop_ui as ui
from content_providers import (
    ContentProviderError,
    bilibili_deep_payload,
    gallery_download,
    provider_status,
    social_profile_download,
    telegram_public_post_download,
)
from desktop_hooks import register_after_build_ui_hook
from plugin_host import plugin_host_status

PROVIDER_MODES = (
    ("gallery", "Gallery-dl 通用图集"),
    ("social", "X / Reddit 资料页批量"),
    ("bilibili", "Bilibili 深度分P/合集"),
    ("telegram", "Telegram 公开帖子"),
)


def _show_provider_center(window, engine_module) -> None:
    existing = getattr(window, "_provider_center_window", None)
    if existing is not None:
        try:
            existing.deiconify()
            existing.lift()
            return
        except tk.TclError:
            pass

    dialog = tk.Toplevel(window)
    window._provider_center_window = dialog
    dialog.title("内容提供器 · Galaxy Local Engine")
    dialog.geometry("820x570")
    dialog.minsize(720, 500)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "内容提供器与插件", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "额外站点适配器与 capability-scoped 外部插件。所有下载都必须由你在此显式启动。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(4, 12))

    status_var = tk.StringVar(value="检测中…")
    ui._label(shell, variable=status_var, size=8, color=ui.CYAN, bg=ui.BG).pack(anchor="w", pady=(0, 10))

    card = tk.Frame(shell, bg=ui.PANEL, padx=14, pady=14, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)

    mode_var = tk.StringVar(value="gallery")
    url_var = tk.StringVar()
    max_var = tk.StringVar(value="200")
    parts_var = tk.StringVar()
    browser_var = tk.StringVar(value="none")
    result_var = tk.StringVar(value="就绪")

    top = tk.Frame(card, bg=ui.PANEL)
    top.pack(fill="x")
    ui._label(top, "模式", size=8, weight="bold").pack(side="left")
    ttk.Combobox(
        top,
        textvariable=mode_var,
        values=tuple(value for value, _ in PROVIDER_MODES),
        state="readonly",
        width=14,
        style="Galaxy.TCombobox",
    ).pack(side="left", padx=(8, 18))
    mode_label_var = tk.StringVar(value=PROVIDER_MODES[0][1])
    ui._label(top, variable=mode_label_var, size=8, color=ui.MUTED).pack(side="left")

    def mode_changed(*_args) -> None:
        mapping = dict(PROVIDER_MODES)
        mode_label_var.set(mapping.get(mode_var.get(), mode_var.get()))

    mode_var.trace_add("write", mode_changed)

    url_row = tk.Frame(card, bg=ui.PANEL)
    url_row.pack(fill="x", pady=(14, 0))
    ui._label(url_row, "链接", size=8, weight="bold").pack(side="left")
    url_entry = tk.Entry(
        url_row,
        textvariable=url_var,
        font=("Segoe UI", 9),
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
    )
    url_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))

    options = tk.Frame(card, bg=ui.PANEL)
    options.pack(fill="x", pady=(12, 0))
    ui._label(options, "最大文件数", size=7, color=ui.MUTED).grid(row=0, column=0, sticky="w")
    tk.Entry(options, textvariable=max_var, width=8, bg=ui.BG, fg=ui.TEXT, insertbackground=ui.TEXT, relief="flat").grid(row=0, column=1, padx=(6, 18))
    ui._label(options, "B站分P", size=7, color=ui.MUTED).grid(row=0, column=2, sticky="w")
    tk.Entry(options, textvariable=parts_var, width=18, bg=ui.BG, fg=ui.TEXT, insertbackground=ui.TEXT, relief="flat").grid(row=0, column=3, padx=(6, 18))
    ui._label(options, "浏览器登录", size=7, color=ui.MUTED).grid(row=0, column=4, sticky="w")
    ttk.Combobox(
        options,
        textvariable=browser_var,
        values=("none", "edge", "chrome", "firefox", "brave"),
        state="readonly",
        width=10,
        style="Galaxy.TCombobox",
    ).grid(row=0, column=5, padx=(6, 0))
    ui._label(
        card,
        "Bilibili 模式：分P留空=全部，示例 1,3,5。Gallery/Social 会硬性限制最多 500 个文件。Telegram 仅处理无需登录的公开帖子。",
        size=7,
        color=ui.SUBTLE,
        wraplength=740,
        justify="left",
    ).pack(anchor="w", pady=(10, 0))

    plugin_box = tk.Text(
        card,
        height=9,
        bg=ui.BG,
        fg=ui.MUTED,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        font=("Consolas", 8),
        wrap="word",
    )
    plugin_box.pack(fill="both", expand=True, pady=(14, 0))
    plugin_box.configure(state="disabled")

    ui._label(card, variable=result_var, size=8, color=ui.MUTED).pack(anchor="w", pady=(8, 0))

    def refresh() -> None:
        provider = provider_status(engine_module)
        plugins = plugin_host_status(engine_module)
        gallery = "gallery-dl ✓" if provider["galleryDlReady"] else "gallery-dl 未安装"
        status_var.set(
            f"{gallery} · Bilibili ✓ · Telegram 公共帖 ✓ · 外部插件 {len(plugins['plugins'])} 个"
        )
        lines = ["Plugin protocol v1 · 外部插件只允许声明 parse/download/batch/metadata capability"]
        for item in plugins["plugins"]:
            lines.append(
                f"{item['id']}  v{item['version']}  [{', '.join(item['capabilities'])}]  {item['name']}"
            )
        if len(lines) == 1:
            lines.append("未发现外部插件。放置到 Galaxy data/plugins/<id>/ 并提供 galaxy-plugin.json 后可被发现。")
        plugin_box.configure(state="normal")
        plugin_box.delete("1.0", "end")
        plugin_box.insert("1.0", "\n".join(lines))
        plugin_box.configure(state="disabled")

    def run_provider() -> None:
        url = url_var.get().strip()
        if not url:
            messagebox.showinfo(engine_module.APP_NAME, "请先输入链接。", parent=dialog)
            return
        mode = mode_var.get()
        result_var.set("正在执行…")

        def worker() -> None:
            try:
                if mode == "bilibili":
                    parts: list[int] = []
                    for raw in parts_var.get().split(","):
                        try:
                            value = int(raw.strip())
                        except ValueError:
                            continue
                        if value > 0 and value not in parts:
                            parts.append(value)
                    payload = bilibili_deep_payload(
                        url,
                        browser=browser_var.get(),
                        selected_items=parts,
                        subtitles=True,
                    )
                    response = window.submit_bridge_job(payload)
                    accepted = bool(getattr(response, "accepted", response[0] if isinstance(response, tuple) else False))
                    message = str(getattr(response, "message", response[1] if isinstance(response, tuple) and len(response) > 1 else response))
                    if not accepted:
                        raise ContentProviderError(message)
                    detail = message
                elif mode == "social":
                    try:
                        max_files = int(max_var.get())
                    except ValueError:
                        max_files = 200
                    detail = social_profile_download(engine_module, url, max_files=max_files).message
                elif mode == "telegram":
                    result = telegram_public_post_download(engine_module, url)
                    detail = f"{result.message} · {result.path.name if result.path else ''}"
                else:
                    try:
                        max_files = int(max_var.get())
                    except ValueError:
                        max_files = 200
                    detail = gallery_download(engine_module, url, max_files=max_files).message
            except Exception as exc:  # noqa: BLE001
                detail = f"失败：{exc}"
            dialog.after(0, lambda: result_var.set(detail))
            dialog.after(0, refresh)

        threading.Thread(target=worker, daemon=True).start()

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    ui.ActionButton(footer, text="刷新插件/工具", command=refresh, kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(footer, text="开始", command=run_provider, kind="secondary", compact=True).pack(side="right")

    def close() -> None:
        window._provider_center_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh()


def _add_provider_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_provider_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "扩展内容提供器", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(text, "Gallery-dl · Bilibili · X/Reddit · Telegram · 外部插件", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(
        card,
        text="打开提供器中心",
        command=lambda: _show_provider_center(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_provider_entry_built = True


def install_desktop_providers(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_providers_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-providers",
        lambda window: _add_provider_entry(window, engine_module),
        order=56,
    )
    window_cls._galaxy_desktop_providers_installed = True
    return window_cls


def run_desktop_providers_self_test() -> None:
    assert dict(PROVIDER_MODES)["bilibili"].startswith("Bilibili")
