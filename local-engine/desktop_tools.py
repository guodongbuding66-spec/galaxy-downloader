from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook, register_desktop_presenter, show_desktop_presenter
from tool_manager import reset_managed_ytdlp, tool_inventory, update_managed_ytdlp


def _window_exists(window: tk.Misc | None) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def _source_label(value: object) -> str:
    return {
        "managed": "托管版本",
        "bundled": "随包版本",
        "system": "系统版本",
        "unavailable": "不可用",
    }.get(str(value or ""), str(value or "—"))


def _version_label(value: object) -> str:
    text = str(value or "").strip()
    return text if text else "—"


def _show_tools(window, engine_module) -> None:
    existing = getattr(window, "_tools_window", None)
    if _window_exists(existing):
        existing.deiconify()
        existing.lift()
        return

    dialog = tk.Toplevel(window)
    window._tools_window = dialog
    dialog.title("工具管理 · Galaxy Local Engine")
    dialog.geometry("680x470")
    dialog.minsize(620, 430)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "工具管理", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "Galaxy 默认继续使用发行包内已经验证的工具。只有你主动点击更新时，才会创建并更新用户目录里的 yt-dlp 托管副本；启动和普通下载不会联网检查工具更新。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=620,
        justify="left",
    ).pack(anchor="w", pady=(4, 12))

    card = tk.Frame(shell, bg=ui.PANEL, padx=16, pady=14, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)

    ytdlp_source_var = tk.StringVar(value="—")
    ytdlp_version_var = tk.StringVar(value="—")
    ffmpeg_source_var = tk.StringVar(value="—")
    ffmpeg_version_var = tk.StringVar(value="—")
    operation_var = tk.StringVar(value="")

    def tool_row(title: str, source_var: tk.StringVar, version_var: tk.StringVar) -> None:
        row = tk.Frame(card, bg=ui.PANEL)
        row.pack(fill="x", pady=(2, 10))
        left = tk.Frame(row, bg=ui.PANEL)
        left.pack(side="left", fill="x", expand=True)
        ui._label(left, title, size=10, weight="bold").pack(anchor="w")
        ui._label(left, variable=version_var, size=8, color=ui.SUBTLE, wraplength=430, justify="left").pack(anchor="w", pady=(3, 0))
        badge = tk.Label(
            row,
            textvariable=source_var,
            font=("Segoe UI", 8, "bold"),
            bg=ui.PANEL_2,
            fg=ui.MUTED,
            padx=9,
            pady=5,
            bd=0,
        )
        badge.pack(side="right", padx=(12, 0))

    tool_row("yt-dlp", ytdlp_source_var, ytdlp_version_var)
    ui._divider(card).pack(fill="x", pady=(2, 10))
    tool_row("FFmpeg", ffmpeg_source_var, ffmpeg_version_var)

    ui._divider(card).pack(fill="x", pady=(2, 10))
    ui._label(
        card,
        "更新 yt-dlp 会先把随包版本复制到 runtime tools，再调用 yt-dlp 官方自更新机制。随包文件本身始终不修改，因此失败或回退时仍有可用基线。FFmpeg 当前只做来源/版本检测，自动托管将在后续阶段接入。",
        size=7,
        color=ui.SUBTLE,
        wraplength=610,
        justify="left",
    ).pack(anchor="w")
    ui._label(card, variable=operation_var, size=8, weight="bold", color=ui.CYAN, wraplength=610, justify="left").pack(anchor="w", pady=(10, 0))

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    update_button = ui.ActionButton(footer, text="更新 yt-dlp", kind="primary", compact=True)
    reset_button = ui.ActionButton(footer, text="恢复随包版本", kind="ghost", compact=True)
    refresh_button = ui.ActionButton(footer, text="刷新", kind="secondary", compact=True)
    reset_button.pack(side="left")
    refresh_button.pack(side="right")
    update_button.pack(side="right", padx=(0, 7))

    def refresh(*, force: bool = True) -> None:
        inventory = tool_inventory(engine_module, refresh=force)
        ytdlp_source_var.set(_source_label(inventory.get("ytDlpSource")))
        ytdlp_version_var.set(_version_label(inventory.get("ytDlpVersion")))
        ffmpeg_source_var.set(_source_label(inventory.get("ffmpegSource")))
        ffmpeg_version_var.set(_version_label(inventory.get("ffmpegVersion")))
        if inventory.get("managedYtDlpReady"):
            reset_button.state(["!disabled"])
        else:
            reset_button.state(["disabled"])

    def set_busy(busy: bool) -> None:
        if busy:
            update_button.state(["disabled"])
            reset_button.state(["disabled"])
            refresh_button.state(["disabled"])
        else:
            update_button.state(["!disabled"])
            refresh_button.state(["!disabled"])
            refresh(force=True)

    def finish_result(result, *, action: str) -> None:
        if not _window_exists(dialog):
            return
        set_busy(False)
        operation_var.set(result.message)
        if result.ok:
            messagebox.showinfo(
                engine_module.APP_NAME,
                f"{action}完成。\n\n当前来源：{_source_label(result.source)}\n版本：{_version_label(result.version)}\n\n{result.message}",
                parent=dialog,
            )
        else:
            messagebox.showwarning(engine_module.APP_NAME, f"{action}未完成。\n\n{result.message}", parent=dialog)

    def update_ytdlp() -> None:
        operation_var.set("正在创建/更新托管 yt-dlp…")
        set_busy(True)

        def worker() -> None:
            result = update_managed_ytdlp(engine_module, channel="stable")
            try:
                dialog.after(0, finish_result, result, action="yt-dlp 更新")
            except tk.TclError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def reset_ytdlp() -> None:
        if not messagebox.askyesno(
            engine_module.APP_NAME,
            "删除用户目录中的托管 yt-dlp，并恢复使用发行包随附版本？\n\n不会删除任何下载文件或设置。",
            parent=dialog,
        ):
            return
        operation_var.set("正在恢复随包 yt-dlp…")
        set_busy(True)

        def worker() -> None:
            result = reset_managed_ytdlp(engine_module)
            try:
                dialog.after(0, finish_result, result, action="恢复随包版本")
            except tk.TclError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    update_button.configure(command=update_ytdlp)
    reset_button.configure(command=reset_ytdlp)
    refresh_button.configure(command=lambda: refresh(force=True))

    def close() -> None:
        window._tools_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh(force=True)


def install_desktop_tools(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_tools_installed", False):
        return window_cls

    register_desktop_presenter(
        window_cls,
        "tools",
        "desktop-tools",
        lambda window: _show_tools(window, engine_module),
        order=135,
    )

    def after_build_ui(window) -> None:
        actions = window._copy_diag_button.master
        window._tools_button = ui.ActionButton(
            actions,
            text="工具",
            command=lambda: show_desktop_presenter(window, "tools"),
            kind="ghost",
            compact=True,
        )
        window._tools_button.pack(side="left", padx=(8, 0))

    register_after_build_ui_hook(window_cls, "desktop-tools", after_build_ui, order=135)
    window_cls._galaxy_desktop_tools_installed = True
    return window_cls
