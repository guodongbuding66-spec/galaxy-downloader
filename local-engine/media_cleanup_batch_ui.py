from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import desktop_extras as extras
import desktop_ui as ui
from desktop_design_tokens import LAYOUT, font
from desktop_hooks import register_after_build_ui_hook, register_before_close_hook
from media_cleanup_batch import (
    CANCELLED,
    CANCELLING,
    FAILED,
    MODE_AUTO,
    MODE_IMAGE_INPAINT,
    MODE_STATIC,
    MODE_TRACKED_VIDEO,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    MediaCleanupBatchCenter,
    MediaCleanupBatchError,
    MediaCleanupBatchFullError,
)

_MODE_LABELS = {
    MODE_AUTO: "自动",
    MODE_STATIC: "固定区域",
    MODE_IMAGE_INPAINT: "图片 Inpainting",
    MODE_TRACKED_VIDEO: "移动水印跟踪",
}
_STATE_LABELS = {
    QUEUED: "等待",
    RUNNING: "处理中",
    CANCELLING: "正在取消",
    SUCCEEDED: "完成",
    FAILED: "失败",
    CANCELLED: "已取消",
}


def _parse_nonnegative_float(value: object, *, name: str) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise MediaCleanupBatchError(f"{name} 必须是数字") from exc
    if parsed < 0:
        raise MediaCleanupBatchError(f"{name} 不能小于 0")
    return parsed


def _parse_positive_int(value: object, *, name: str) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise MediaCleanupBatchError(f"{name} 必须是整数") from exc
    if parsed < 1:
        raise MediaCleanupBatchError(f"{name} 必须大于 0")
    return parsed


def build_batch_specs(
    paths: list[str] | tuple[str, ...],
    *,
    mode: str,
    x: object,
    y: object,
    width: object,
    height: object,
    anchor_seconds: object = 0,
) -> list[dict[str, Any]]:
    clean_paths = [str(Path(value).expanduser()) for value in paths if str(value).strip()]
    if not clean_paths:
        raise MediaCleanupBatchError("请至少选择一个图片或视频文件")
    clean_mode = str(mode or MODE_AUTO).strip().lower()
    if clean_mode not in _MODE_LABELS:
        raise MediaCleanupBatchError("批处理模式无效")
    region = {
        "x": int(_parse_nonnegative_float(x, name="X")),
        "y": int(_parse_nonnegative_float(y, name="Y")),
        "width": _parse_positive_int(width, name="宽度"),
        "height": _parse_positive_int(height, name="高度"),
    }
    anchor = _parse_nonnegative_float(anchor_seconds, name="锚点时间")
    specs: list[dict[str, Any]] = []
    for path in clean_paths:
        item: dict[str, Any] = {
            "inputPath": path,
            "mode": clean_mode,
            "regions": [dict(region)],
        }
        if clean_mode == MODE_TRACKED_VIDEO:
            item["anchorSeconds"] = anchor
        specs.append(item)
    return specs


def _center_for_window(window: Any, engine_module: Any) -> MediaCleanupBatchCenter:
    center = getattr(window, "_galaxy_media_cleanup_batch_center", None)
    if isinstance(center, MediaCleanupBatchCenter):
        return center
    ffmpeg_directory = engine_module.ffmpeg_dir()
    if ffmpeg_directory is None:
        raise MediaCleanupBatchError("当前 Local Engine 未找到 FFmpeg / FFprobe")
    center = MediaCleanupBatchCenter()
    center.start_default(Path(ffmpeg_directory))
    window._galaxy_media_cleanup_batch_center = center
    return center


def _shutdown_center(window: Any) -> None:
    center = getattr(window, "_galaxy_media_cleanup_batch_center", None)
    if not isinstance(center, MediaCleanupBatchCenter):
        return
    center.shutdown(cancel_running=True, timeout=2.0)
    window._galaxy_media_cleanup_batch_center = None


def _show_batch_center(window: Any, engine_module: Any) -> None:
    existing = getattr(window, "_media_cleanup_batch_window", None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return
        except tk.TclError:
            pass

    try:
        center = _center_for_window(window, engine_module)
    except Exception as exc:  # noqa: BLE001
        messagebox.showerror(engine_module.APP_NAME, f"无法启动批处理中心：\n{exc}", parent=window)
        return

    dialog = tk.Toplevel(window)
    window._media_cleanup_batch_window = dialog
    dialog.title("可见水印清理 · 批处理任务中心")
    dialog.geometry("1040x700")
    dialog.minsize(860, 560)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    page = int(LAYOUT["page"])
    section = int(LAYOUT["section"])
    inline = int(LAYOUT["inline"])
    micro = int(LAYOUT["micro"])
    shell = tk.Frame(dialog, bg=ui.BG, padx=page, pady=page)
    shell.pack(fill="both", expand=True)

    ui._label(shell, "批处理任务中心", size="title", weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "同一批文件可复用一个已确认的可见水印区域。任务使用现有单工 FIFO 调度器，关闭窗口不会中断任务；退出 Galaxy 时会安全取消。",
        size="body_sm",
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=960,
        justify="left",
    ).pack(anchor="w", pady=(micro, section))

    summary_var = tk.StringVar(value="等待 0 · 处理中 0 · 完成 0")
    ui._label(shell, variable=summary_var, size="body_sm", color=ui.CYAN, bg=ui.BG).pack(anchor="w")

    tree_frame = tk.Frame(shell, bg=ui.PANEL, highlightthickness=1, highlightbackground=ui.BORDER)
    tree_frame.pack(fill="both", expand=True, pady=(inline, section))
    columns = ("state", "file", "kind", "mode", "progress", "status")
    tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
    headings = {
        "state": "状态",
        "file": "文件",
        "kind": "类型",
        "mode": "模式",
        "progress": "进度",
        "status": "详情",
    }
    widths = {"state": 86, "file": 220, "kind": 70, "mode": 130, "progress": 80, "status": 300}
    for key in columns:
        tree.heading(key, text=headings[key])
        tree.column(key, width=widths[key], minwidth=60, stretch=key in {"file", "status"})
    scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    status_var = tk.StringVar(value="就绪")
    ui._label(shell, variable=status_var, size="body_sm", color=ui.SUBTLE, bg=ui.BG).pack(anchor="w")

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(inline, 0))

    row_ids: dict[str, str] = {}

    def selected_task_id() -> str:
        selected = tree.selection()
        if not selected:
            return ""
        iid = selected[0]
        return str(tree.set(iid, "file") and tree.item(iid, "tags")[0] if tree.item(iid, "tags") else "")

    def render_record(record: dict[str, Any]) -> None:
        task_id = str(record.get("id") or "")
        if not task_id:
            return
        state = str(record.get("state") or "")
        error = str(record.get("errorDetail") or "").strip()
        detail = error or str(record.get("status") or "")
        values = (
            _STATE_LABELS.get(state, state),
            str(record.get("inputName") or "—"),
            "图片" if record.get("mediaKind") == "image" else "视频",
            _MODE_LABELS.get(str(record.get("mode") or ""), str(record.get("mode") or "—")),
            f"{float(record.get('progress') or 0):.0f}%",
            detail[:240],
        )
        iid = row_ids.get(task_id)
        if iid and tree.exists(iid):
            tree.item(iid, values=values, tags=(task_id, state))
        else:
            row_ids[task_id] = tree.insert("", "end", values=values, tags=(task_id, state))

    def refresh() -> None:
        if not dialog.winfo_exists():
            return
        snapshot = center.snapshot()
        records = list(snapshot["active"]) + list(snapshot["waiting"]) + list(snapshot["completed"])
        live_ids = set()
        for record in records:
            task_id = str(record.get("id") or "")
            live_ids.add(task_id)
            render_record(record)
        for task_id, iid in list(row_ids.items()):
            if task_id not in live_ids:
                if tree.exists(iid):
                    tree.delete(iid)
                row_ids.pop(task_id, None)
        summary_var.set(
            f"等待 {snapshot['waitingCount']} · 处理中 {snapshot['activeCount']} · "
            f"已结束 {len(snapshot['completed'])} · 并发 {snapshot['concurrencyLimit']}"
        )
        try:
            dialog.after(500, refresh)
        except tk.TclError:
            pass

    def add_batch() -> None:
        files = filedialog.askopenfilenames(
            parent=dialog,
            title="选择要批量清理的图片/视频",
            filetypes=(("媒体文件", "*.png *.jpg *.jpeg *.webp *.mp4 *.mkv *.mov *.webm"), ("所有文件", "*.*")),
        )
        if not files:
            return

        form = tk.Toplevel(dialog)
        form.title("批处理参数")
        form.geometry("520x390")
        form.resizable(False, False)
        form.configure(bg=ui.BG)
        form.transient(dialog)
        form.grab_set()
        body = tk.Frame(form, bg=ui.BG, padx=page, pady=page)
        body.pack(fill="both", expand=True)
        ui._label(body, f"已选择 {len(files)} 个文件", size="title_sm", weight="bold", bg=ui.BG).pack(anchor="w")
        ui._label(
            body,
            "坐标使用原始媒体像素。移动水印跟踪要求视频且仅一个区域；Auto 会对图片使用 Inpainting，对视频使用固定区域。",
            size="body_sm",
            color=ui.MUTED,
            bg=ui.BG,
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(micro, section))

        mode_var = tk.StringVar(value=MODE_AUTO)
        x_var = tk.StringVar(value="0")
        y_var = tk.StringVar(value="0")
        w_var = tk.StringVar(value="160")
        h_var = tk.StringVar(value="80")
        anchor_var = tk.StringVar(value="0")

        def field(label: str, variable: tk.StringVar, row: int) -> None:
            ui._label(body, label, size="body_sm", color=ui.SUBTLE, bg=ui.BG).grid(row=row, column=0, sticky="w", pady=(0, inline))
            entry = tk.Entry(
                body,
                textvariable=variable,
                font=font("body"),
                bg=ui.PANEL_2,
                fg=ui.TEXT,
                insertbackground=ui.TEXT,
                relief="flat",
                highlightthickness=1,
                highlightbackground=ui.BORDER,
                highlightcolor=ui.ACCENT,
            )
            entry.grid(row=row, column=1, sticky="ew", padx=(inline, 0), pady=(0, inline), ipady=micro)

        ui._label(body, "模式", size="body_sm", color=ui.SUBTLE, bg=ui.BG).grid(row=0, column=0, sticky="w", pady=(0, inline))
        mode_box = ttk.Combobox(
            body,
            textvariable=mode_var,
            values=(MODE_AUTO, MODE_STATIC, MODE_IMAGE_INPAINT, MODE_TRACKED_VIDEO),
            state="readonly",
        )
        mode_box.grid(row=0, column=1, sticky="ew", padx=(inline, 0), pady=(0, inline), ipady=micro)
        field("区域 X", x_var, 1)
        field("区域 Y", y_var, 2)
        field("区域宽度", w_var, 3)
        field("区域高度", h_var, 4)
        field("跟踪锚点（秒）", anchor_var, 5)
        body.grid_columnconfigure(1, weight=1)

        actions = tk.Frame(body, bg=ui.BG)
        actions.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(section, 0))

        def submit() -> None:
            try:
                specs = build_batch_specs(
                    list(files),
                    mode=mode_var.get(),
                    x=x_var.get(),
                    y=y_var.get(),
                    width=w_var.get(),
                    height=h_var.get(),
                    anchor_seconds=anchor_var.get(),
                )
                accepted = center.submit_many(specs)
            except (MediaCleanupBatchError, MediaCleanupBatchFullError, OSError, ValueError) as exc:
                messagebox.showerror(engine_module.APP_NAME, str(exc), parent=form)
                return
            status_var.set(f"已加入 {len(accepted)} 个任务")
            form.destroy()
            refresh()

        ui.ActionButton(actions, text="取消", command=form.destroy, kind="ghost", compact=True).pack(side="right")
        ui.ActionButton(actions, text="加入队列", command=submit, kind="secondary", compact=True).pack(side="right", padx=(0, inline))

    def cancel_selected() -> None:
        task_id = selected_task_id()
        if not task_id:
            status_var.set("请先选择一个任务")
            return
        result = center.cancel(task_id)
        status_var.set("已请求取消" if result.get("cancelled") else str(result.get("code") or result.get("state") or "无法取消"))
        refresh()

    def clear_waiting() -> None:
        count = center.clear_waiting()
        status_var.set(f"已取消 {count} 个等待任务")
        refresh()

    def open_result() -> None:
        task_id = selected_task_id()
        if not task_id:
            status_var.set("请先选择一个任务")
            return
        path = center.result_path(task_id)
        if path is None or not path.exists():
            status_var.set("所选任务暂无可打开的结果")
            return
        try:
            extras._open_path(path, select_file=True)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, f"无法打开结果：\n{exc}", parent=dialog)

    ui.ActionButton(footer, text="添加批处理", command=add_batch, kind="primary").pack(side="left")
    ui.ActionButton(footer, text="取消所选", command=cancel_selected, kind="ghost", compact=True).pack(side="left", padx=(inline, 0))
    ui.ActionButton(footer, text="清空等待", command=clear_waiting, kind="ghost", compact=True).pack(side="left", padx=(inline, 0))
    ui.ActionButton(footer, text="打开结果", command=open_result, kind="secondary", compact=True).pack(side="right")

    def close_dialog() -> None:
        window._media_cleanup_batch_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close_dialog)
    refresh()


def _add_batch_entry(window: Any) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_media_cleanup_batch_entry_built", False):
        return
    import engine

    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(int(LAYOUT["content"]), 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, int(LAYOUT["inline"])))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "可见水印清理批处理", size="body_sm", weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        text,
        "最多 32 项/次 · FIFO · 实时进度 · 可取消",
        size="caption",
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(int(LAYOUT["micro"]), 0))
    ui.ActionButton(
        card,
        text="打开批处理中心",
        command=lambda: _show_batch_center(window, engine),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_media_cleanup_batch_entry_built = True


def install_media_cleanup_batch_ui(window_cls: type) -> type:
    if getattr(window_cls, "_galaxy_media_cleanup_batch_ui_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "media-cleanup-batch-ui",
        _add_batch_entry,
        order=66,
    )
    register_before_close_hook(
        window_cls,
        "media-cleanup-batch-ui",
        _shutdown_center,
        order=66,
    )
    window_cls._galaxy_media_cleanup_batch_ui_installed = True
    return window_cls


def run_media_cleanup_batch_ui_self_test() -> None:
    specs = build_batch_specs(
        ("/tmp/example-a.png", "/tmp/example-b.mp4"),
        mode=MODE_AUTO,
        x="12",
        y="20",
        width="160",
        height="80",
        anchor_seconds="0",
    )
    assert len(specs) == 2
    assert specs[0]["regions"] == [{"x": 12, "y": 20, "width": 160, "height": 80}]
    assert specs[1]["mode"] == MODE_AUTO
    tracked = build_batch_specs(
        ("/tmp/example.mp4",),
        mode=MODE_TRACKED_VIDEO,
        x=1,
        y=2,
        width=3,
        height=4,
        anchor_seconds="2.5",
    )
    assert tracked[0]["anchorSeconds"] == 2.5
    try:
        build_batch_specs(("/tmp/example.mp4",), mode=MODE_AUTO, x=-1, y=0, width=1, height=1)
    except MediaCleanupBatchError:
        pass
    else:
        raise AssertionError("negative coordinates must fail closed")


if __name__ == "__main__":
    run_media_cleanup_batch_ui_self_test()
    print("Media cleanup batch UI self-test passed")
