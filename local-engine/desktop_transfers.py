from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook
from telegram_transfer import (
    TelegramTransferError,
    TelegramUploadSettings,
    clear_telegram_bot_token,
    load_telegram_upload_settings,
    save_telegram_upload_settings,
    telegram_bot_token_configured,
    upload_to_telegram,
)
from transfer_center import (
    P2PSenderSession,
    download_torrent,
    receive_p2p_file,
    transfer_status,
)


def _entry(master, variable, width=30, **kwargs):
    options = {
        "textvariable": variable,
        "width": width,
        "font": ("Segoe UI", 8),
        "bg": ui.BG,
        "fg": ui.TEXT,
        "insertbackground": ui.TEXT,
        "relief": "flat",
        "highlightthickness": 1,
        "highlightbackground": ui.BORDER,
        "highlightcolor": ui.ACCENT,
    }
    options.update(kwargs)
    return tk.Entry(master, **options)


def _telegram_settings(mode: object, chat_id: object, send_as: object, user_adapter: object) -> TelegramUploadSettings:
    return TelegramUploadSettings(
        mode=str(mode or "bot").strip().lower(),
        chat_id=str(chat_id or "").strip(),
        send_as=str(send_as or "document").strip().lower(),
        user_adapter=str(user_adapter or "galaxy-telegram-user").strip(),
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
    dialog.geometry("900x660")
    dialog.minsize(780, 560)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "传输中心", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "Torrent / Magnet、局域网一次性短码 P2P，以及显式配置的 Telegram Bot / User Session 传输。",
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
            try:
                dialog.after(0, lambda: torrent_result_var.set(detail))
            except tk.TclError:
                return

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
                try:
                    dialog.after(0, lambda: sender_status_var.set(f"失败：{exc}"))
                except tk.TclError:
                    return

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
            try:
                dialog.after(0, lambda: receiver_status_var.set(detail))
            except tk.TclError:
                return

        threading.Thread(target=worker, daemon=True).start()

    ui.ActionButton(receive_row, text="接收", command=receive, kind="secondary", compact=True).pack(side="right")

    # Telegram
    telegram_tab = tk.Frame(notebook, bg=ui.PANEL, padx=16, pady=14)
    notebook.add(telegram_tab, text="Telegram")
    telegram_saved = load_telegram_upload_settings(engine_module)
    telegram_mode_var = tk.StringVar(value=telegram_saved.mode)
    telegram_chat_var = tk.StringVar(value=telegram_saved.chat_id)
    telegram_send_as_var = tk.StringVar(value=telegram_saved.send_as)
    telegram_adapter_var = tk.StringVar(value=telegram_saved.user_adapter)
    telegram_token_var = tk.StringVar(value="")
    telegram_token_state_var = tk.StringVar(
        value="Bot Token 已保存" if telegram_bot_token_configured(engine_module) else "Bot Token 未保存"
    )
    telegram_file_var = tk.StringVar(value="")
    telegram_name_var = tk.StringVar(value="")
    telegram_ext_var = tk.StringVar(value="")
    telegram_thumbnail_var = tk.StringVar(value="")
    telegram_caption_var = tk.StringVar(value="")
    telegram_chunk_var = tk.BooleanVar(value=True)
    telegram_status_var = tk.StringVar(value="选择 Galaxy 下载目录中的文件，然后上传到 Telegram。")

    settings_card = tk.Frame(
        telegram_tab,
        bg=ui.PANEL_2,
        padx=12,
        pady=11,
        highlightthickness=1,
        highlightbackground=ui.BORDER_SOFT,
    )
    settings_card.pack(fill="x")
    ui._label(settings_card, "Telegram 账户与目标", size=9, weight="bold", bg=ui.PANEL_2).pack(anchor="w")

    settings_row = tk.Frame(settings_card, bg=ui.PANEL_2)
    settings_row.pack(fill="x", pady=(9, 0))

    mode_field = tk.Frame(settings_row, bg=ui.PANEL_2)
    mode_field.pack(side="left")
    ui._label(mode_field, "模式", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w")
    mode_combo = ttk.Combobox(mode_field, textvariable=telegram_mode_var, values=("bot", "user"), state="readonly", width=10)
    mode_combo.pack(anchor="w", pady=(3, 0), ipady=4)

    chat_field = tk.Frame(settings_row, bg=ui.PANEL_2)
    chat_field.pack(side="left", fill="x", expand=True, padx=(10, 0))
    ui._label(chat_field, "Chat ID / @username", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w")
    chat_entry = _entry(chat_field, telegram_chat_var, 28, bg=ui.PANEL_3)
    chat_entry.pack(fill="x", pady=(3, 0), ipady=6)

    send_field = tk.Frame(settings_row, bg=ui.PANEL_2)
    send_field.pack(side="left", padx=(10, 0))
    ui._label(send_field, "发送类型", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w")
    send_combo = ttk.Combobox(
        send_field,
        textvariable=telegram_send_as_var,
        values=("document", "video", "audio"),
        state="readonly",
        width=12,
    )
    send_combo.pack(anchor="w", pady=(3, 0), ipady=4)

    adapter_field = tk.Frame(settings_row, bg=ui.PANEL_2)
    adapter_field.pack(side="left", fill="x", expand=True, padx=(10, 0))
    ui._label(adapter_field, "User adapter", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w")
    adapter_entry = _entry(adapter_field, telegram_adapter_var, 24, bg=ui.PANEL_3)
    adapter_entry.pack(fill="x", pady=(3, 0), ipady=6)

    token_row = tk.Frame(settings_card, bg=ui.PANEL_2)
    token_row.pack(fill="x", pady=(9, 0))
    token_field = tk.Frame(token_row, bg=ui.PANEL_2)
    token_field.pack(side="left", fill="x", expand=True)
    ui._label(token_field, "Bot Token（留空表示保留已保存 Token）", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w")
    token_entry = _entry(token_field, telegram_token_var, 46, bg=ui.PANEL_3, show="•")
    token_entry.pack(fill="x", pady=(3, 0), ipady=6)
    ui._label(token_row, variable=telegram_token_state_var, size=7, color=ui.MUTED, bg=ui.PANEL_2).pack(side="left", padx=(10, 0), pady=(17, 0))

    settings_actions = tk.Frame(token_row, bg=ui.PANEL_2)
    settings_actions.pack(side="right", padx=(10, 0), pady=(14, 0))

    def current_telegram_settings() -> TelegramUploadSettings:
        return _telegram_settings(
            telegram_mode_var.get(),
            telegram_chat_var.get(),
            telegram_send_as_var.get(),
            telegram_adapter_var.get(),
        )

    def refresh_telegram_mode(*_args) -> None:
        is_bot = telegram_mode_var.get().strip().lower() == "bot"
        token_entry.configure(state="normal" if is_bot else "disabled")
        adapter_entry.configure(state="disabled" if is_bot else "normal")

    def save_telegram_settings_from_ui() -> None:
        try:
            token = telegram_token_var.get().strip()
            saved = save_telegram_upload_settings(
                engine_module,
                current_telegram_settings(),
                bot_token=token if token else None,
            )
            telegram_mode_var.set(saved.mode)
            telegram_chat_var.set(saved.chat_id)
            telegram_send_as_var.set(saved.send_as)
            telegram_adapter_var.set(saved.user_adapter)
            telegram_token_var.set("")
            telegram_token_state_var.set(
                "Bot Token 已保存" if telegram_bot_token_configured(engine_module) else "Bot Token 未保存"
            )
            telegram_status_var.set("Telegram 设置已保存。")
            refresh_telegram_mode()
        except TelegramTransferError as exc:
            telegram_status_var.set(f"设置无效：{exc}")

    def clear_telegram_token_from_ui() -> None:
        try:
            clear_telegram_bot_token(engine_module)
            telegram_token_var.set("")
            telegram_token_state_var.set("Bot Token 未保存")
            telegram_status_var.set("Telegram Bot Token 已清除。")
        except TelegramTransferError as exc:
            telegram_status_var.set(f"清除失败：{exc}")

    settings_save_button = ui.ActionButton(
        settings_actions,
        text="保存设置",
        command=save_telegram_settings_from_ui,
        kind="secondary",
        compact=True,
    )
    settings_save_button.pack(side="left")
    settings_clear_button = ui.ActionButton(
        settings_actions,
        text="清除 Token",
        command=clear_telegram_token_from_ui,
        kind="ghost",
        compact=True,
    )
    settings_clear_button.pack(side="left", padx=(6, 0))

    upload_card = tk.Frame(telegram_tab, bg=ui.PANEL, pady=12)
    upload_card.pack(fill="both", expand=True)
    ui._label(upload_card, "上传 / Leech", size=9, weight="bold").pack(anchor="w")
    ui._label(
        upload_card,
        "Bot 模式使用 Telegram 官方 HTTPS Bot API；超过 50 MB 时可自动拆成 document 分片。User 模式只调用显式配置的本机 adapter。",
        size=7,
        color=ui.SUBTLE,
    ).pack(anchor="w", pady=(2, 8))

    file_row = tk.Frame(upload_card, bg=ui.PANEL)
    file_row.pack(fill="x")
    file_entry = _entry(
        file_row,
        telegram_file_var,
        56,
        state="readonly",
        readonlybackground=ui.PANEL_3,
        bg=ui.PANEL_3,
    )
    file_entry.pack(side="left", fill="x", expand=True, ipady=6)

    def choose_telegram_file() -> None:
        try:
            initial = str(Path(engine_module.default_download_dir()).resolve(strict=False))
        except Exception:  # noqa: BLE001
            initial = ""
        value = filedialog.askopenfilename(
            parent=dialog,
            title="选择 Galaxy 下载文件",
            initialdir=initial or None,
        )
        if value:
            telegram_file_var.set(value)
            source = Path(value)
            telegram_name_var.set(source.stem)
            telegram_ext_var.set(source.suffix.lstrip("."))

    file_choose_button = ui.ActionButton(
        file_row,
        text="选择 Galaxy 文件",
        command=choose_telegram_file,
        kind="ghost",
        compact=True,
    )
    file_choose_button.pack(side="right", padx=(8, 0))

    meta_row = tk.Frame(upload_card, bg=ui.PANEL)
    meta_row.pack(fill="x", pady=(8, 0))
    name_field = tk.Frame(meta_row, bg=ui.PANEL)
    name_field.pack(side="left", fill="x", expand=True)
    ui._label(name_field, "文件名", size=7, color=ui.SUBTLE).pack(anchor="w")
    _entry(name_field, telegram_name_var, 32, bg=ui.PANEL_3).pack(fill="x", pady=(3, 0), ipady=6)
    ext_field = tk.Frame(meta_row, bg=ui.PANEL)
    ext_field.pack(side="left", padx=(10, 0))
    ui._label(ext_field, "扩展名", size=7, color=ui.SUBTLE).pack(anchor="w")
    _entry(ext_field, telegram_ext_var, 10, bg=ui.PANEL_3).pack(pady=(3, 0), ipady=6)
    thumb_field = tk.Frame(meta_row, bg=ui.PANEL)
    thumb_field.pack(side="left", fill="x", expand=True, padx=(10, 0))
    ui._label(thumb_field, "JPEG 缩略图（可选）", size=7, color=ui.SUBTLE).pack(anchor="w")
    thumb_entry = _entry(
        thumb_field,
        telegram_thumbnail_var,
        28,
        state="readonly",
        readonlybackground=ui.PANEL_3,
        bg=ui.PANEL_3,
    )
    thumb_entry.pack(side="left", fill="x", expand=True, pady=(3, 0), ipady=6)

    def choose_telegram_thumbnail() -> None:
        value = filedialog.askopenfilename(
            parent=dialog,
            title="选择 Telegram JPEG 缩略图",
            filetypes=(("JPEG", "*.jpg *.jpeg"),),
        )
        if value:
            telegram_thumbnail_var.set(value)

    thumbnail_button = ui.ActionButton(
        thumb_field,
        text="选择",
        command=choose_telegram_thumbnail,
        kind="ghost",
        compact=True,
    )
    thumbnail_button.pack(side="right", padx=(6, 0), pady=(3, 0))

    caption_row = tk.Frame(upload_card, bg=ui.PANEL)
    caption_row.pack(fill="x", pady=(8, 0))
    caption_field = tk.Frame(caption_row, bg=ui.PANEL)
    caption_field.pack(side="left", fill="x", expand=True)
    ui._label(caption_field, "Caption（最多 1024 字符）", size=7, color=ui.SUBTLE).pack(anchor="w")
    caption_entry = _entry(caption_field, telegram_caption_var, 56, bg=ui.PANEL_3)
    caption_entry.pack(fill="x", pady=(3, 0), ipady=6)

    chunk_check = tk.Checkbutton(
        caption_row,
        text=">50 MB 自动分片",
        variable=telegram_chunk_var,
        onvalue=True,
        offvalue=False,
        takefocus=True,
        bg=ui.PANEL,
        fg=ui.TEXT,
        activebackground=ui.PANEL,
        activeforeground=ui.TEXT,
        selectcolor=ui.PANEL_3,
        font=("Segoe UI", 8, "bold"),
        bd=0,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER_SOFT,
        highlightcolor=ui.ACCENT,
        cursor="hand2",
    )
    chunk_check.pack(side="left", padx=(10, 0), pady=(16, 0))

    upload_footer = tk.Frame(upload_card, bg=ui.PANEL)
    upload_footer.pack(fill="x", pady=(10, 0))
    ui._label(upload_footer, variable=telegram_status_var, size=7, color=ui.MUTED).pack(side="left", fill="x", expand=True)

    telegram_busy_controls: list[object] = [
        settings_save_button,
        settings_clear_button,
        file_choose_button,
        thumbnail_button,
    ]

    def set_telegram_busy(busy: bool) -> None:
        for control in telegram_busy_controls:
            try:
                control.state(["disabled" if busy else "!disabled"])
            except (AttributeError, tk.TclError):
                pass
        for control in (mode_combo, send_combo, chat_entry, token_entry, adapter_entry, caption_entry, chunk_check):
            try:
                control.configure(state="disabled" if busy else "normal")
            except tk.TclError:
                pass
        if not busy:
            mode_combo.configure(state="readonly")
            send_combo.configure(state="readonly")
            refresh_telegram_mode()

    def start_telegram_upload() -> None:
        source = telegram_file_var.get().strip()
        if not source:
            telegram_status_var.set("请先选择 Galaxy 下载目录中的文件。")
            return
        settings = current_telegram_settings()
        token = telegram_token_var.get().strip()
        filename = telegram_name_var.get().strip()
        extension = telegram_ext_var.get().strip()
        thumbnail = telegram_thumbnail_var.get().strip()
        caption = telegram_caption_var.get().strip()
        auto_chunk = bool(telegram_chunk_var.get())
        set_telegram_busy(True)
        telegram_status_var.set("正在提交 Telegram 上传…")

        def worker() -> None:
            try:
                saved = save_telegram_upload_settings(
                    engine_module,
                    settings,
                    bot_token=token if token else None,
                )
                results = upload_to_telegram(
                    engine_module,
                    file_path=source,
                    filename=filename,
                    extension=extension,
                    thumbnail=thumbnail,
                    caption=caption,
                    auto_chunk=auto_chunk,
                )
                count = len(results)
                detail = f"Telegram 上传完成 · {count} 个消息/分片 · {saved.mode} 模式"
                ok = True
            except Exception as exc:  # noqa: BLE001
                detail = f"Telegram 上传失败：{exc}"
                ok = False

            def finish() -> None:
                set_telegram_busy(False)
                if ok:
                    telegram_token_var.set("")
                    telegram_token_state_var.set(
                        "Bot Token 已保存" if telegram_bot_token_configured(engine_module) else "Bot Token 未保存"
                    )
                telegram_status_var.set(detail[:300])

            try:
                dialog.after(0, finish)
            except tk.TclError:
                return

        threading.Thread(target=worker, name="GalaxyTelegramUpload", daemon=True).start()

    telegram_upload_button = ui.ActionButton(
        upload_footer,
        text="上传到 Telegram",
        command=start_telegram_upload,
        kind="secondary",
        compact=True,
    )
    telegram_upload_button.pack(side="right", padx=(8, 0))
    telegram_busy_controls.append(telegram_upload_button)
    mode_combo.bind("<<ComboboxSelected>>", refresh_telegram_mode)
    refresh_telegram_mode()

    def refresh_status() -> None:
        data = transfer_status(engine_module)
        torrent = "aria2c/Torrent ✓" if data["torrentReady"] else "aria2c 未安装"
        settings = load_telegram_upload_settings(engine_module)
        if settings.mode == "user":
            telegram = "Telegram User adapter"
        elif telegram_bot_token_configured(engine_module):
            telegram = "Telegram Bot ✓"
        else:
            telegram = "Telegram Bot 未配置"
        status_var.set(f"{torrent} · LAN P2P ✓ · {telegram} · discovery UDP {data['p2pDiscoveryPort']}")

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
    ui._label(text, "Magnet/Torrent · 局域网 P2P · Telegram", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w", pady=(2, 0))
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
    assert callable(upload_to_telegram)
    settings = _telegram_settings("BOT", " @example_user ", "VIDEO", "galaxy-telegram-user")
    assert settings.mode == "bot"
    assert settings.chat_id == "@example_user"
    assert settings.send_as == "video"
