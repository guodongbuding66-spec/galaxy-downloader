from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook, register_desktop_presenter, show_desktop_presenter
from ffmpeg_manager import existing_managed_ffmpeg, reset_managed_ffmpeg, seed_managed_ffmpeg
from ffmpeg_online_installer import install_managed_ffmpeg_online
from ffmpeg_update_status import check_ffmpeg_update
from tool_manager import invalidate_tool_inventory, reset_managed_ytdlp, tool_inventory, update_managed_ytdlp
from tool_sources import trusted_ffmpeg_source_available


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
    dialog.geometry("800x650")
    dialog.minsize(720, 590)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "工具管理", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "普通启动、刷新和下载不会联网检查工具。只有你主动点击“检查更新”或“在线安装 / 更新”时，Galaxy 才访问经过审核的工具源；托管版本都位于 runtime/tools，可独立恢复到发行包基线。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=740,
        justify="left",
    ).pack(anchor="w", pady=(4, 12))

    card = tk.Frame(shell, bg=ui.PANEL, padx=16, pady=14, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)

    ytdlp_source_var = tk.StringVar(value="—")
    ytdlp_version_var = tk.StringVar(value="—")
    ffmpeg_source_var = tk.StringVar(value="—")
    ffmpeg_version_var = tk.StringVar(value="—")
    ffmpeg_update_var = tk.StringVar(value="尚未检查在线 FFmpeg 更新。")
    operation_var = tk.StringVar(value="")

    def tool_row(title: str, source_var: tk.StringVar, version_var: tk.StringVar) -> None:
        row = tk.Frame(card, bg=ui.PANEL)
        row.pack(fill="x", pady=(2, 10))
        left = tk.Frame(row, bg=ui.PANEL)
        left.pack(side="left", fill="x", expand=True)
        ui._label(left, title, size=10, weight="bold").pack(anchor="w")
        ui._label(left, variable=version_var, size=8, color=ui.SUBTLE, wraplength=520, justify="left").pack(anchor="w", pady=(3, 0))
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

    ffmpeg_actions = tk.Frame(card, bg=ui.PANEL)
    ffmpeg_actions.pack(fill="x", pady=(0, 7))
    ffmpeg_check_button = ui.ActionButton(ffmpeg_actions, text="检查 FFmpeg 更新", kind="secondary", compact=True)
    ffmpeg_online_button = ui.ActionButton(ffmpeg_actions, text="在线安装 / 更新 FFmpeg", kind="primary", compact=True)
    ffmpeg_seed_button = ui.ActionButton(ffmpeg_actions, text="从随包创建托管副本", kind="secondary", compact=True)
    ffmpeg_reset_button = ui.ActionButton(ffmpeg_actions, text="恢复随包 FFmpeg", kind="ghost", compact=True)
    ffmpeg_check_button.pack(side="left")
    ffmpeg_online_button.pack(side="left", padx=(7, 0))
    ffmpeg_seed_button.pack(side="left", padx=(7, 0))
    ffmpeg_reset_button.pack(side="left", padx=(7, 0))

    ui._label(
        card,
        variable=ffmpeg_update_var,
        size=8,
        weight="bold",
        color=ui.CYAN,
        wraplength=730,
        justify="left",
    ).pack(anchor="w", pady=(2, 7))
    ui._label(
        card,
        "检查更新只读取可信 provider 的发布元数据，不下载 FFmpeg。在线安装才下载构建，并在 staging 内校验来源、SHA-256、归档布局、资源上限、ffmpeg/ffprobe 可执行性与本地来源元数据，全部通过后才原子替换。",
        size=7,
        color=ui.SUBTLE,
        wraplength=730,
        justify="left",
    ).pack(anchor="w", pady=(0, 3))
    ui._label(
        card,
        "离线兜底：不联网，只把发行包内已验证的 FFmpeg 复制到 runtime/tools。随包种子没有在线 release identity，因此检查更新时会明确显示“无法精确比较”，不会猜测版本顺序。",
        size=7,
        color=ui.SUBTLE,
        wraplength=730,
        justify="left",
    ).pack(anchor="w", pady=(0, 9))

    ui._divider(card).pack(fill="x", pady=(2, 10))
    ui._label(
        card,
        "yt-dlp 更新会先创建用户目录托管副本，再调用 yt-dlp 官方自更新机制。所有工具动作都由用户显式触发；Galaxy 不在后台自动检查或替换二进制。",
        size=7,
        color=ui.SUBTLE,
        wraplength=730,
        justify="left",
    ).pack(anchor="w")
    ui._label(card, variable=operation_var, size=8, weight="bold", color=ui.CYAN, wraplength=730, justify="left").pack(anchor="w", pady=(10, 0))

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    update_button = ui.ActionButton(footer, text="更新 yt-dlp", kind="primary", compact=True)
    reset_button = ui.ActionButton(footer, text="恢复随包 yt-dlp", kind="ghost", compact=True)
    refresh_button = ui.ActionButton(footer, text="刷新本地状态", kind="secondary", compact=True)
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

        managed_ready = existing_managed_ffmpeg(engine_module) is not None
        if managed_ready:
            ffmpeg_seed_button.state(["disabled"])
            ffmpeg_reset_button.state(["!disabled"])
        else:
            ffmpeg_seed_button.state(["!disabled"])
            ffmpeg_reset_button.state(["disabled"])

        if trusted_ffmpeg_source_available():
            ffmpeg_check_button.state(["!disabled"])
            ffmpeg_online_button.state(["!disabled"])
        else:
            ffmpeg_check_button.state(["disabled"])
            ffmpeg_online_button.state(["disabled"])
            ffmpeg_update_var.set("当前平台尚未配置经过审核的 FFmpeg 在线构建源。")

    def set_busy(busy: bool) -> None:
        buttons = (
            update_button,
            reset_button,
            refresh_button,
            ffmpeg_check_button,
            ffmpeg_online_button,
            ffmpeg_seed_button,
            ffmpeg_reset_button,
        )
        if busy:
            for button in buttons:
                button.state(["disabled"])
        else:
            update_button.state(["!disabled"])
            refresh_button.state(["!disabled"])
            refresh(force=True)

    def finish_result(result, action: str) -> None:
        if not _window_exists(dialog):
            return
        invalidate_tool_inventory(engine_module)
        set_busy(False)
        operation_var.set(result.message)
        if action in {"在线安装 / 更新 FFmpeg", "从随包创建托管 FFmpeg", "恢复随包 FFmpeg"}:
            ffmpeg_update_var.set("本地 FFmpeg 状态已变化；可再次点击“检查 FFmpeg 更新”确认在线发布身份。")
        if result.ok:
            messagebox.showinfo(
                engine_module.APP_NAME,
                f"{action}完成。\n\n当前来源：{_source_label(result.source)}\n版本：{_version_label(result.version)}\n\n{result.message}",
                parent=dialog,
            )
        else:
            messagebox.showwarning(engine_module.APP_NAME, f"{action}未完成。\n\n{result.message}", parent=dialog)

    def finish_update_status(status) -> None:
        if not _window_exists(dialog):
            return
        set_busy(False)
        operation_var.set(status.message)
        ffmpeg_update_var.set(status.message)
        details = (
            f"当前来源：{_source_label(status.current_source)}\n"
            f"当前版本：{_version_label(status.current_version)}\n"
            f"当前发布：{_version_label(status.current_release_tag)}\n\n"
            f"在线构建：{_version_label(status.available_version)}\n"
            f"在线发布：{_version_label(status.available_release_tag)}\n\n"
            f"{status.message}"
        )
        if status.ok:
            messagebox.showinfo(engine_module.APP_NAME, details, parent=dialog)
        else:
            messagebox.showwarning(engine_module.APP_NAME, details, parent=dialog)

    def run_action(action_name: str, status_text: str, callback) -> None:
        operation_var.set(status_text)
        set_busy(True)

        def worker() -> None:
            result = callback()
            try:
                dialog.after(0, finish_result, result, action_name)
            except tk.TclError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def check_ffmpeg() -> None:
        operation_var.set("正在检查可信 FFmpeg provider 的发布元数据…")
        ffmpeg_update_var.set("正在检查更新…")
        set_busy(True)

        def worker() -> None:
            status = check_ffmpeg_update(engine_module)
            try:
                dialog.after(0, finish_update_status, status)
            except tk.TclError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def update_ytdlp() -> None:
        run_action(
            "yt-dlp 更新",
            "正在创建/更新托管 yt-dlp…",
            lambda: update_managed_ytdlp(engine_module, channel="stable"),
        )

    def reset_ytdlp() -> None:
        if not messagebox.askyesno(
            engine_module.APP_NAME,
            "删除用户目录中的托管 yt-dlp，并恢复使用发行包随附版本？\n\n不会删除任何下载文件或设置。",
            parent=dialog,
        ):
            return
        run_action("恢复随包 yt-dlp", "正在恢复随包 yt-dlp…", lambda: reset_managed_ytdlp(engine_module))

    def install_ffmpeg_online() -> None:
        if not messagebox.askyesno(
            engine_module.APP_NAME,
            "从可信 BtbN FFmpeg 构建源下载并安装/更新托管 FFmpeg？\n\n"
            "Galaxy 会先校验来源、SHA-256、归档布局、解压资源上限以及 ffmpeg/ffprobe 可执行性，并把发布身份写入 staging。"
            "全部通过后才替换 runtime/tools 中的托管版本。\n发行包内 FFmpeg 不会被修改。",
            parent=dialog,
        ):
            return
        run_action(
            "在线安装 / 更新 FFmpeg",
            "正在解析可信 FFmpeg 构建、下载并验证…",
            lambda: install_managed_ffmpeg_online(engine_module),
        )

    def seed_ffmpeg() -> None:
        run_action(
            "从随包创建托管 FFmpeg",
            "正在从已验证的随包 FFmpeg 创建托管副本并校验…",
            lambda: seed_managed_ffmpeg(engine_module),
        )

    def reset_ffmpeg() -> None:
        if not messagebox.askyesno(
            engine_module.APP_NAME,
            "删除 runtime/tools 中的托管 FFmpeg，并恢复使用发行包随附版本？\n\n不会删除媒体文件或设置。",
            parent=dialog,
        ):
            return
        run_action("恢复随包 FFmpeg", "正在恢复随包 FFmpeg…", lambda: reset_managed_ffmpeg(engine_module))

    update_button.configure(command=update_ytdlp)
    reset_button.configure(command=reset_ytdlp)
    ffmpeg_check_button.configure(command=check_ffmpeg)
    ffmpeg_online_button.configure(command=install_ffmpeg_online)
    ffmpeg_seed_button.configure(command=seed_ffmpeg)
    ffmpeg_reset_button.configure(command=reset_ffmpeg)
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
