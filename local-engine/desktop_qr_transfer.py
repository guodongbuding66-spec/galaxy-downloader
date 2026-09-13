from __future__ import annotations

import io
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from PIL import Image, ImageTk

import desktop_ui as ui
from qr_transfer import QRTransferSession


def build_qr_transfer_tab(notebook: ttk.Notebook, dialog: tk.Misc) -> tk.Frame:
    tab = tk.Frame(notebook, bg=ui.PANEL, padx=16, pady=14)
    notebook.add(tab, text="QR 手机接收")

    ui._label(tab, "QR Transfer · 手机浏览器直接接收", size=10, weight="bold").pack(anchor="w")
    ui._label(
        tab,
        "选择一个本地文件后生成一次性局域网二维码。手机与电脑需处于同一局域网；文件不经过云端。",
        size=7,
        color=ui.SUBTLE,
    ).pack(anchor="w", pady=(3, 10))

    file_var = tk.StringVar(value="")
    url_var = tk.StringVar(value="")
    status_var = tk.StringVar(value="选择文件后创建二维码。链接默认 10 分钟内有效，成功下载一次后立即失效。")
    current_session: list[QRTransferSession | None] = [None]
    current_photo: list[ImageTk.PhotoImage | None] = [None]

    source_card = tk.Frame(
        tab,
        bg=ui.PANEL_2,
        padx=12,
        pady=11,
        highlightthickness=1,
        highlightbackground=ui.BORDER_SOFT,
    )
    source_card.pack(fill="x")
    ui._label(source_card, "发送文件", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")

    source_row = tk.Frame(source_card, bg=ui.PANEL_2)
    source_row.pack(fill="x", pady=(7, 0))
    source_entry = tk.Entry(
        source_row,
        textvariable=file_var,
        state="readonly",
        readonlybackground=ui.PANEL_3,
        bg=ui.PANEL_3,
        fg=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
        font=("Segoe UI", 8),
    )
    source_entry.pack(side="left", fill="x", expand=True, ipady=6)

    def choose_file() -> None:
        value = filedialog.askopenfilename(parent=dialog, title="选择要通过 QR Transfer 发送的文件")
        if value:
            file_var.set(value)
            status_var.set("文件已选择；创建二维码后可用手机浏览器直接接收。")

    choose_button = ui.ActionButton(source_row, text="选择文件", command=choose_file, kind="ghost", compact=True)
    choose_button.pack(side="right", padx=(8, 0))

    content = tk.Frame(tab, bg=ui.PANEL)
    content.pack(fill="both", expand=True, pady=(12, 0))

    qr_card = tk.Frame(
        content,
        bg=ui.PANEL_2,
        padx=14,
        pady=14,
        highlightthickness=1,
        highlightbackground=ui.BORDER_SOFT,
    )
    qr_card.pack(side="left", fill="both", expand=False)
    qr_label = tk.Label(
        qr_card,
        text="二维码将在这里显示",
        width=28,
        height=14,
        bg=ui.PANEL_3,
        fg=ui.MUTED,
        font=("Segoe UI", 8),
        relief="flat",
        bd=0,
    )
    qr_label.pack()

    detail = tk.Frame(content, bg=ui.PANEL, padx=16)
    detail.pack(side="left", fill="both", expand=True)
    ui._label(detail, "一次性接收地址", size=8, weight="bold").pack(anchor="w")
    url_entry = tk.Entry(
        detail,
        textvariable=url_var,
        state="readonly",
        readonlybackground=ui.PANEL_3,
        bg=ui.PANEL_3,
        fg=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
        font=("Segoe UI", 8),
    )
    url_entry.pack(fill="x", pady=(5, 0), ipady=6)
    ui._label(
        detail,
        "地址包含临时随机令牌。不要公开分享；停止发送、到期或成功下载后都会失效。",
        size=7,
        color=ui.SUBTLE,
    ).pack(anchor="w", pady=(6, 0))
    ui._label(detail, variable=status_var, size=8, color=ui.MUTED).pack(anchor="w", pady=(14, 0))

    actions = tk.Frame(detail, bg=ui.PANEL)
    actions.pack(fill="x", pady=(16, 0))

    def stop_transfer(*, update_status: bool = True) -> None:
        session = current_session[0]
        if session is not None:
            session.stop()
            current_session[0] = None
        current_photo[0] = None
        try:
            qr_label.configure(image="", text="二维码将在这里显示")
        except tk.TclError:
            pass
        url_var.set("")
        if update_status:
            status_var.set("QR Transfer 已停止。")

    def set_busy(busy: bool) -> None:
        for control in (choose_button, create_button, stop_button):
            try:
                control.state(["disabled" if busy else "!disabled"])
            except (AttributeError, tk.TclError):
                pass

    def create_transfer() -> None:
        raw_path = file_var.get().strip()
        if not raw_path:
            status_var.set("请先选择要发送的文件。")
            return
        source = Path(raw_path)
        set_busy(True)
        status_var.set("正在创建局域网一次性接收地址…")

        def worker() -> None:
            session: QRTransferSession | None = None
            try:
                session = QRTransferSession(source).start()
                png = session.qr_png_bytes(box_size=7, border=4)
                payload = session.public_payload()

                def finish() -> None:
                    old = current_session[0]
                    if old is not None and old is not session:
                        old.stop()
                    current_session[0] = session
                    image = Image.open(io.BytesIO(png)).convert("RGB")
                    image.thumbnail((260, 260))
                    photo = ImageTk.PhotoImage(image)
                    current_photo[0] = photo
                    qr_label.configure(image=photo, text="", width=260, height=260)
                    url_var.set(str(payload.get("url") or ""))
                    ttl = int(payload.get("ttlSeconds") or 0)
                    status_var.set(f"已就绪 · {payload.get('fileName', '')} · 最长 {ttl // 60} 分钟 · 成功下载一次后失效")
                    set_busy(False)

                dialog.after(0, finish)
            except Exception as exc:  # noqa: BLE001
                if session is not None:
                    session.stop()

                def finish_error() -> None:
                    status_var.set(f"创建失败：{exc}"[:260])
                    set_busy(False)

                try:
                    dialog.after(0, finish_error)
                except tk.TclError:
                    return

        threading.Thread(target=worker, name="GalaxyQRTransfer", daemon=True).start()

    create_button = ui.ActionButton(actions, text="创建二维码", command=create_transfer, kind="secondary", compact=True)
    create_button.pack(side="right")
    stop_button = ui.ActionButton(actions, text="停止发送", command=stop_transfer, kind="ghost", compact=True)
    stop_button.pack(side="right", padx=(0, 7))

    tab._galaxy_qr_stop = lambda: stop_transfer(update_status=False)  # type: ignore[attr-defined]
    return tab


def run_desktop_qr_transfer_self_test() -> None:
    assert callable(build_qr_transfer_tab)
