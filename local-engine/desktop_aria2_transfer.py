from __future__ import annotations

"""Native Tk lifecycle controls for Galaxy Torrent/aria2 transfers."""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import desktop_ui as ui
from aria2_file_selection import selected_files_for
from aria2_task_provider import register_aria2_session
from aria2_transfer import Aria2Progress, Aria2TransferSnapshot
from desktop_design_tokens import LAYOUT
from transfer_center import preview_torrent_metadata, start_torrent_transfer

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


def _format_bytes(value: int) -> str:
    size = float(max(0, int(value)))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


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
    detail = tk.StringVar(value="aria2c 使用断点续传；关闭程序后任务会进入可恢复状态，不会静默重新下载。")
    metadata_status = tk.StringVar(value="本地 .torrent、HTTPS torrent 和 Magnet 都可读取文件列表并选择下载项。")
    pct = tk.DoubleVar(value=0.0)
    metadata_state = {"source": "", "local_source": "", "loading": False}

    ui._label(tab, "Torrent / Magnet", size=11, weight="bold").pack(anchor="w")
    ui._label(
        tab,
        "支持 BTIH Magnet、HTTPS .torrent 地址或本地 .torrent 文件；读取文件列表后可逐文件选择，暂停会保留 aria2 断点。",
        size=7, color=ui.SUBTLE, wraplength=760, justify="left",
    ).pack(anchor="w", pady=(4, 12))

    row = tk.Frame(tab, bg=ui.PANEL); row.pack(fill="x")
    entry = tk.Entry(
        row, textvariable=source, font=("Segoe UI", 10), bg=ui.PANEL_3, fg=ui.TEXT,
        insertbackground=ui.TEXT, relief="flat", bd=0, highlightthickness=1,
        highlightbackground=ui.BORDER, highlightcolor=ui.ACCENT,
    )
    entry.pack(side="left", fill="x", expand=True, ipady=7)

    files_card = tk.Frame(tab, bg=ui.PANEL_2, padx=10, pady=8)
    files_card.pack(fill="both", expand=True, pady=(12, 0))
    files_head = tk.Frame(files_card, bg=ui.PANEL_2); files_head.pack(fill="x")
    ui._label(files_head, "Torrent 文件", size=8, weight="bold", bg=ui.PANEL_2).pack(side="left")
    ui._label(files_card, variable=metadata_status, size=7, color=ui.MUTED, bg=ui.PANEL_2, wraplength=740, justify="left").pack(anchor="w", pady=(4, 6))

    tree = ttk.Treeview(files_card, columns=("size",), show="tree headings", selectmode="extended", height=7)
    tree.heading("#0", text="文件路径")
    tree.heading("size", text="大小")
    tree.column("#0", width=560, minwidth=240, stretch=True)
    tree.column("size", width=110, minwidth=90, stretch=False, anchor="e")
    tree.pack(fill="both", expand=True)

    select_actions = tk.Frame(files_card, bg=ui.PANEL_2); select_actions.pack(fill="x", pady=(7, 0))
    select_all_btn = ui.ActionButton(select_actions, text="全选", command=lambda: tree.selection_set(tree.get_children("")), kind="ghost", compact=True)
    clear_btn = ui.ActionButton(select_actions, text="清空选择", command=lambda: tree.selection_remove(tree.selection()), kind="ghost", compact=True)
    select_all_btn.pack(side="left")
    clear_btn.pack(side="left", padx=(6, 0))

    choose_btn = ui.ActionButton(row, text="选择文件", command=lambda: None, kind="ghost", compact=True)
    choose_btn.pack(side="right", padx=(8, 0))
    preview_btn = ui.ActionButton(row, text="读取文件列表", command=lambda: None, kind="ghost", compact=True)
    preview_btn.pack(side="right", padx=(8, 0))

    def clear_metadata(message: str | None = None) -> None:
        for item in tree.get_children(""):
            tree.delete(item)
        metadata_state["source"] = ""
        metadata_state["local_source"] = ""
        if message is not None:
            metadata_status.set(message)

    def set_preview_controls(enabled: bool) -> None:
        active = session()
        locked = bool(active and (active.active or active.state == "paused"))
        allow = enabled and not locked
        for control in (choose_btn, preview_btn, select_all_btn, clear_btn):
            _enabled(control, allow)

    def populate_metadata(wanted: str, acquired) -> None:
        if source.get().strip() != wanted:
            return
        for item in tree.get_children(""):
            tree.delete(item)
        for file in acquired.metadata.files:
            tree.insert("", "end", iid=str(file.index), text=file.path, values=(_format_bytes(file.length),))
        children = tree.get_children("")
        if children:
            tree.selection_set(children)
        metadata_state["source"] = wanted
        metadata_state["local_source"] = str(acquired.torrent_path)
        metadata_status.set(
            f"{acquired.metadata.name} · {len(acquired.metadata.files)} 个文件 · {_format_bytes(acquired.metadata.total_length)} · 默认全选，可 Ctrl/Shift 多选。"
        )

    def begin_metadata_preview(value: str | None = None) -> None:
        wanted = str(value if value is not None else source.get()).strip()
        if not wanted:
            clear_metadata("请先输入 Magnet / HTTPS .torrent 地址或选择本地 .torrent 文件。")
            return
        if metadata_state["loading"]:
            metadata_status.set("正在读取 Torrent 文件列表，请稍候。")
            return
        metadata_state["loading"] = True
        clear_metadata("正在安全读取 Torrent 元数据…")
        metadata_state["loading"] = True
        set_preview_controls(False)

        def worker() -> None:
            try:
                acquired = preview_torrent_metadata(engine_module, wanted)
                error = ""
            except Exception as exc:  # noqa: BLE001 - UI boundary
                acquired = None
                error = str(exc)[:400]

            def finish() -> None:
                metadata_state["loading"] = False
                try:
                    if not dialog.winfo_exists():
                        return
                    if source.get().strip() != wanted:
                        set_preview_controls(True)
                        return
                    if acquired is None:
                        clear_metadata(error or "读取 Torrent 文件列表失败")
                    else:
                        populate_metadata(wanted, acquired)
                    set_preview_controls(True)
                except tk.TclError:
                    pass

            try:
                dialog.after(0, finish)
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="GalaxyTorrentMetadataPreview", daemon=True).start()

    def on_source_changed(*_args) -> None:
        wanted = source.get().strip()
        if metadata_state["source"] and wanted != metadata_state["source"]:
            clear_metadata("来源已更改；请重新读取文件列表。未读取时开始下载会按全部文件处理。")

    source.trace_add("write", on_source_changed)

    def choose() -> None:
        value = filedialog.askopenfilename(parent=dialog, title="选择 Torrent", filetypes=(("Torrent", "*.torrent"),))
        if value:
            source.set(value)
            begin_metadata_preview(value)

    choose_btn.configure(command=choose)
    preview_btn.configure(command=begin_metadata_preview)

    ui._label(tab, variable=status, size=9, weight="bold").pack(anchor="w", pady=(14, 0))
    ttk.Progressbar(tab, variable=pct, maximum=100, mode="determinate").pack(fill="x", pady=(8, 8))
    ui._label(tab, variable=detail, size=7, color=ui.MUTED, wraplength=760, justify="left").pack(anchor="w")
    actions = tk.Frame(tab, bg=ui.PANEL); actions.pack(fill="x", pady=(14, 0))
    start_btn = ui.ActionButton(actions, text="开始下载", command=lambda: None, kind="secondary", compact=True)
    pause_btn = ui.ActionButton(actions, text="暂停", command=lambda: None, kind="ghost", compact=True)
    resume_btn = ui.ActionButton(actions, text="继续", command=lambda: None, kind="ghost", compact=True)
    retry_btn = ui.ActionButton(actions, text="重试", command=lambda: None, kind="ghost", compact=True)
    cancel_btn = ui.ActionButton(actions, text="取消", command=lambda: None, kind="ghost", compact=True)
    start_btn.pack(side="left"); pause_btn.pack(side="left", padx=(8,0)); resume_btn.pack(side="left", padx=(8,0)); retry_btn.pack(side="left", padx=(8,0)); cancel_btn.pack(side="right")

    def session(): return getattr(window, "_galaxy_aria2_torrent_session", None)

    def current_selection(value: str) -> tuple[int, ...]:
        if metadata_state["source"] != value or not tree.get_children(""):
            return ()
        selected = tuple(sorted(int(item) for item in tree.selection()))
        if not selected:
            raise ValueError("请至少选择一个 Torrent 文件；如需全部文件请点击“全选”。")
        return selected

    def render(s: Aria2TransferSnapshot) -> None:
        def apply() -> None:
            try:
                if not dialog.winfo_exists(): return
                a, b = torrent_snapshot_text(s); status.set(a); detail.set(b); pct.set(float(s.progress.percent))
                locked = s.state in _ACTIVE or s.state == "paused"
                entry.configure(state="disabled" if locked else "normal")
                tree.configure(selectmode="none" if locked else "extended")
                for control in (choose_btn, preview_btn, select_all_btn, clear_btn):
                    _enabled(control, not locked and not metadata_state["loading"])
                _enabled(start_btn, (not metadata_state["loading"]) and (s.state in {"cancelled", "completed", "failed"} or (s.state == "queued" and s.attempt == 0)))
                _enabled(pause_btn, s.state in {"running", "retrying"}); _enabled(resume_btn, s.state == "paused")
                _enabled(retry_btn, s.state == "failed"); _enabled(cancel_btn, s.state not in {"cancelled", "completed", "failed"})
            except tk.TclError: pass
        try: dialog.after(0, apply)
        except tk.TclError: pass
    dialog._galaxy_aria2_render = render

    def start() -> None:
        value = source.get().strip()
        if not value:
            status.set("请输入 BTIH Magnet、HTTPS .torrent 地址或选择本地 .torrent 文件")
            return
        if metadata_state["loading"]:
            status.set("正在读取 Torrent 文件列表")
            detail.set("元数据读取完成后再开始下载。")
            return
        old = session()
        if old is not None and old.active:
            status.set("已有 Torrent 任务正在运行")
            return
        try:
            selected = current_selection(value)
            actual_source = metadata_state["local_source"] if metadata_state["source"] == value and metadata_state["local_source"] else value
            new = start_torrent_transfer(engine_module, actual_source, selected_files=selected, on_update=render, max_attempts=3)
            register_aria2_session(new)
            window._galaxy_aria2_torrent_session = new
            new.start()
        except Exception as exc:
            status.set("启动失败")
            detail.set(str(exc)[:240])

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
        try:
            old_source = str(old.options.source)
            source.set(old_source)
            acquired = preview_torrent_metadata(engine_module, old_source)
            populate_metadata(old_source, acquired)
            saved = selected_files_for(old.options)
            if saved:
                tree.selection_remove(tree.selection())
                valid = [str(index) for index in saved if tree.exists(str(index))]
                if valid:
                    tree.selection_set(valid)
        except Exception:
            pass
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
    assert _format_bytes(0) == "0 B"
    assert _format_bytes(1024) == "1.0 KiB"
