from __future__ import annotations

"""Native Tk lifecycle controls for Galaxy Torrent/aria2 transfers."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import desktop_ui as ui
from aria2_transfer import Aria2Progress, Aria2TransferSnapshot
from desktop_design_tokens import LAYOUT
from transfer_center import start_torrent_transfer

_STATE_TEXT = {
    "queued": "等待启动", "running": "下载中", "retrying": "重试等待",
    "pausing": "正在暂停", "paused": "已暂停", "cancelling": "正在取消",
    "cancelled": "已取消", "completed": "已完成", "failed": "失败",
}
_ACTIVE = {"queued", "running", "retrying", "pausing", "cancelling"}


def torrent_snapshot_text(snapshot: Aria2TransferSnapshot) -> tuple[str, str]:
    p = snapshot.progress
    primary = f"{_STATE_TEXT.get(snapshot.state, snapshot.state)} · {p.percent}%"
    parts = []
    if p.speed: parts.append(f"速度 {p.speed}/s")
    if p.eta: parts.append(f"剩余 {p.eta}")
    if p.connections: parts.append(f"连接 {p.connections}")
    if snapshot.attempt: parts.append(f"尝试 {snapshot.attempt}/{snapshot.max_attempts}")
    if snapshot.error and snapshot.state in {"failed", "retrying"}: parts.append(snapshot.error[:180])
    if snapshot.state == "completed": parts.append(str(snapshot.destination))
    return primary, " · ".join(parts) or "aria2c 已就绪"


def _enabled(button, value: bool) -> None:
    state = "normal" if value else "disabled"
    try:
        button.configure(state=state)
        return
    except (AttributeError, tk.TclError):
        pass
    try:
        button.state(["!disabled" if value else "disabled"])
    except (AttributeError, tk.TclError):
        pass


def _notebook(root: tk.Misc) -> ttk.Notebook | None:
    for child in root.winfo_children():
        if isinstance(child, ttk.Notebook): return child
        found = _notebook(child)
        if found is not None: return found
    return None


def _install_torrent_tab(window, dialog: tk.Toplevel, engine_module) -> None:
    if getattr(dialog, "_galaxy_aria2_tab_installed", False):
        session = getattr(window, "_galaxy_aria2_torrent_session", None)
        if session is not None and hasattr(dialog, "_galaxy_aria2_render"):
            session.set_listener(dialog._galaxy_aria2_render)
        return
    book = _notebook(dialog)
    if book is None or not book.tabs(): return
    tab = book.nametowidget(book.tabs()[0])
    for child in tab.winfo_children(): child.destroy()
    tab.configure(bg=ui.PANEL, padx=LAYOUT["section"], pady=LAYOUT["section"])
    book.tab(book.tabs()[0], text="Torrent / Magnet")

    source = tk.StringVar()
    status = tk.StringVar(value="就绪 · 支持实时进度、暂停/继续、失败重试")
    detail = tk.StringVar(value="aria2c 使用断点续传；关闭此窗口不会中断正在进行的任务。")
    pct = tk.DoubleVar(value=0.0)
    ui._label(tab, "Torrent / Magnet", size=11, weight="bold").pack(anchor="w")
    ui._label(tab, "Magnet 链接或 .torrent 文件；失败最多自动重试 3 次，暂停会保留 aria2 控制文件。",
              size=7, color=ui.SUBTLE, wraplength=760, justify="left").pack(anchor="w", pady=(4, 12))
    row = tk.Frame(tab, bg=ui.PANEL); row.pack(fill="x")
    entry = tk.Entry(row, textvariable=source, font=("Segoe UI", 10), bg=ui.PANEL_3, fg=ui.TEXT,
                     insertbackground=ui.TEXT, relief="flat", bd=0, highlightthickness=1,
                     highlightbackground=ui.BORDER, highlightcolor=ui.ACCENT)
    entry.pack(side="left", fill="x", expand=True, ipady=7)
    def choose() -> None:
        value = filedialog.askopenfilename(parent=dialog, title="选择 Torrent", filetypes=(("Torrent", "*.torrent"),))
        if value: source.set(value)
    choose_btn = ui.ActionButton(row, text="选择文件", command=choose, kind="ghost", compact=True)
    choose_btn.pack(side="right", padx=(8, 0))

    ui._label(tab, variable=status, size=9, weight="bold").pack(anchor="w", pady=(16, 0))
    ttk.Progressbar(tab, variable=pct, maximum=100, mode="determinate").pack(fill="x", pady=(8, 8))
    ui._label(tab, variable=detail, size=7, color=ui.MUTED, wraplength=760, justify="left").pack(anchor="w")
    actions = tk.Frame(tab, bg=ui.PANEL); actions.pack(fill="x", pady=(16, 0))
    start_btn = ui.ActionButton(actions, text="开始下载", command=lambda: None, kind="secondary", compact=True)
    pause_btn = ui.ActionButton(actions, text="暂停", command=lambda: None, kind="ghost", compact=True)
    resume_btn = ui.ActionButton(actions, text="继续", command=lambda: None, kind="ghost", compact=True)
    retry_btn = ui.ActionButton(actions, text="重试", command=lambda: None, kind="ghost", compact=True)
    cancel_btn = ui.ActionButton(actions, text="取消", command=lambda: None, kind="ghost", compact=True)
    start_btn.pack(side="left"); pause_btn.pack(side="left", padx=(8,0)); resume_btn.pack(side="left", padx=(8,0)); retry_btn.pack(side="left", padx=(8,0)); cancel_btn.pack(side="right")

    def session(): return getattr(window, "_galaxy_aria2_torrent_session", None)
    def render(s: Aria2TransferSnapshot) -> None:
        def apply() -> None:
            try:
                if not dialog.winfo_exists(): return
                a, b = torrent_snapshot_text(s); status.set(a); detail.set(b); pct.set(float(s.progress.percent))
                locked = s.state in _ACTIVE or s.state == "paused"
                entry.configure(state="disabled" if locked else "normal"); _enabled(choose_btn, not locked)
                _enabled(start_btn, s.state in {"cancelled", "completed", "failed"} or (s.state == "queued" and s.attempt == 0))
                _enabled(pause_btn, s.state in {"running", "retrying"}); _enabled(resume_btn, s.state == "paused")
                _enabled(retry_btn, s.state == "failed"); _enabled(cancel_btn, s.state not in {"cancelled", "completed", "failed"})
            except tk.TclError: pass
        try: dialog.after(0, apply)
        except tk.TclError: pass
    dialog._galaxy_aria2_render = render

    def start() -> None:
        value = source.get().strip()
        if not value: status.set("请输入 Magnet 链接或选择 .torrent 文件"); return
        old = session()
        if old is not None and old.active: status.set("已有 Torrent 任务正在运行"); return
        try:
            new = start_torrent_transfer(engine_module, value, on_update=render, max_attempts=3)
            window._galaxy_aria2_torrent_session = new; new.start()
        except Exception as exc: status.set("启动失败"); detail.set(str(exc)[:240])
    def pause() -> None:
        s = session(); s.pause() if s is not None else None
    def resume() -> None:
        s = session()
        if s is not None: s.set_listener(render); s.resume()
    def retry() -> None:
        s = session()
        if s is not None: s.set_listener(render); s.retry()
    def cancel() -> None:
        s = session(); s.cancel() if s is not None else None
    start_btn.configure(command=start); pause_btn.configure(command=pause); resume_btn.configure(command=resume); retry_btn.configure(command=retry); cancel_btn.configure(command=cancel)
    entry.bind("<Return>", lambda _event: start())
    old = session()
    if old is not None:
        try: source.set(str(old.options.source))
        except Exception: pass
        old.set_listener(render); render(old.snapshot())
    else:
        for button in (pause_btn, resume_btn, retry_btn, cancel_btn): _enabled(button, False)
    dialog._galaxy_aria2_tab_installed = True


def install_desktop_aria2_transfer_presenter(engine_module, legacy_module) -> None:
    if getattr(legacy_module, "_galaxy_aria2_dialog_patch_installed", False): return
    original = legacy_module._show_transfer_center
    def show(window, module=engine_module) -> None:
        original(window, module)
        dialog = getattr(window, "_transfer_center_window", None)
        if dialog is not None:
            try: _install_torrent_tab(window, dialog, module)
            except tk.TclError: pass
    legacy_module._show_transfer_center = show
    legacy_module._galaxy_aria2_dialog_patch_installed = True


def run_desktop_aria2_transfer_self_test() -> None:
    snapshot = Aria2TransferSnapshot("running", 2, 3, Aria2Progress(37, "5.0MiB", "12s", 16), Path("downloads/torrents"))
    primary, detail = torrent_snapshot_text(snapshot)
    assert primary == "下载中 · 37%" and "5.0MiB/s" in detail and "剩余 12s" in detail and "连接 16" in detail and "尝试 2/3" in detail
