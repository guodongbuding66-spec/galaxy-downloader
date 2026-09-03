from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook
from transfer_center import (
    P2PSenderSession,
    TransferError,
    download_torrent,
    receive_p2p_file,
    transfer_status,
)


def _entry(master, variable, width=30):
    return tk.Entry(
        master,
        textvariable=variable,
        width=width,
        font=("Segoe UI", 8),
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
    )


def _show_transfer_center(window, engine_module) -> None:
    existing = getattr(window, "_transfer_center_window", None)
    if existing is not None:
        try:
            existing.deiconify()
            existing.lift()
            return
        except tk.TclError:
            pass

    dialog = tk.Toplevel(window)
    window._transfer_center_window = dialog
    dialog.title("传输中心 · Galaxy Local Engine")
    dialog.geometry("820x590")
    dialog.minsize(720, 520)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "Torrent / Magnet 与局域网 P2P", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "Torrent 使用 aria2c；短码传输无需云端中转，只在同一局域网广播短码哈希并进行一次性文件传输。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(4, 12))

    status_var = tk.StringVar(value="检测中…")
    ui._label(shell, variable=status_var, size=8, color=ui.CYAN, bg=ui.BG).pack(anchor="w", pady=(0, 10))

    style = ttk.Style(dialog)
    style.configure("Galaxy.TNotebook", background=ui.BG, borderwidth=0)
    style.configure("Galaxy.TNotebook.Tab", background=ui.PANEL_2, foreground=ui.MUTED, padding=(12, 7))
    style.map("Galaxy.TNotebook.Tab", background=[("selected", ui.PANEL_3)], foreground=[("selected", ui.TEXT)])
    notebook = ttk.Notebook(shell, style="Galaxy.TNotebook")
    notebook.pack(fill="both", expand=True)

    # Torrent
    torrent_tab = tk.Frame(notebook, bg=ui.PANEL, padx=16, pady=16)
    notebook.add(torrent_tab, text="Torrent / Magnet")
    torrent_source_var = tk.StringVar()
    torrent_result_var = tk.StringVar(value="就绪")
    ui._label(torrent_tab, "Magnet 链接或 .torrent 文件", size=9, weight="bold").pack(anchor="w")
    torrent_row = tk.Frame(torrent_tab, bg=ui.PANEL)
    torrent_row.pack(fill="x", pady=(9, 0))
    _entry(torrent_row, torrent_source_var, 58).pack(side="left", fill="x", expand=True)

    def choose_torrent() -> None:
        value = filedialog.askopenfilename(parent=dialog, title="选择 Torrent", filetypes=(("Torrent", "*.torrent"),))
        if value:
            torrent_source_var.set(value)

    ui.ActionButton(torrent_row, text="选择文件", command=choose_torrent, kind="ghost", compact=True).pack(side="right", padx=(8, 0))
    ui._label(
        torrent_tab,
        "默认下载到 downloads/torrents，支持断点续传；完成后 seed-time=0，不会继续长期做种。",
        size=7,
        color=ui.SUBTLE,
    ).pack(anchor="w", pady=(7, 0))
    ui._label(torrent_tab, variable=torrent_result_var, size=8, color=ui.MUTED).pack(anchor="w", pady=(12, 0))

    def start_torrent() -> None:
        source = torrent_source_var.get().strip()
        if not source:
            return
        torrent_result_var.set("正在下载…")

        def worker() -> None:
            try:
                result = download_torrent(engine_module, source)
                detail = f"{result.message} · {result.destination}"
            except Exception as exc:  # noqa: BLE001
                detail = f"失败：{exc}"
            dialog.after(0, lambda: torrent_result_var.set(detail))

        threading.Thread(target=worker, daemon=True).start()

    ui.ActionButton(torrent_tab, text="开始 Torrent 下载", command=start_torrent, kind="secondary", compact=True).pack(anchor="e", pady=(14, 0))

    # P2P
    p2p_tab = tk.Frame(notebook, bg=ui.PANEL, padx=16, pady=16)
    notebook.add(p2p_tab, text="P2P 短码")
    sender_file_var = tk.StringVar()
    sender_code_var = tk.StringVar(value="—")
    sender_status_var = tk.StringVar(value="选择一个文件后创建短码")
    receiver_code_var = tk.StringVar()
    receiver_status_var = tk.StringVar(value="输入发送端短码；双方需处于同一局域网")
    current_session: list[P2PSenderSession | None] = [None]

    ui._label(p2p_tab, "发送文件", size=9, weight="bold").pack(anchor="w")
    send_row = tk.Frame(p2p_tab, bg=ui.PANEL)
    send_row.pack(fill="x", pady=(8, 0))
    _entry(send_row, sender_file_var, 54).pack(side="left", fill="x", expand=True)

    def choose_send_file() -> None:
        value = filedialog.askopenfilename(parent=dialog, title="选择要发送的文件")
        if value:
            sender_file_var.set(value)

    ui.ActionButton(send_row, text="选择文件", command=choose_send_file, kind="ghost", compact=True).pack(side="right", padx=(8, 0))

    code_card = tk.Frame(p2p_tab, bg=ui.PANEL_2, padx=12, pady=10, highlightthickness=1, highlightbackground=ui.BORDER_SOFT)
    code_card.pack(fill="x", pady=(9, 0))
    ui._label(code_card, "一次性短码", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w")
    ui._label(code_card, variable=sender_code_var, size=18, weight="bold", color=ui.CYAN, bg=ui.PANEL_2).pack(anchor="w", pady=(2, 0))
    ui._label(code_card, variable=sender_status_var, size=7, color=ui.MUTED, bg=ui.PANEL_2).pack(anchor="w", pady=(4, 0))

    def sender_status(message: str) -> None:
        try:
            dialog.after(0, lambda: sender_status_var.set(message))
        except tk.TclError:
            pass

    def start_sender() -> None:
        value = sender_file_var.get().strip()
        if not value:
            return
        old = current_session[0]
        if old is not None:
            old.stop()
        sender_status_var.set("准备发送端…")
        sender_code_var.set("—")

        def worker() -> None:
            try:
                session = P2PSenderSession(Path(value), on_status=sender_status).start()
                current_session[0] = session
                dialog.after(0, lambda: sender_code_var.set(session.code))
            except Exception as exc:  # noqa: BLE001
                dialog.after(0, lambda: sender_status_var.set(f"失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def stop_sender() -> None:
        session = current_session[0]
        if session is not None:
            session.stop()
            current_session[0] = None
        sender_code_var.set("—")
        sender_status_var.set("发送端已停止")

    send_actions = tk.Frame(p2p_tab, bg=ui.PANEL)
    send_actions.pack(fill="x", pady=(8, 0))
    ui.ActionButton(send_actions, text="停止发送", command=stop_sender, kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(send_actions, text="创建短码并发送", command=start_sender, kind="secondary", compact=True).pack(side="right", padx=(0, 6))

    ui._divider(p2p_tab).pack(fill="x", pady=(14, 12))
    ui._label(p2p_tab, "接收文件", size=9, weight="bold").pack(anchor="w")
    receive_row = tk.Frame(p2p_tab, bg=ui.PANEL)
    receive_row.pack(fill="x", pady=(8, 0))
    _entry(receive_row, receiver_code_var, 24).pack(side="left")
    ui._label(receive_row, variable=receiver_status_var, size=7, color=ui.MUTED).pack(side="left", padx=(10, 0))

    def receive() -> None:
        code = receiver_code_var.get().strip().upper()
        if not code:
            return
        receiver_status_var.set("正在局域网发现发送端…")

        def progress(done: int, total: int) -> None:
            percent = int(done * 100 / total) if total else 0
            try:
                dialog.after(0, lambda: receiver_status_var.set(f"接收中 {percent}% · {done:,}/{total:,} bytes"))
            except tk.TclError:
                pass

        def worker() -> None:
            try:
                result = receive_p2p_file(engine_module, code, on_progress=progress)
                detail = f"接收完成：{result.path.name} · SHA-256 {result.sha256[:12]}…"
            except Exception as exc:  # noqa: BLE001
                detail = f"失败：{exc}"
            dialog.after(0, lambda: receiver_status_var.set(detail))

        threading.Thread(target=worker, daemon=True).start()

    ui.ActionButton(receive_row, text="接收", command=receive, kind="secondary", compact=True).pack(side="right")

    def refresh_status() -> None:
        data = transfer_status(engine_module)
        torrent = "aria2c/Torrent ✓" if data["torrentReady"] else "aria2c 未安装"
        status_var.set(f"{torrent} · LAN P2P ✓ · discovery UDP {data['p2pDiscoveryPort']}")

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(10, 0))
    ui.ActionButton(footer, text="刷新检测", command=refresh_status, kind="ghost", compact=True).pack(side="left")

    def close() -> None:
        stop_sender()
        window._transfer_center_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh_status()


def _add_transfer_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_transfer_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "传输中心", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(text, "Magnet/Torrent · 局域网一次性短码 P2P", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(
        card,
        text="打开传输中心",
        command=lambda: _show_transfer_center(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_transfer_entry_built = True


def install_desktop_transfers(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_transfers_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-transfers",
        lambda window: _add_transfer_entry(window, engine_module),
        order=64,
    )
    window_cls._galaxy_desktop_transfers_installed = True
    return window_cls


def run_desktop_transfers_self_test() -> None:
    assert callable(download_torrent)
    assert callable(receive_p2p_file)
