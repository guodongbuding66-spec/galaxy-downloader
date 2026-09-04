from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterable

import media_cleanup_workbench as legacy
from media_cleanup import (
    CleanupRegion,
    MediaCleanupCancelled,
    MediaCleanupError,
    MediaCleanupResult,
    MediaProbe,
    _tool_path,
    _validate_input,
    cleanup_visible_overlay,
    probe_media,
)
from media_cleanup_comparison import render_cleanup_comparison
from media_cleanup_inpainting import inpaint_visible_overlay_image
from media_cleanup_suggestions import suggest_visible_overlay_for_media
from media_cleanup_tracking import (
    cleanup_tracked_visible_overlay,
    track_visible_overlay_for_video,
)

MODE_IMAGE_INPAINT = "image-inpaint"
MODE_VIDEO_STATIC = "video-static"
MODE_VIDEO_TRACKED = "video-tracked"
WORKBENCH_MODES = frozenset({MODE_IMAGE_INPAINT, MODE_VIDEO_STATIC, MODE_VIDEO_TRACKED})


def workbench_mode_values(media_kind: str) -> tuple[tuple[str, str], ...]:
    if media_kind == "image":
        return (("智能修复（Inpainting）", MODE_IMAGE_INPAINT),)
    if media_kind == "video":
        return (
            ("固定水印区域", MODE_VIDEO_STATIC),
            ("移动水印跟踪", MODE_VIDEO_TRACKED),
        )
    raise MediaCleanupError("Unsupported media kind for cleanup workbench")


def normalize_workbench_mode(media_kind: str, requested: object = "") -> str:
    allowed = {value for _label, value in workbench_mode_values(media_kind)}
    clean = str(requested or "").strip().lower()
    if clean in allowed:
        return clean
    return MODE_IMAGE_INPAINT if media_kind == "image" else MODE_VIDEO_STATIC


def validate_workbench_regions(
    media_kind: str,
    mode: str,
    regions: Iterable[CleanupRegion],
) -> tuple[CleanupRegion, ...]:
    normalized = tuple(item.validate() for item in regions)
    if not normalized:
        raise MediaCleanupError("At least one visible-overlay region is required")
    if len(normalized) > 16:
        raise MediaCleanupError("At most 16 cleanup regions are supported")
    selected_mode = normalize_workbench_mode(media_kind, mode)
    if selected_mode == MODE_VIDEO_TRACKED and len(normalized) != 1:
        raise MediaCleanupError("Moving watermark tracking requires exactly one confirmed region")
    return normalized


def execute_workbench_cleanup(
    ffmpeg_directory: Path,
    source: Path,
    probe: MediaProbe,
    regions: Iterable[CleanupRegion],
    *,
    mode: str,
    anchor_seconds: float = 0.0,
    cancel_event: threading.Event | None = None,
    progress_callback=None,
) -> MediaCleanupResult:
    normalized = validate_workbench_regions(probe.media_kind, mode, regions)
    selected_mode = normalize_workbench_mode(probe.media_kind, mode)
    if selected_mode == MODE_IMAGE_INPAINT:
        return inpaint_visible_overlay_image(
            source,
            normalized,
            cancel_event=cancel_event,
            progress_callback=progress_callback,
        )
    if selected_mode == MODE_VIDEO_TRACKED:
        ffmpeg_path = _tool_path(ffmpeg_directory, "ffmpeg")
        if progress_callback:
            progress_callback(2.0, "Tracking moving visible overlay")
        track = track_visible_overlay_for_video(
            ffmpeg_path,
            source,
            probe,
            normalized[0],
            anchor_seconds=max(0.0, float(anchor_seconds)),
        )
        if cancel_event is not None and cancel_event.is_set():
            raise MediaCleanupCancelled("Temporal visible-overlay cleanup was cancelled")
        if progress_callback:
            progress_callback(10.0, "Moving overlay track ready")

        def scaled(percent: float, message: str) -> None:
            if progress_callback:
                progress_callback(10.0 + max(0.0, min(100.0, percent)) * 0.9, message)

        return cleanup_tracked_visible_overlay(
            ffmpeg_directory,
            source,
            track,
            cancel_event=cancel_event,
            progress_callback=scaled,
        )
    return cleanup_visible_overlay(
        ffmpeg_directory,
        source,
        normalized,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
    )


def _show_workbench_v2(window: Any, engine_module: Any) -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    import desktop_extras as extras
    import desktop_ui as ui

    existing = getattr(window, "_media_cleanup_workbench", None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                return
        except tk.TclError:
            pass

    dialog = tk.Toplevel(window)
    window._media_cleanup_workbench = dialog
    dialog.title("可见水印清理 2.0 · Galaxy Local Engine")
    dialog.geometry("1080x840")
    dialog.minsize(900, 700)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    state: dict[str, Any] = {
        "source": None,
        "probe": None,
        "plan": None,
        "preview_dir": None,
        "photo": None,
        "drag_start": None,
        "drag_item": None,
        "regions": [],
        "suggestions": [],
        "suggestion_running": False,
        "result": None,
        "comparison": None,
    }

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "可见水印清理 2.0", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "图片使用像素重建；视频支持固定区域或移动水印跟踪。自动建议只提供候选框，必须确认后才会处理。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=990,
        justify="left",
    ).pack(anchor="w", pady=(4, 2))
    ui._label(
        shell,
        "仅编辑画面中可见像素；不会识别、规避或移除 SynthID / C2PA 等不可见来源或真实性标记。",
        size=7,
        color=ui.SUBTLE,
        bg=ui.BG,
        wraplength=990,
        justify="left",
    ).pack(anchor="w", pady=(0, 12))

    source_row = tk.Frame(shell, bg=ui.BG)
    source_row.pack(fill="x")
    source_var = tk.StringVar(value="尚未选择文件")
    ui._label(source_row, variable=source_var, size=8, color=ui.MUTED, bg=ui.BG).pack(
        side="left", fill="x", expand=True
    )

    controls_row = tk.Frame(shell, bg=ui.BG)
    controls_row.pack(fill="x", pady=(8, 0))
    ui._label(controls_row, "处理方式", size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    mode_var = tk.StringVar(value="")
    mode_box = ttk.Combobox(controls_row, textvariable=mode_var, state="disabled", width=20)
    mode_box.pack(side="left", padx=(8, 16))
    ui._label(controls_row, "自动建议", size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    profile_var = tk.StringVar(value="自动")
    profile_box = ttk.Combobox(
        controls_row,
        textvariable=profile_var,
        values=("自动", "豆包", "Gemini"),
        state="readonly",
        width=11,
    )
    profile_box.pack(side="left", padx=(8, 0))
    suggestion_var = tk.StringVar(value="尚未生成建议")
    ui._label(
        controls_row,
        variable=suggestion_var,
        size=8,
        color=ui.SUBTLE,
        bg=ui.BG,
    ).pack(side="left", padx=(12, 0), fill="x", expand=True)

    preview_card = tk.Frame(
        shell,
        bg=ui.PANEL,
        padx=10,
        pady=10,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    preview_card.pack(fill="both", expand=True, pady=(10, 0))
    canvas = tk.Canvas(
        preview_card,
        width=720,
        height=420,
        bg="#111827",
        bd=0,
        highlightthickness=0,
        cursor="crosshair",
    )
    canvas.pack(expand=True)
    canvas.create_text(
        360,
        210,
        text="选择图片或视频后，在这里框选可见水印区域",
        fill=ui.SUBTLE,
        font=("Segoe UI", 10),
    )

    region_var = tk.StringVar(value="已选 0 个区域")
    ui._label(shell, variable=region_var, size=8, color=ui.MUTED, bg=ui.BG).pack(
        anchor="w", pady=(9, 0)
    )
    status_row = tk.Frame(shell, bg=ui.BG)
    status_row.pack(fill="x", pady=(8, 0))
    status_var = tk.StringVar(value="就绪")
    ui._label(status_row, variable=status_var, size=8, color=ui.SUBTLE, bg=ui.BG).pack(side="left")
    progress_var = tk.DoubleVar(value=0.0)
    ttk.Progressbar(
        status_row,
        variable=progress_var,
        maximum=100,
        style="Galaxy.Horizontal.TProgressbar",
    ).pack(side="right", fill="x", expand=True, padx=(14, 0))

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))

    def busy() -> bool:
        return bool(legacy.media_cleanup_active(window) or state.get("suggestion_running"))

    def sync_buttons() -> None:
        running = legacy.media_cleanup_active(window)
        suggesting = bool(state.get("suggestion_running"))
        is_busy = running or suggesting
        has_source = isinstance(state.get("source"), Path)
        has_regions = bool(state.get("regions"))
        has_suggestions = bool(state.get("suggestions"))
        choose_button.state(["disabled"] if is_busy else ["!disabled"])
        suggestion_button.state(["!disabled"] if has_source and not is_busy else ["disabled"])
        accept_button.state(["!disabled"] if has_suggestions and not is_busy else ["disabled"])
        ignore_button.state(["!disabled"] if has_suggestions and not is_busy else ["disabled"])
        undo_button.state(["!disabled"] if has_regions and not is_busy else ["disabled"])
        clear_button.state(["!disabled"] if has_regions and not is_busy else ["disabled"])
        run_button.state(["!disabled"] if has_regions and not is_busy else ["disabled"])
        cancel_button.state(["!disabled"] if running else ["disabled"])
        output_button.state(["!disabled"] if state.get("result") is not None and not is_busy else ["disabled"])
        compare_button.state(["!disabled"] if state.get("result") is not None and not is_busy else ["disabled"])
        mode_box.configure(state="readonly" if has_source and not is_busy else "disabled")
        profile_box.configure(state="readonly" if not is_busy else "disabled")

    def set_running(value: bool) -> None:
        window._galaxy_media_cleanup_running = bool(value)
        sync_buttons()

    def clear_preview_temp() -> None:
        preview_dir = state.get("preview_dir")
        state["preview_dir"] = None
        if preview_dir:
            shutil.rmtree(str(preview_dir), ignore_errors=True)

    def clear_suggestions(message: str = "尚未生成建议") -> None:
        for item, _suggestion in state.get("suggestions", []):
            try:
                canvas.delete(item)
            except tk.TclError:
                pass
        state["suggestions"] = []
        suggestion_var.set(message)
        sync_buttons()

    def update_regions_label() -> None:
        regions = [record[1] for record in state["regions"]]
        if not regions:
            region_var.set("已选 0 个区域")
        else:
            summary = "；".join(
                f"#{index + 1} {region.x},{region.y} {region.width}×{region.height}"
                for index, region in enumerate(regions[:4])
            )
            if len(regions) > 4:
                summary += f"；另 {len(regions) - 4} 个"
            region_var.set(f"已选 {len(regions)} 个区域 · {summary}")
        sync_buttons()

    def reset_regions() -> None:
        for item, _region in state["regions"]:
            try:
                canvas.delete(item)
            except tk.TclError:
                pass
        state["regions"] = []
        drag_item = state.get("drag_item")
        if drag_item is not None:
            try:
                canvas.delete(drag_item)
            except tk.TclError:
                pass
        state["drag_item"] = None
        state["drag_start"] = None
        update_regions_label()

    def selected_mode() -> str:
        probe = state.get("probe")
        if not isinstance(probe, MediaProbe):
            return MODE_VIDEO_STATIC
        mapping = dict(workbench_mode_values(probe.media_kind))
        return mapping.get(mode_var.get(), normalize_workbench_mode(probe.media_kind))

    def configure_modes(media_kind: str) -> None:
        values = workbench_mode_values(media_kind)
        labels = tuple(label for label, _value in values)
        mode_box.configure(values=labels)
        mode_var.set(labels[0])

    def render_source(source: Path) -> None:
        ffmpeg_directory = engine_module.ffmpeg_dir()
        if ffmpeg_directory is None:
            raise MediaCleanupError("FFmpeg / FFprobe is not available in this Local Engine package")
        resolved, media_kind = _validate_input(source)
        ffmpeg_path = _tool_path(ffmpeg_directory, "ffmpeg")
        ffprobe_path = _tool_path(ffmpeg_directory, "ffprobe")
        probe = probe_media(ffprobe_path, resolved, media_kind)
        plan = legacy.build_preview_plan(probe)
        clear_preview_temp()
        preview_dir = Path(tempfile.mkdtemp(prefix="galaxy-cleanup-v2-preview-"))
        preview_path = preview_dir / "preview.png"
        legacy.generate_preview_png(ffmpeg_path, resolved, preview_path, plan)
        photo = tk.PhotoImage(file=str(preview_path))
        state.update(
            source=resolved,
            probe=probe,
            plan=plan,
            preview_dir=preview_dir,
            photo=photo,
            result=None,
            comparison=None,
        )
        reset_regions()
        clear_suggestions()
        configure_modes(media_kind)
        canvas.delete("all")
        canvas.configure(width=plan.preview_width, height=plan.preview_height)
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.image = photo
        source_var.set(
            f"{resolved.name} · {probe.width}×{probe.height} · {'视频' if media_kind == 'video' else '图片'}"
        )
        status_var.set(
            "图片将使用 Inpainting 重建像素" if media_kind == "image"
            else "可选择固定区域或移动水印跟踪；移动跟踪仅支持 1 个确认区域"
        )
        progress_var.set(0.0)
        sync_buttons()

    def choose_source() -> None:
        path = filedialog.askopenfilename(
            parent=dialog,
            title="选择需要清理可见水印的图片或视频",
            filetypes=(
                ("图片和视频", "*.jpg *.jpeg *.png *.webp *.mp4 *.mov *.mkv *.webm *.m4v"),
                ("所有文件", "*.*"),
            ),
        )
        if not path:
            return
        try:
            render_source(Path(path).expanduser().resolve())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, f"无法生成清理预览：\n{exc}", parent=dialog)

    def request_suggestions() -> None:
        source = state.get("source")
        probe = state.get("probe")
        plan = state.get("plan")
        if busy() or not isinstance(source, Path) or not isinstance(probe, MediaProbe) or plan is None:
            return
        ffmpeg_directory = engine_module.ffmpeg_dir()
        if ffmpeg_directory is None:
            messagebox.showerror(engine_module.APP_NAME, "FFmpeg 不可用。", parent=dialog)
            return
        try:
            ffmpeg_path = _tool_path(ffmpeg_directory, "ffmpeg")
        except MediaCleanupError as exc:
            messagebox.showerror(engine_module.APP_NAME, str(exc), parent=dialog)
            return
        profile = {"自动": "auto", "豆包": "doubao", "Gemini": "gemini"}.get(profile_var.get(), "auto")
        clear_suggestions("正在分析可见像素候选区…")
        state["suggestion_running"] = True
        status_var.set("正在分析可见水印候选区域…")
        sync_buttons()

        def worker() -> None:
            try:
                suggestions = suggest_visible_overlay_for_media(
                    ffmpeg_path,
                    source,
                    probe,
                    provider_hint=profile,
                )
            except Exception as exc:  # noqa: BLE001
                def failed(error=exc) -> None:
                    state["suggestion_running"] = False
                    suggestion_var.set("自动建议失败")
                    status_var.set("自动建议失败，可继续手动画框")
                    sync_buttons()
                    messagebox.showerror(engine_module.APP_NAME, f"无法生成自动建议：\n{error}", parent=dialog)
                dialog.after(0, failed)
                return

            def completed() -> None:
                state["suggestion_running"] = False
                if state.get("source") != source or state.get("plan") != plan:
                    sync_buttons()
                    return
                if not suggestions:
                    suggestion_var.set("未发现可靠候选区；请手动画框或选择位置先验")
                    status_var.set("没有自动采用任何区域")
                    sync_buttons()
                    return
                limit = 1 if selected_mode() == MODE_VIDEO_TRACKED else 16
                for suggestion in suggestions[:limit]:
                    x1, y1, x2, y2 = legacy.region_to_canvas_rect(suggestion.region, plan)
                    item = canvas.create_rectangle(
                        x1, y1, x2, y2,
                        outline=ui.ACCENT,
                        width=2,
                        dash=(6, 4),
                    )
                    state["suggestions"].append((item, suggestion))
                primary = suggestions[0]
                source_label = {
                    "edge-analysis": "单帧边缘分析",
                    "temporal-edge-analysis": "多帧稳定区域",
                    "profile": "位置先验（低置信度）",
                }.get(primary.source, primary.source)
                suggestion_var.set(
                    f"候选 {len(state['suggestions'])} 个 · 置信度 {round(primary.confidence * 100)}% · {source_label}"
                )
                status_var.set("虚线框仅为建议；采用后才会参与清理")
                sync_buttons()
            dialog.after(0, completed)

        threading.Thread(target=worker, name="GalaxyMediaCleanupV2Suggest", daemon=True).start()

    def accept_suggestions() -> None:
        if busy() or not state["suggestions"]:
            return
        limit = 1 if selected_mode() == MODE_VIDEO_TRACKED else 16
        available = max(0, limit - len(state["regions"]))
        accepted = state["suggestions"][:available]
        remaining = state["suggestions"][available:]
        for item, suggestion in accepted:
            canvas.itemconfigure(item, dash=(), outline=ui.CYAN, width=2)
            state["regions"].append((item, suggestion.region))
        for item, _suggestion in remaining:
            canvas.delete(item)
        state["suggestions"] = []
        suggestion_var.set(f"已采用 {len(accepted)} 个建议区域")
        status_var.set("实线框会参与清理")
        update_regions_label()

    def ignore_suggestions() -> None:
        if busy():
            return
        clear_suggestions("已忽略自动建议，可重新分析或手动画框")
        status_var.set("自动建议已忽略")

    def on_mode_changed(_event=None) -> None:
        clear_suggestions("处理方式已切换，可重新生成自动建议")
        if selected_mode() == MODE_VIDEO_TRACKED and len(state["regions"]) > 1:
            while len(state["regions"]) > 1:
                item, _region = state["regions"].pop()
                canvas.delete(item)
            update_regions_label()
        sync_buttons()

    mode_box.bind("<<ComboboxSelected>>", on_mode_changed)

    def clamp_canvas(event) -> tuple[float, float]:
        plan = state.get("plan")
        if plan is None:
            return 0.0, 0.0
        return (
            min(max(float(event.x), 0.0), float(plan.preview_width)),
            min(max(float(event.y), 0.0), float(plan.preview_height)),
        )

    def on_press(event) -> None:
        plan = state.get("plan")
        if busy() or plan is None:
            return
        limit = 1 if selected_mode() == MODE_VIDEO_TRACKED else 16
        if len(state["regions"]) >= limit:
            status_var.set("移动跟踪仅允许 1 个区域" if limit == 1 else "最多支持 16 个区域")
            return
        state["drag_start"] = clamp_canvas(event)
        x, y = state["drag_start"]
        state["drag_item"] = canvas.create_rectangle(
            x, y, x, y,
            outline=ui.ACCENT,
            width=2,
            dash=(5, 3),
        )

    def on_drag(event) -> None:
        if state.get("drag_start") is None or state.get("drag_item") is None:
            return
        x1, y1 = state["drag_start"]
        x2, y2 = clamp_canvas(event)
        canvas.coords(state["drag_item"], x1, y1, x2, y2)

    def on_release(event) -> None:
        plan = state.get("plan")
        start = state.get("drag_start")
        item = state.get("drag_item")
        state["drag_start"] = None
        state["drag_item"] = None
        if plan is None or start is None or item is None:
            return
        x1, y1 = start
        x2, y2 = clamp_canvas(event)
        if abs(x2 - x1) < 3 or abs(y2 - y1) < 3:
            canvas.delete(item)
            return
        try:
            region = legacy.canvas_rect_to_region(x1, y1, x2, y2, plan)
        except MediaCleanupError:
            canvas.delete(item)
            return
        canvas.itemconfigure(item, dash=(), outline=ui.CYAN, width=2)
        state["regions"].append((item, region))
        update_regions_label()

    canvas.bind("<Button-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)

    def undo_region() -> None:
        if busy() or not state["regions"]:
            return
        item, _region = state["regions"].pop()
        canvas.delete(item)
        update_regions_label()

    def open_output() -> None:
        result = state.get("result")
        if result is None:
            return
        try:
            extras._open_path(result.output_path.parent)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, f"无法打开输出目录：\n{exc}", parent=dialog)

    def show_comparison() -> None:
        result = state.get("result")
        source = state.get("source")
        plan = state.get("plan")
        ffmpeg_directory = engine_module.ffmpeg_dir()
        if result is None or not isinstance(source, Path) or plan is None or ffmpeg_directory is None:
            return
        compare_button.state(["disabled"])
        status_var.set("正在生成处理前 / 后对比…")

        def worker() -> None:
            try:
                artifact = render_cleanup_comparison(
                    ffmpeg_directory,
                    source,
                    result.output_path,
                    seek_seconds=plan.seek_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                def failed(error=exc) -> None:
                    status_var.set("生成前后对比失败")
                    sync_buttons()
                    messagebox.showerror(engine_module.APP_NAME, f"无法生成前后对比：\n{error}", parent=dialog)
                dialog.after(0, failed)
                return

            def completed() -> None:
                state["comparison"] = artifact
                status_var.set(f"前后对比：{artifact.comparison_path.name}")
                compare = tk.Toplevel(dialog)
                compare.title("处理前 / 后对比 · Galaxy Local Engine")
                compare.configure(bg=ui.BG)
                photo = tk.PhotoImage(file=str(artifact.comparison_path))
                frame = tk.Frame(compare, bg=ui.BG, padx=10, pady=10)
                frame.pack(fill="both", expand=True)
                comparison_canvas = tk.Canvas(
                    frame,
                    width=min(photo.width(), 1280),
                    height=min(photo.height(), 700),
                    bg="#111827",
                    highlightthickness=0,
                    scrollregion=(0, 0, photo.width(), photo.height()),
                )
                xbar = ttk.Scrollbar(frame, orient="horizontal", command=comparison_canvas.xview)
                ybar = ttk.Scrollbar(frame, orient="vertical", command=comparison_canvas.yview)
                comparison_canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
                comparison_canvas.grid(row=0, column=0, sticky="nsew")
                ybar.grid(row=0, column=1, sticky="ns")
                xbar.grid(row=1, column=0, sticky="ew")
                frame.grid_rowconfigure(0, weight=1)
                frame.grid_columnconfigure(0, weight=1)
                comparison_canvas.create_image(0, 0, image=photo, anchor="nw")
                comparison_canvas.image = photo
                compare.geometry(f"{min(photo.width() + 40, 1320)}x{min(photo.height() + 70, 780)}")
                sync_buttons()
            dialog.after(0, completed)

        threading.Thread(target=worker, name="GalaxyMediaCleanupCompare", daemon=True).start()

    def cancel_cleanup() -> None:
        if legacy.cancel_active_media_cleanup(window):
            status_var.set("正在取消清理任务…")
            sync_buttons()

    def run_cleanup() -> None:
        source = state.get("source")
        probe = state.get("probe")
        plan = state.get("plan")
        regions = tuple(record[1] for record in state["regions"])
        ffmpeg_directory = engine_module.ffmpeg_dir()
        if busy() or not isinstance(source, Path) or not isinstance(probe, MediaProbe) or plan is None or not regions:
            return
        if ffmpeg_directory is None:
            messagebox.showerror(engine_module.APP_NAME, "FFmpeg / FFprobe 不可用。", parent=dialog)
            return
        mode = selected_mode()
        try:
            validate_workbench_regions(probe.media_kind, mode, regions)
        except MediaCleanupError as exc:
            messagebox.showerror(engine_module.APP_NAME, str(exc), parent=dialog)
            return

        event = threading.Event()
        window._galaxy_media_cleanup_cancel_event = event
        state["result"] = None
        state["comparison"] = None
        progress_var.set(0.0)
        status_var.set("正在准备可见水印清理…")
        set_running(True)

        def report(percent: float, message: str) -> None:
            def apply() -> None:
                progress_var.set(max(0.0, min(100.0, float(percent))))
                status_var.set(str(message))
            try:
                dialog.after(0, apply)
            except Exception:
                pass

        def worker() -> None:
            try:
                result = execute_workbench_cleanup(
                    ffmpeg_directory,
                    source,
                    probe,
                    regions,
                    mode=mode,
                    anchor_seconds=plan.seek_seconds,
                    cancel_event=event,
                    progress_callback=report,
                )
            except MediaCleanupCancelled:
                def cancelled() -> None:
                    window._galaxy_media_cleanup_cancel_event = None
                    set_running(False)
                    progress_var.set(0.0)
                    status_var.set("清理任务已取消，原文件未修改")
                dialog.after(0, cancelled)
                return
            except Exception as exc:  # noqa: BLE001
                def failed(error=exc) -> None:
                    window._galaxy_media_cleanup_cancel_event = None
                    set_running(False)
                    progress_var.set(0.0)
                    status_var.set("清理失败")
                    messagebox.showerror(engine_module.APP_NAME, f"可见水印清理失败：\n{error}", parent=dialog)
                dialog.after(0, failed)
                return

            def completed() -> None:
                window._galaxy_media_cleanup_cancel_event = None
                state["result"] = result
                set_running(False)
                progress_var.set(100.0)
                method_label = {
                    MODE_IMAGE_INPAINT: "图片 Inpainting",
                    MODE_VIDEO_STATIC: "固定区域清理",
                    MODE_VIDEO_TRACKED: "移动水印跟踪清理",
                }[mode]
                status_var.set(f"完成 · {method_label} · {result.output_path.name}")
                messagebox.showinfo(
                    engine_module.APP_NAME,
                    f"可见水印清理完成。\n\n输出：{result.output_path}\n审计记录：{result.manifest_path.name}",
                    parent=dialog,
                )
                sync_buttons()
            dialog.after(0, completed)

        threading.Thread(target=worker, name="GalaxyMediaCleanupV2", daemon=True).start()

    choose_button = ui.ActionButton(footer, text="选择文件", command=choose_source, kind="secondary", compact=True)
    choose_button.pack(side="left")
    suggestion_button = ui.ActionButton(footer, text="自动建议", command=request_suggestions, kind="secondary", compact=True)
    suggestion_button.pack(side="left", padx=(7, 0))
    accept_button = ui.ActionButton(footer, text="采用建议", command=accept_suggestions, kind="ghost", compact=True)
    accept_button.pack(side="left", padx=(7, 0))
    ignore_button = ui.ActionButton(footer, text="忽略建议", command=ignore_suggestions, kind="ghost", compact=True)
    ignore_button.pack(side="left", padx=(7, 0))
    undo_button = ui.ActionButton(footer, text="撤销区域", command=undo_region, kind="ghost", compact=True)
    undo_button.pack(side="left", padx=(7, 0))
    clear_button = ui.ActionButton(footer, text="清空区域", command=reset_regions, kind="ghost", compact=True)
    clear_button.pack(side="left", padx=(7, 0))
    output_button = ui.ActionButton(footer, text="打开输出目录", command=open_output, kind="ghost", compact=True)
    output_button.pack(side="right")
    compare_button = ui.ActionButton(footer, text="处理前 / 后", command=show_comparison, kind="secondary", compact=True)
    compare_button.pack(side="right", padx=(0, 7))
    cancel_button = ui.ActionButton(footer, text="取消", command=cancel_cleanup, kind="ghost", compact=True)
    cancel_button.pack(side="right", padx=(0, 7))
    run_button = ui.ActionButton(footer, text="开始清理", command=run_cleanup, kind="primary", compact=True)
    run_button.pack(side="right", padx=(0, 7))
    sync_buttons()

    def close_dialog() -> None:
        if state.get("suggestion_running"):
            status_var.set("自动建议仍在分析中，完成后即可关闭窗口")
            return
        if legacy.media_cleanup_active(window):
            if not messagebox.askyesno(
                engine_module.APP_NAME,
                "当前清理任务仍在运行。取消任务并关闭窗口？",
                parent=dialog,
            ):
                return
            legacy.cancel_active_media_cleanup(window)
            status_var.set("正在取消清理任务…")

            def wait_for_stop() -> None:
                if legacy.media_cleanup_active(window):
                    dialog.after(100, wait_for_stop)
                    return
                close_dialog()
            dialog.after(100, wait_for_stop)
            return
        clear_preview_temp()
        window._media_cleanup_workbench = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close_dialog)


def install_media_cleanup_workbench_v2_patch() -> None:
    """Replace only the workbench presenter while preserving legacy hooks.

    `install_media_cleanup_workbench()` keeps owning the button, active/cancel
    attributes and graceful-exit contract. The button resolves `_show_workbench`
    from the legacy module at click time, so patching that symbol is sufficient.
    """
    legacy._show_workbench = _show_workbench_v2
    legacy._galaxy_media_cleanup_v2_patched = True


def run_media_cleanup_workbench_v2_self_test() -> None:
    assert workbench_mode_values("image") == (("智能修复（Inpainting）", MODE_IMAGE_INPAINT),)
    video_values = dict(workbench_mode_values("video"))
    assert video_values["固定水印区域"] == MODE_VIDEO_STATIC
    assert video_values["移动水印跟踪"] == MODE_VIDEO_TRACKED
    assert normalize_workbench_mode("image", "video-static") == MODE_IMAGE_INPAINT
    assert normalize_workbench_mode("video", "bad") == MODE_VIDEO_STATIC
    two = (CleanupRegion(1, 2, 10, 12), CleanupRegion(20, 22, 8, 9))
    assert validate_workbench_regions("image", MODE_IMAGE_INPAINT, two) == two
    try:
        validate_workbench_regions("video", MODE_VIDEO_TRACKED, two)
    except MediaCleanupError as exc:
        assert "exactly one" in str(exc)
    else:
        raise AssertionError("tracked workbench mode accepted multiple regions")
    install_media_cleanup_workbench_v2_patch()
    assert legacy._show_workbench is _show_workbench_v2
    assert getattr(legacy, "_galaxy_media_cleanup_v2_patched", False) is True
