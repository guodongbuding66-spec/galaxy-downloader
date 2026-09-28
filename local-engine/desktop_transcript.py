from __future__ import annotations

import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import desktop_extras as extras
import desktop_ui as ui
from ai_workspace import transcript_path
from desktop_hooks import register_after_build_ui_hook, register_desktop_presenter, show_desktop_presenter
from media_library import list_media_items, sync_media_library
from transcript_export import EXPORT_FORMATS, TranscriptExportError, export_transcript_to_path
from transcript_workspace import TranscriptWorkspaceError, index_transcript, search_transcript

FORMAT_LABELS = {
    "txt": "TXT",
    "md": "Markdown",
    "srt": "SRT",
    "vtt": "VTT",
    "json": "JSON",
    "csv": "CSV",
}
FORMAT_BY_LABEL = {label: name for name, label in FORMAT_LABELS.items()}
MEDIA_LABELS = {"video": "视频", "audio": "音频"}
_SAFE_FILE_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _window_exists(window: tk.Misc | None) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def _format_bytes(value: object) -> str:
    try:
        size = max(0, int(value or 0))
    except (TypeError, ValueError):
        return "—"
    amount = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{size} B"
        amount /= 1024
    return "—"


def _display_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("fileName") or item.get("id") or "未命名媒体").strip()


def _suggest_export_name(item: dict[str, Any], format_name: object) -> str:
    selected = str(format_name or "txt").strip().lower()
    if selected not in EXPORT_FORMATS:
        selected = "txt"
    raw = _display_title(item)
    file_name = str(item.get("fileName") or "").strip()
    if file_name:
        raw = Path(file_name).stem or raw
    clean = _SAFE_FILE_CHARS_RE.sub("-", raw).strip(" .-")[:80] or "transcript"
    return f"{clean}.{selected}"


def _has_transcript(engine_module, media_id: object) -> bool:
    clean = str(media_id or "").strip().lower()
    if not clean:
        return False
    try:
        source = transcript_path(engine_module, clean)
        return source.is_file() and not source.is_symlink() and source.stat().st_size > 0
    except (OSError, RuntimeError, ValueError):
        return False



def _format_timestamp(value: object) -> str:
    try:
        seconds = max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        seconds = 0.0
    total_ms = int(round(seconds * 1000.0))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    if hours:
        return f"{hours:02}:{minutes:02}:{whole_seconds:02}.{milliseconds:03}"
    return f"{minutes:02}:{whole_seconds:02}.{milliseconds:03}"


def _parse_filter_seconds(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 1:
            seconds = float(parts[0])
        elif len(parts) == 2:
            minutes = int(parts[0])
            tail = float(parts[1])
            if minutes < 0 or not 0 <= tail < 60:
                raise ValueError
            seconds = minutes * 60 + tail
        elif len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            tail = float(parts[2])
            if hours < 0 or not 0 <= minutes < 60 or not 0 <= tail < 60:
                raise ValueError
            seconds = hours * 3600 + minutes * 60 + tail
        else:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("时间请输入秒数、MM:SS 或 HH:MM:SS") from exc
    if seconds < 0:
        raise ValueError("时间不能为负数")
    return seconds


def _highlight_chunks(text: object, ranges: object) -> list[tuple[str, bool]]:
    value = str(text or "")
    clean_ranges: list[tuple[int, int]] = []
    for raw in ranges if isinstance(ranges, list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            start = max(0, int(raw.get("start", 0)))
            end = min(len(value), int(raw.get("end", 0)))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        if clean_ranges and start < clean_ranges[-1][1]:
            start = clean_ranges[-1][1]
        if end > start:
            clean_ranges.append((start, end))

    chunks: list[tuple[str, bool]] = []
    cursor = 0
    for start, end in clean_ranges:
        if start > cursor:
            chunks.append((value[cursor:start], False))
        chunks.append((value[start:end], True))
        cursor = end
    if cursor < len(value):
        chunks.append((value[cursor:], False))
    if not chunks and value:
        chunks.append((value, False))
    return chunks

def _show_transcript_workspace(window, engine_module) -> None:
    existing = getattr(window, "_transcript_workspace_window", None)
    if _window_exists(existing):
        existing.deiconify()
        existing.lift()
        return

    dialog = tk.Toplevel(window)
    window._transcript_workspace_window = dialog
    dialog.title("Transcript · Galaxy Local Engine")
    dialog.geometry("1040x790")
    dialog.minsize(900, 650)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "Transcript", size="title", weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "选择已经生成字幕的本地媒体，在当前 Transcript 内按全文、Speaker 和时间范围搜索，并可导出 TXT、Markdown、SRT、VTT、JSON 或 CSV。",
        size="body_sm",
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=820,
        justify="left",
    ).pack(anchor="w", pady=(4, 12))

    status_var = tk.StringVar(value="正在读取媒体库…")
    ui._label(shell, variable=status_var, size="body_sm", color=ui.MUTED, bg=ui.BG).pack(anchor="w", pady=(0, 10))

    card = tk.Frame(shell, bg=ui.PANEL, padx=12, pady=12, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True)
    style = ttk.Style(dialog)
    style.configure(
        "Galaxy.Transcript.Treeview",
        background=ui.PANEL,
        fieldbackground=ui.PANEL,
        foreground=ui.TEXT,
        rowheight=30,
        borderwidth=0,
    )
    style.configure(
        "Galaxy.Transcript.Treeview.Heading",
        background=ui.PANEL_2,
        foreground=ui.MUTED,
        relief="flat",
        font=(ui.FONT_FAMILY, ui.TYPE["body_sm"], "bold"),
    )
    style.map(
        "Galaxy.Transcript.Treeview",
        background=[("selected", ui.PANEL_3)],
        foreground=[("selected", ui.TEXT)],
    )

    columns = ("type", "transcript", "title")
    tree = ttk.Treeview(
        card,
        columns=columns,
        show="headings",
        style="Galaxy.Transcript.Treeview",
        selectmode="browse",
    )
    tree.heading("type", text="类型")
    tree.heading("transcript", text="Transcript")
    tree.heading("title", text="标题 / 文件名")
    tree.column("type", width=72, minwidth=60, stretch=False)
    tree.column("transcript", width=110, minwidth=100, stretch=False)
    tree.column("title", width=650, minwidth=260, stretch=True)
    scrollbar = ttk.Scrollbar(card, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)

    search_card = tk.Frame(
        shell,
        bg=ui.PANEL,
        padx=12,
        pady=12,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    search_card.pack(fill="x", pady=(10, 0))
    ui._label(search_card, "Transcript Search", size="title_sm", weight="bold").pack(anchor="w")
    ui._label(
        search_card,
        "搜索范围始终是当前选中的媒体；搜索前会刷新该 Transcript 的本地索引。",
        size="body_sm",
        color=ui.MUTED,
    ).pack(anchor="w", pady=(2, 8))

    search_query_var = tk.StringVar()
    speaker_var = tk.StringVar()
    start_var = tk.StringVar()
    end_var = tk.StringVar()
    search_status_var = tk.StringVar(value="选择带 Transcript 的媒体后即可搜索。")

    query_row = tk.Frame(search_card, bg=ui.PANEL)
    query_row.pack(fill="x")
    ui._label(query_row, "全文", size="body_sm", color=ui.MUTED).pack(side="left")
    query_entry = ui._entry(query_row, search_query_var, 48)
    query_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))

    filter_row = tk.Frame(search_card, bg=ui.PANEL)
    filter_row.pack(fill="x", pady=(8, 0))
    ui._label(filter_row, "Speaker", size="body_sm", color=ui.MUTED).pack(side="left")
    speaker_entry = ui._entry(filter_row, speaker_var, 14)
    speaker_entry.pack(side="left", padx=(6, 12))
    ui._label(filter_row, "开始", size="body_sm", color=ui.MUTED).pack(side="left")
    start_entry = ui._entry(filter_row, start_var, 10)
    start_entry.pack(side="left", padx=(6, 4))
    ui._label(filter_row, "结束", size="body_sm", color=ui.MUTED).pack(side="left", padx=(8, 0))
    end_entry = ui._entry(filter_row, end_var, 10)
    end_entry.pack(side="left", padx=(6, 8))
    ui._label(
        filter_row,
        "支持秒数 / MM:SS / HH:MM:SS",
        size="caption",
        color=ui.SUBTLE,
    ).pack(side="left", padx=(4, 0))

    result_frame = tk.Frame(search_card, bg=ui.PANEL)
    result_frame.pack(fill="x", pady=(8, 0))
    search_result = tk.Text(
        result_frame,
        height=7,
        wrap="word",
        bg=ui.PANEL_2,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        borderwidth=0,
        padx=10,
        pady=8,
        font=(ui.FONT_FAMILY, ui.TYPE["body_sm"]),
        takefocus=True,
        state="disabled",
    )
    search_scroll = ttk.Scrollbar(result_frame, orient="vertical", command=search_result.yview)
    search_result.configure(yscrollcommand=search_scroll.set)
    search_scroll.pack(side="right", fill="y")
    search_result.pack(side="left", fill="x", expand=True)
    search_result.tag_configure("meta", foreground=ui.MUTED)
    search_result.tag_configure("match", foreground=ui.ACCENT, background=ui.PANEL_3)

    search_footer = tk.Frame(search_card, bg=ui.PANEL)
    search_footer.pack(fill="x", pady=(8, 0))
    ui._label(
        search_footer,
        variable=search_status_var,
        size="body_sm",
        color=ui.MUTED,
    ).pack(side="left")
    search_button = ui.ActionButton(
        query_row,
        text="搜索",
        command=lambda: run_search(),
        kind="primary",
        compact=True,
    )
    search_button.pack(side="right")
    search_button.state(["disabled"])
    ui.ActionButton(
        search_footer,
        text="清除筛选",
        command=lambda: clear_search(),
        kind="ghost",
        compact=True,
    ).pack(side="right")

    controls = tk.Frame(
        shell,
        bg=ui.PANEL,
        padx=12,
        pady=12,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    controls.pack(fill="x", pady=(10, 0))
    format_var = tk.StringVar(value=FORMAT_LABELS["txt"])
    name_var = tk.StringVar(value="transcript.txt")
    include_speaker_var = tk.BooleanVar(value=True)

    ui._label(controls, "格式", size="body_sm", color=ui.MUTED).grid(row=0, column=0, sticky="w")
    format_box = ttk.Combobox(
        controls,
        textvariable=format_var,
        values=tuple(FORMAT_LABELS.values()),
        state="readonly",
        width=12,
        style="Galaxy.TCombobox",
    )
    format_box.grid(row=1, column=0, sticky="w", pady=(4, 0))

    ui._label(controls, "文件名", size="body_sm", color=ui.MUTED).grid(
        row=0,
        column=1,
        sticky="w",
        padx=(12, 0),
    )
    name_entry = ui._entry(controls, name_var, 42)
    name_entry.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(4, 0))
    controls.grid_columnconfigure(1, weight=1)

    include_check = ui._check(controls, "包含 Speaker 标签", include_speaker_var)
    include_check.grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(4, 0))

    item_by_iid: dict[str, dict[str, Any]] = {}
    last_export: dict[str, Path | None] = {"path": None}
    export_button: ui.ActionButton | None = None
    open_button: ui.ActionButton | None = None
    search_generation = {"value": 0}

    def selected() -> dict[str, Any] | None:
        selection = tree.selection()
        return item_by_iid.get(selection[0]) if selection else None

    def selected_format() -> str:
        return FORMAT_BY_LABEL.get(format_var.get(), "txt")

    def selection_changed(_event=None) -> None:
        item = selected()
        search_generation["value"] += 1
        render_search_results([])
        if item is None:
            if export_button is not None:
                export_button.state(["disabled"])
            search_button.state(["disabled"])
            search_status_var.set("选择带 Transcript 的媒体后即可搜索。")
            return
        ready = bool(item.get("transcriptAvailable"))
        name_var.set(_suggest_export_name(item, selected_format()))
        if export_button is not None:
            export_button.state(["!disabled"] if ready else ["disabled"])
        search_button.state(["!disabled"] if ready else ["disabled"])
        search_status_var.set(
            "可搜索当前 Transcript。"
            if ready
            else "当前媒体尚未生成 Transcript。"
        )
        status_var.set(
            "可导出 Transcript。"
            if ready
            else "所选媒体尚未生成 Transcript；请先在 ASR / AI 工作台生成字幕。"
        )

    def render_search_results(rows: list[dict[str, Any]]) -> None:
        search_result.configure(state="normal")
        search_result.delete("1.0", "end")
        for row in rows:
            timestamp = _format_timestamp(row.get("startSeconds"))
            speaker = str(row.get("speaker") or "").strip()
            meta = f"{timestamp}"
            if speaker:
                meta += f" · {speaker}"
            search_result.insert("end", meta + "\n", "meta")
            for chunk, matched in _highlight_chunks(row.get("text"), row.get("highlights")):
                search_result.insert("end", chunk, "match" if matched else ())
            search_result.insert("end", "\n\n")
        search_result.configure(state="disabled")

    def clear_search() -> None:
        search_generation["value"] += 1
        search_query_var.set("")
        speaker_var.set("")
        start_var.set("")
        end_var.set("")
        render_search_results([])
        item = selected()
        search_status_var.set(
            "可搜索当前 Transcript。"
            if item and item.get("transcriptAvailable")
            else "选择带 Transcript 的媒体后即可搜索。"
        )

    def run_search() -> None:
        item = selected()
        if not item or not item.get("transcriptAvailable"):
            search_status_var.set("请先选择一个已经生成 Transcript 的媒体。")
            return
        try:
            start_seconds = _parse_filter_seconds(start_var.get())
            end_seconds = _parse_filter_seconds(end_var.get())
        except ValueError as exc:
            search_status_var.set(str(exc))
            return
        if start_seconds is not None and end_seconds is not None and end_seconds < start_seconds:
            search_status_var.set("结束时间不能早于开始时间。")
            return

        media_id = str(item.get("id") or "")
        query = search_query_var.get()
        speaker = speaker_var.get()
        search_generation["value"] += 1
        generation = search_generation["value"]
        search_button.state(["disabled"])
        search_status_var.set("正在刷新索引并搜索…")

        def finish(rows: list[dict[str, Any]] | None, error: str = "") -> None:
            if not _window_exists(dialog) or generation != search_generation["value"]:
                return
            current = selected()
            if not current or str(current.get("id") or "") != media_id:
                return
            search_button.state(["!disabled"])
            if error:
                render_search_results([])
                search_status_var.set(error)
                return
            result_rows = rows or []
            render_search_results(result_rows)
            if result_rows:
                search_status_var.set(f"找到 {len(result_rows)} 个匹配片段；匹配文本已高亮。")
            else:
                search_status_var.set("当前 Transcript 中没有匹配片段。")

        def worker() -> None:
            try:
                count = index_transcript(engine_module, media_id)
                if count <= 0:
                    raise TranscriptWorkspaceError("Transcript 尚未建立可搜索的索引")
                rows = search_transcript(
                    engine_module,
                    query,
                    media_id=media_id,
                    speaker=speaker,
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    limit=100,
                )
                dialog.after(0, lambda: finish(rows))
            except (TranscriptWorkspaceError, OSError, RuntimeError, ValueError) as exc:
                dialog.after(0, lambda exc=exc: finish(None, f"Transcript 搜索失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def format_changed(_event=None) -> None:
        item = selected()
        if item:
            name_var.set(_suggest_export_name(item, selected_format()))

    def refresh(*_args, sync: bool = False) -> None:
        current = selected()
        selected_id = str(current.get("id") or "") if current else ""
        if sync:
            try:
                sync_media_library(engine_module)
            except Exception as exc:  # noqa: BLE001
                status_var.set(f"媒体库同步失败：{exc}")
        try:
            rows = [
                item
                for item in list_media_items(engine_module, limit=500)
                if item.get("available") and item.get("mediaType") in {"video", "audio"}
            ]
        except Exception as exc:  # noqa: BLE001
            rows = []
            status_var.set(f"媒体库不可用：{exc}")

        for iid in tree.get_children():
            tree.delete(iid)
        item_by_iid.clear()
        transcript_count = 0
        for index, item in enumerate(rows):
            media_id = str(item.get("id") or "")
            transcript_ready = _has_transcript(engine_module, media_id)
            transcript_count += int(transcript_ready)
            enriched = {**item, "transcriptAvailable": transcript_ready}
            iid = str(index)
            item_by_iid[iid] = enriched
            tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    MEDIA_LABELS.get(str(item.get("mediaType") or ""), "其他"),
                    "可导出" if transcript_ready else "未生成",
                    _display_title(item),
                ),
            )

        if selected_id:
            for iid, item in item_by_iid.items():
                if str(item.get("id") or "") == selected_id:
                    tree.selection_set(iid)
                    break
        if not tree.selection() and tree.get_children():
            tree.selection_set(tree.get_children()[0])
        if not rows:
            status_var.set("媒体库中没有可用的视频或音频。")
        else:
            status_var.set(f"共 {len(rows)} 个本地媒体 · {transcript_count} 个 Transcript 可导出")
        selection_changed()

    def finish_export(result_path: Path | None, message: str, *, error: bool = False) -> None:
        if not _window_exists(dialog):
            return
        status_var.set(message)
        if export_button is not None:
            item = selected()
            export_button.state(
                ["!disabled"]
                if item and item.get("transcriptAvailable")
                else ["disabled"]
            )
        if result_path is not None:
            last_export["path"] = result_path
            if open_button is not None:
                open_button.state(["!disabled"])
        if error:
            messagebox.showerror(engine_module.APP_NAME, message, parent=dialog)

    def export_selected() -> None:
        item = selected()
        if not item or not item.get("transcriptAvailable"):
            messagebox.showinfo(
                engine_module.APP_NAME,
                "请选择一个已经生成 Transcript 的媒体。",
                parent=dialog,
            )
            return
        format_name = selected_format()
        requested_name = name_var.get().strip() or _suggest_export_name(item, format_name)
        if not requested_name.lower().endswith(f".{format_name}"):
            requested_name = f"{Path(requested_name).stem}.{format_name}"
        target = filedialog.asksaveasfilename(
            parent=dialog,
            title="导出 Transcript",
            initialdir=str(engine_module.default_download_dir()),
            initialfile=requested_name,
            defaultextension=f".{format_name}",
            filetypes=[
                (f"{FORMAT_LABELS[format_name]} 文件", f"*.{format_name}"),
                ("所有文件", "*.*"),
            ],
        )
        if not target:
            return
        if export_button is not None:
            export_button.state(["disabled"])
        status_var.set("正在建立索引并导出…")
        media_id = str(item.get("id") or "")
        include_speaker = bool(include_speaker_var.get())

        def worker() -> None:
            try:
                count = index_transcript(engine_module, media_id)
                if count <= 0:
                    raise TranscriptWorkspaceError("Transcript 尚未建立可导出的索引")
                result = export_transcript_to_path(
                    engine_module,
                    media_id,
                    Path(target),
                    format=format_name,
                    include_speaker=include_speaker,
                )
                path = Path(result.path)
                message = (
                    f"已导出 {result.segment_count} 段 · "
                    f"{_format_bytes(result.size_bytes)} · {path.name}"
                )
                dialog.after(0, lambda: finish_export(path, message))
            except (
                TranscriptExportError,
                TranscriptWorkspaceError,
                OSError,
                RuntimeError,
                ValueError,
            ) as exc:
                dialog.after(
                    0,
                    lambda exc=exc: finish_export(
                        None,
                        f"Transcript 导出失败：{exc}",
                        error=True,
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def open_last_export() -> None:
        path = last_export["path"]
        if path is None or not path.is_file():
            status_var.set("上一次导出文件已不可用。")
            if open_button is not None:
                open_button.state(["disabled"])
            return
        try:
            extras._open_path(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                engine_module.APP_NAME,
                f"无法打开导出文件：\n{exc}",
                parent=dialog,
            )

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(10, 0))
    ui.ActionButton(
        footer,
        text="刷新",
        command=lambda: refresh(sync=True),
        kind="ghost",
        compact=True,
    ).pack(side="left")
    open_button = ui.ActionButton(
        footer,
        text="打开上次导出",
        command=open_last_export,
        kind="secondary",
        compact=True,
    )
    open_button.pack(side="right")
    open_button.state(["disabled"])
    export_button = ui.ActionButton(
        footer,
        text="导出为…",
        command=export_selected,
        kind="primary",
        compact=True,
    )
    export_button.pack(side="right", padx=(0, 8))
    export_button.state(["disabled"])

    tree.bind("<<TreeviewSelect>>", selection_changed)
    format_box.bind("<<ComboboxSelected>>", format_changed)
    query_entry.bind("<Return>", lambda _event: run_search())
    speaker_entry.bind("<Return>", lambda _event: run_search())
    start_entry.bind("<Return>", lambda _event: run_search())
    end_entry.bind("<Return>", lambda _event: run_search())

    def close() -> None:
        window._transcript_workspace_window = None
        dialog.destroy()

    dialog.bind("<Escape>", lambda _event: close())
    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh(sync=True)
    tree.focus_set()


def install_desktop_transcript(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_transcript_installed", False):
        return window_cls

    register_desktop_presenter(
        window_cls,
        "transcript",
        "desktop-transcript",
        lambda window: _show_transcript_workspace(window, engine_module),
        order=150,
    )

    def after_build_ui(window) -> None:
        queue_head = window._queue_clear_button.master
        window._transcript_button = ui.ActionButton(
            queue_head,
            text="Transcript",
            command=lambda: show_desktop_presenter(window, "transcript"),
            kind="ghost",
            compact=True,
        )
        window._transcript_button.pack(side="right", anchor="n", padx=(0, 5))

    register_after_build_ui_hook(
        window_cls,
        "desktop-transcript",
        after_build_ui,
        order=150,
    )
    window_cls._galaxy_desktop_transcript_installed = True
    engine_module._galaxy_desktop_transcript_installed = True
    return window_cls


def run_desktop_transcript_self_test() -> None:
    item = {"title": "Demo / Clip", "fileName": "Demo:Clip.mp4"}
    assert _suggest_export_name(item, "txt") == "Demo-Clip.txt"
    assert _suggest_export_name(item, "srt") == "Demo-Clip.srt"
    assert _format_bytes(1024) == "1.0 KB"
    assert FORMAT_BY_LABEL["Markdown"] == "md"
    assert set(FORMAT_LABELS) == set(EXPORT_FORMATS)


def run_desktop_transcript_search_self_test() -> None:
    assert _format_timestamp(65.25) == "01:05.250"
    assert _format_timestamp(3661.5) == "01:01:01.500"
    assert _parse_filter_seconds("90.5") == 90.5
    assert _parse_filter_seconds("01:30.5") == 90.5
    assert _parse_filter_seconds("1:02:03") == 3723.0
    assert _parse_filter_seconds("") is None
    try:
        _parse_filter_seconds("01:99")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid transcript time filter was accepted")
    assert _highlight_chunks("Hello world", [{"start": 6, "end": 11}]) == [
        ("Hello ", False),
        ("world", True),
    ]
    assert _highlight_chunks("abcdef", [{"start": 1, "end": 4}, {"start": 3, "end": 6}]) == [
        ("a", False),
        ("bcd", True),
        ("ef", True),
    ]
