from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desktop_hooks import register_after_build_ui_hook, registered_after_build_ui_hooks
from media_cleanup import (
    MAX_CLEANUP_REGIONS,
    CleanupRegion,
    MediaCleanupCancelled,
    MediaCleanupError,
    MediaProbe,
    _tool_path,
    _validate_input,
    cleanup_visible_overlay,
    probe_media,
)
from media_cleanup_suggestions import (
    suggest_visible_overlay_for_media,
)

MAX_PREVIEW_WIDTH = 900
MAX_PREVIEW_HEIGHT = 520


@dataclass(frozen=True)
class CleanupPreviewPlan:
    media_kind: str
    source_width: int
    source_height: int
    preview_width: int
    preview_height: int
    seek_seconds: float = 0.0


def fit_preview_size(
    source_width: int,
    source_height: int,
    *,
    max_width: int = MAX_PREVIEW_WIDTH,
    max_height: int = MAX_PREVIEW_HEIGHT,
) -> tuple[int, int]:
    if source_width < 2 or source_height < 2:
        raise MediaCleanupError("Preview source dimensions are invalid")
    if max_width < 2 or max_height < 2:
        raise MediaCleanupError("Preview bounds are invalid")
    scale = min(1.0, max_width / source_width, max_height / source_height)
    width = max(2, int(round(source_width * scale)))
    height = max(2, int(round(source_height * scale)))
    return width, height


def build_preview_plan(probe: MediaProbe) -> CleanupPreviewPlan:
    preview_width, preview_height = fit_preview_size(probe.width, probe.height)
    seek = 0.0
    if probe.media_kind == "video" and probe.duration_seconds > 0:
        seek = min(1.0, probe.duration_seconds / 2.0)
    return CleanupPreviewPlan(
        media_kind=probe.media_kind,
        source_width=probe.width,
        source_height=probe.height,
        preview_width=preview_width,
        preview_height=preview_height,
        seek_seconds=max(0.0, seek),
    )


def build_preview_command(
    ffmpeg_path: Path,
    source: Path,
    output_png: Path,
    plan: CleanupPreviewPlan,
) -> list[str]:
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
    ]
    if plan.media_kind == "video" and plan.seek_seconds > 0:
        command.extend(["-ss", f"{plan.seek_seconds:.3f}"])
    command.extend(
        [
            "-i",
            str(source),
            "-vf",
            f"scale={plan.preview_width}:{plan.preview_height}",
            "-frames:v",
            "1",
            "-an",
            "-sn",
            str(output_png),
        ]
    )
    return command


def generate_preview_png(
    ffmpeg_path: Path,
    source: Path,
    output_png: Path,
    plan: CleanupPreviewPlan,
) -> Path:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    command = build_preview_command(ffmpeg_path, source, output_png, plan)
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False)
    except OSError as exc:
        raise MediaCleanupError(f"Could not start FFmpeg preview renderer: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaCleanupError("Timed out while creating media preview") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "FFmpeg preview failed").strip()[-600:]
        raise MediaCleanupError(f"Could not create cleanup preview: {detail}")
    if not output_png.exists() or output_png.stat().st_size <= 0:
        raise MediaCleanupError("Preview renderer did not produce a PNG frame")
    return output_png


def canvas_rect_to_region(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    plan: CleanupPreviewPlan,
) -> CleanupRegion:
    left = min(max(min(x1, x2), 0.0), float(plan.preview_width))
    right = min(max(max(x1, x2), 0.0), float(plan.preview_width))
    top = min(max(min(y1, y2), 0.0), float(plan.preview_height))
    bottom = min(max(max(y1, y2), 0.0), float(plan.preview_height))
    if right - left < 1.0 or bottom - top < 1.0:
        raise MediaCleanupError("Cleanup selection is too small")

    sx = int(math.floor(left * plan.source_width / plan.preview_width))
    sy = int(math.floor(top * plan.source_height / plan.preview_height))
    ex = int(math.ceil(right * plan.source_width / plan.preview_width))
    ey = int(math.ceil(bottom * plan.source_height / plan.preview_height))
    sx = min(max(sx, 0), plan.source_width - 2)
    sy = min(max(sy, 0), plan.source_height - 2)
    ex = min(max(ex, sx + 2), plan.source_width)
    ey = min(max(ey, sy + 2), plan.source_height)
    return CleanupRegion(sx, sy, ex - sx, ey - sy).validate()


def region_to_canvas_rect(
    region: CleanupRegion,
    plan: CleanupPreviewPlan,
) -> tuple[float, float, float, float]:
    region = region.validate()
    if (
        region.x + region.width > plan.source_width
        or region.y + region.height > plan.source_height
    ):
        raise MediaCleanupError("Cleanup suggestion exceeds the source frame")
    x1 = region.x * plan.preview_width / plan.source_width
    y1 = region.y * plan.preview_height / plan.source_height
    x2 = (region.x + region.width) * plan.preview_width / plan.source_width
    y2 = (region.y + region.height) * plan.preview_height / plan.source_height
    return x1, y1, x2, y2


def media_cleanup_active(window: Any) -> bool:
    return bool(getattr(window, "_galaxy_media_cleanup_running", False))


def cancel_active_media_cleanup(window: Any) -> bool:
    event = getattr(window, "_galaxy_media_cleanup_cancel_event", None)
    setter = getattr(event, "set", None)
    if not callable(setter):
        return False
    setter()
    return True


def _show_workbench(window: Any, engine_module: Any) -> None:
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
    dialog.title("可见水印清理 · Galaxy Local Engine")
    dialog.geometry("1040x800")
    dialog.minsize(840, 680)
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
    }

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "可见水印清理", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "选择图片或视频，在预览中框选 Logo / 文字 / 角标区域。框选坐标会映射回原始分辨率后再处理。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=930,
        justify="left",
    ).pack(anchor="w", pady=(4, 2))
    ui._label(
        shell,
        "仅编辑画面中可见像素；不会识别、规避或移除 SynthID / C2PA 等不可见来源或真实性标记。",
        size=7,
        color=ui.SUBTLE,
        bg=ui.BG,
        wraplength=930,
        justify="left",
    ).pack(anchor="w", pady=(0, 12))

    toolbar = tk.Frame(shell, bg=ui.BG)
    toolbar.pack(fill="x")
    source_var = tk.StringVar(value="尚未选择文件")
    ui._label(toolbar, variable=source_var, size=8, color=ui.MUTED, bg=ui.BG).pack(
        side="left", fill="x", expand=True
    )

    suggestion_row = tk.Frame(shell, bg=ui.BG)
    suggestion_row.pack(fill="x", pady=(8, 0))
    ui._label(suggestion_row, "自动建议", size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    suggestion_profile_var = tk.StringVar(value="自动")
    suggestion_profile = ttk.Combobox(
        suggestion_row,
        textvariable=suggestion_profile_var,
        values=("自动", "豆包", "Gemini"),
        state="readonly",
        width=11,
    )
    suggestion_profile.pack(side="left", padx=(8, 0))
    suggestion_var = tk.StringVar(value="尚未生成建议")
    ui._label(
        suggestion_row, variable=suggestion_var, size=8, color=ui.SUBTLE, bg=ui.BG
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
    placeholder = canvas.create_text(
        360,
        210,
        text="选择图片或视频后，在这里框选可见水印区域",
        fill=ui.SUBTLE,
        font=("Segoe UI", 10),
    )

    region_var = tk.StringVar(value="已选 0 个区域")
    ui._label(shell, variable=region_var, size=8, color=ui.MUTED, bg=ui.BG).pack(anchor="w", pady=(9, 0))

    status_row = tk.Frame(shell, bg=ui.BG)
    status_row.pack(fill="x", pady=(8, 0))
    cleanup_status_var = tk.StringVar(value="就绪")
    ui._label(status_row, variable=cleanup_status_var, size=8, color=ui.SUBTLE, bg=ui.BG).pack(side="left")
    progress_var = tk.DoubleVar(value=0.0)
    progress = ttk.Progressbar(status_row, variable=progress_var, maximum=100, style="Galaxy.Horizontal.TProgressbar")
    progress.pack(side="right", fill="x", expand=True, padx=(14, 0))

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))

    def set_running(running: bool) -> None:
        window._galaxy_media_cleanup_running = bool(running)
        suggesting = bool(state.get("suggestion_running"))
        busy = bool(running or suggesting)
        if busy:
            suggestion_profile.configure(state="disabled")
            choose_button.state(["disabled"])
            run_button.state(["disabled"])
            undo_button.state(["disabled"])
            clear_button.state(["disabled"])
            suggestion_button.state(["disabled"])
            accept_suggestion_button.state(["disabled"])
            ignore_suggestion_button.state(["disabled"])
            cancel_button.state(["!disabled"] if running else ["disabled"])
        else:
            suggestion_profile.configure(state="readonly")
            choose_button.state(["!disabled"])
            run_button.state(["!disabled"] if state["regions"] else ["disabled"])
            undo_button.state(["!disabled"] if state["regions"] else ["disabled"])
            clear_button.state(["!disabled"] if state["regions"] else ["disabled"])
            suggestion_button.state(["!disabled"] if state.get("source") else ["disabled"])
            accept_suggestion_button.state(["!disabled"] if state["suggestions"] else ["disabled"])
            ignore_suggestion_button.state(["!disabled"] if state["suggestions"] else ["disabled"])
            cancel_button.state(["disabled"])

    def clear_preview_temp() -> None:
        preview_dir = state.get("preview_dir")
        state["preview_dir"] = None
        if preview_dir:
            shutil.rmtree(str(preview_dir), ignore_errors=True)

    def clear_suggestions(*, message: str = "尚未生成建议") -> None:
        for item, _suggestion in state["suggestions"]:
            try:
                canvas.delete(item)
            except tk.TclError:
                pass
        state["suggestions"] = []
        suggestion_var.set(message)

    def update_regions_label() -> None:
        regions = [record[1] for record in state["regions"]]
        if not regions:
            region_var.set("已选 0 个区域")
            run_button.state(["disabled"])
            undo_button.state(["disabled"])
            clear_button.state(["disabled"])
            return
        summary = "；".join(
            f"#{index + 1} {region.x},{region.y} {region.width}×{region.height}"
            for index, region in enumerate(regions[:4])
        )
        if len(regions) > 4:
            summary += f"；另 {len(regions) - 4} 个"
        region_var.set(f"已选 {len(regions)} 个区域 · {summary}")
        if not media_cleanup_active(window):
            run_button.state(["!disabled"])
            undo_button.state(["!disabled"])
            clear_button.state(["!disabled"])

    def reset_regions() -> None:
        for item, _region in state["regions"]:
            try:
                canvas.delete(item)
            except tk.TclError:
                pass
        state["regions"] = []
        drag_item = state.get("drag_item")
        if drag_item is not None:
            canvas.delete(drag_item)
        state["drag_item"] = None
        state["drag_start"] = None
        update_regions_label()

    def render_source(source: Path) -> None:
        ffmpeg_directory = engine_module.ffmpeg_dir()
        if ffmpeg_directory is None:
            raise MediaCleanupError("FFmpeg / FFprobe is not available in this Local Engine package")
        _source, media_kind = _validate_input(source)
        ffmpeg_path = _tool_path(ffmpeg_directory, "ffmpeg")
        ffprobe_path = _tool_path(ffmpeg_directory, "ffprobe")
        probe = probe_media(ffprobe_path, source, media_kind)
        plan = build_preview_plan(probe)
        clear_preview_temp()
        preview_dir = Path(tempfile.mkdtemp(prefix="galaxy-cleanup-preview-"))
        preview_path = preview_dir / "preview.png"
        generate_preview_png(ffmpeg_path, source, preview_path, plan)
        photo = tk.PhotoImage(file=str(preview_path))

        state.update(source=source, probe=probe, plan=plan, preview_dir=preview_dir, photo=photo, result=None)
        reset_regions()
        clear_suggestions()
        canvas.delete("all")
        canvas.configure(width=plan.preview_width, height=plan.preview_height)
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.image = photo
        source_var.set(
            f"{source.name} · {probe.width}×{probe.height} · {'视频' if media_kind == 'video' else '图片'}"
        )
        cleanup_status_var.set("拖动鼠标框选需要清理的可见水印区域，或先使用自动建议")
        progress_var.set(0.0)
        output_button.state(["disabled"])
        set_running(False)

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
        if (
            media_cleanup_active(window)
            or state.get("suggestion_running")
            or not isinstance(source, Path)
            or not isinstance(probe, MediaProbe)
            or not isinstance(plan, CleanupPreviewPlan)
        ):
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

        profile = {"自动": "auto", "豆包": "doubao", "Gemini": "gemini"}.get(
            suggestion_profile_var.get(), "auto"
        )
        clear_suggestions(message="正在分析可见像素候选区…")
        state["suggestion_running"] = True
        cleanup_status_var.set("正在分析可见水印候选区域…")
        set_running(False)

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
                    cleanup_status_var.set("自动建议失败，可继续手动画框")
                    set_running(False)
                    messagebox.showerror(
                        engine_module.APP_NAME, f"无法生成自动建议：\n{error}", parent=dialog
                    )

                try:
                    dialog.after(0, failed)
                except Exception:
                    state["suggestion_running"] = False
                return

            def completed() -> None:
                state["suggestion_running"] = False
                if state.get("source") != source or state.get("plan") != plan:
                    set_running(False)
                    return
                if not suggestions:
                    suggestion_var.set("未发现可靠候选区；请手动画框或选择豆包 / Gemini 位置先验")
                    cleanup_status_var.set("没有自动采用任何区域")
                    set_running(False)
                    return

                for suggestion in suggestions[:MAX_CLEANUP_REGIONS]:
                    x1, y1, x2, y2 = region_to_canvas_rect(suggestion.region, plan)
                    item = canvas.create_rectangle(
                        x1,
                        y1,
                        x2,
                        y2,
                        outline=ui.ACCENT,
                        width=2,
                        dash=(6, 4),
                    )
                    state["suggestions"].append((item, suggestion))
                primary = suggestions[0]
                source_label = "画面边缘分析" if primary.source == "edge-analysis" else "位置先验（低置信度）"
                suggestion_var.set(
                    f"候选 {len(suggestions)} 个 · 置信度 {round(primary.confidence * 100)}% · {source_label}"
                )
                cleanup_status_var.set("虚线框仅为建议；采用后才会进入清理区域")
                set_running(False)

            try:
                dialog.after(0, completed)
            except Exception:
                state["suggestion_running"] = False

        threading.Thread(target=worker, name="GalaxyMediaCleanupSuggest", daemon=True).start()

    def accept_suggestions() -> None:
        if media_cleanup_active(window) or state.get("suggestion_running") or not state["suggestions"]:
            return
        available = MAX_CLEANUP_REGIONS - len(state["regions"])
        if available <= 0:
            cleanup_status_var.set(f"最多支持 {MAX_CLEANUP_REGIONS} 个清理区域")
            return
        accepted = state["suggestions"][:available]
        remaining = state["suggestions"][available:]
        for item, suggestion in accepted:
            canvas.itemconfigure(item, dash=(), outline=ui.CYAN, width=2)
            state["regions"].append((item, suggestion.region))
        for item, _suggestion in remaining:
            canvas.delete(item)
        state["suggestions"] = []
        suggestion_var.set(f"已采用 {len(accepted)} 个建议区域，可继续拖动补充")
        cleanup_status_var.set("建议已确认；实线框会参与清理")
        update_regions_label()
        set_running(False)

    def ignore_suggestions() -> None:
        if media_cleanup_active(window) or state.get("suggestion_running"):
            return
        clear_suggestions(message="已忽略自动建议，可重新分析或手动画框")
        cleanup_status_var.set("自动建议已忽略")
        set_running(False)

    def clamp_canvas(event) -> tuple[float, float]:
        plan = state.get("plan")
        if not isinstance(plan, CleanupPreviewPlan):
            return 0.0, 0.0
        return (
            min(max(float(event.x), 0.0), float(plan.preview_width)),
            min(max(float(event.y), 0.0), float(plan.preview_height)),
        )

    def on_press(event) -> None:
        if media_cleanup_active(window) or state.get("suggestion_running") or state.get("plan") is None:
            return
        if len(state["regions"]) >= MAX_CLEANUP_REGIONS:
            cleanup_status_var.set(f"最多支持 {MAX_CLEANUP_REGIONS} 个清理区域")
            return
        state["drag_start"] = clamp_canvas(event)
        item = state.get("drag_item")
        if item is not None:
            canvas.delete(item)
        x, y = state["drag_start"]
        state["drag_item"] = canvas.create_rectangle(
            x,
            y,
            x,
            y,
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
        if not isinstance(plan, CleanupPreviewPlan) or start is None or item is None:
            return
        x1, y1 = start
        x2, y2 = clamp_canvas(event)
        if abs(x2 - x1) < 3 or abs(y2 - y1) < 3:
            canvas.delete(item)
            return
        try:
            region = canvas_rect_to_region(x1, y1, x2, y2, plan)
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
        if not state["regions"] or media_cleanup_active(window) or state.get("suggestion_running"):
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

    def cancel_cleanup() -> None:
        if cancel_active_media_cleanup(window):
            cleanup_status_var.set("正在取消清理任务…")
            cancel_button.state(["disabled"])

    def run_cleanup() -> None:
        if state.get("suggestion_running"):
            return
        source = state.get("source")
        regions = tuple(record[1] for record in state["regions"])
        ffmpeg_directory = engine_module.ffmpeg_dir()
        if not isinstance(source, Path) or not regions:
            return
        if ffmpeg_directory is None:
            messagebox.showerror(engine_module.APP_NAME, "FFmpeg / FFprobe 不可用。", parent=dialog)
            return

        event = threading.Event()
        window._galaxy_media_cleanup_cancel_event = event
        state["result"] = None
        output_button.state(["disabled"])
        progress_var.set(0.0)
        cleanup_status_var.set("正在准备可见水印清理…")
        set_running(True)

        def report(percent: float, message: str) -> None:
            def apply() -> None:
                progress_var.set(max(0.0, min(100.0, float(percent))))
                cleanup_status_var.set(str(message))

            try:
                dialog.after(0, apply)
            except Exception:
                pass

        def worker() -> None:
            try:
                result = cleanup_visible_overlay(
                    ffmpeg_directory,
                    source,
                    regions,
                    cancel_event=event,
                    progress_callback=report,
                )
            except MediaCleanupCancelled:
                def cancelled() -> None:
                    window._galaxy_media_cleanup_cancel_event = None
                    set_running(False)
                    progress_var.set(0.0)
                    cleanup_status_var.set("清理任务已取消，原文件未修改")

                try:
                    dialog.after(0, cancelled)
                except Exception:
                    window._galaxy_media_cleanup_running = False
                return
            except Exception as exc:  # noqa: BLE001
                def failed(error=exc) -> None:
                    window._galaxy_media_cleanup_cancel_event = None
                    set_running(False)
                    progress_var.set(0.0)
                    cleanup_status_var.set("清理失败")
                    messagebox.showerror(engine_module.APP_NAME, f"可见水印清理失败：\n{error}", parent=dialog)

                try:
                    dialog.after(0, failed)
                except Exception:
                    window._galaxy_media_cleanup_running = False
                return

            def completed() -> None:
                window._galaxy_media_cleanup_cancel_event = None
                state["result"] = result
                set_running(False)
                progress_var.set(100.0)
                cleanup_status_var.set(f"完成：{result.output_path.name}")
                output_button.state(["!disabled"])
                messagebox.showinfo(
                    engine_module.APP_NAME,
                    f"可见水印清理完成。\n\n输出：{result.output_path}\n审计记录：{result.manifest_path.name}",
                    parent=dialog,
                )

            try:
                dialog.after(0, completed)
            except Exception:
                window._galaxy_media_cleanup_running = False

        threading.Thread(target=worker, name="GalaxyMediaCleanup", daemon=True).start()

    choose_button = ui.ActionButton(footer, text="选择文件", command=choose_source, kind="secondary", compact=True)
    choose_button.pack(side="left")
    suggestion_button = ui.ActionButton(
        footer, text="自动建议", command=request_suggestions, kind="secondary", compact=True
    )
    suggestion_button.pack(side="left", padx=(7, 0))
    accept_suggestion_button = ui.ActionButton(
        footer, text="采用建议", command=accept_suggestions, kind="ghost", compact=True
    )
    accept_suggestion_button.pack(side="left", padx=(7, 0))
    ignore_suggestion_button = ui.ActionButton(
        footer, text="忽略建议", command=ignore_suggestions, kind="ghost", compact=True
    )
    ignore_suggestion_button.pack(side="left", padx=(7, 0))
    undo_button = ui.ActionButton(footer, text="撤销区域", command=undo_region, kind="ghost", compact=True)
    undo_button.pack(side="left", padx=(7, 0))
    clear_button = ui.ActionButton(footer, text="清空区域", command=reset_regions, kind="ghost", compact=True)
    clear_button.pack(side="left", padx=(7, 0))
    output_button = ui.ActionButton(footer, text="打开输出目录", command=open_output, kind="ghost", compact=True)
    output_button.pack(side="right")
    cancel_button = ui.ActionButton(footer, text="取消", command=cancel_cleanup, kind="ghost", compact=True)
    cancel_button.pack(side="right", padx=(0, 7))
    run_button = ui.ActionButton(footer, text="开始清理", command=run_cleanup, kind="primary", compact=True)
    run_button.pack(side="right", padx=(0, 7))
    set_running(False)
    run_button.state(["disabled"])
    suggestion_button.state(["disabled"])
    accept_suggestion_button.state(["disabled"])
    ignore_suggestion_button.state(["disabled"])
    undo_button.state(["disabled"])
    clear_button.state(["disabled"])
    output_button.state(["disabled"])

    def close_dialog() -> None:
        if state.get("suggestion_running"):
            cleanup_status_var.set("自动建议仍在分析中，完成后即可关闭窗口")
            return
        if media_cleanup_active(window):
            if not messagebox.askyesno(
                engine_module.APP_NAME,
                "当前清理任务仍在运行。取消任务并关闭窗口？",
                parent=dialog,
            ):
                return
            cancel_active_media_cleanup(window)
            cleanup_status_var.set("正在取消清理任务…")

            def wait_for_stop() -> None:
                if media_cleanup_active(window):
                    dialog.after(100, wait_for_stop)
                    return
                close_dialog()

            dialog.after(100, wait_for_stop)
            return
        clear_preview_temp()
        window._media_cleanup_workbench = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close_dialog)


def install_media_cleanup_workbench(engine_module: Any):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_media_cleanup_workbench_installed", False):
        return window_cls

    def after_build_ui(window: Any) -> None:
        import desktop_ui as ui

        actions = window._copy_diag_button.master
        button = ui.ActionButton(
            actions,
            text="去水印",
            command=lambda: _show_workbench(window, engine_module),
            kind="ghost",
            compact=True,
        )
        button.pack(side="left", padx=(8, 0))
        window._media_cleanup_button = button
        window._galaxy_media_cleanup_running = False
        window._galaxy_media_cleanup_cancel_event = None

    register_after_build_ui_hook(
        window_cls,
        "media-cleanup-workbench",
        after_build_ui,
        order=135,
    )
    window_cls._galaxy_media_cleanup_workbench_installed = True
    return window_cls


def run_media_cleanup_workbench_self_test() -> None:
    self_plan = CleanupPreviewPlan("video", 1920, 1080, 900, 506, 1.0)
    region = canvas_rect_to_region(0, 0, 900, 506, self_plan)
    assert region == CleanupRegion(0, 0, 1920, 1080)
    corner = canvas_rect_to_region(810, 455, 900, 506, self_plan)
    canvas_corner = region_to_canvas_rect(corner, self_plan)
    round_trip = canvas_rect_to_region(*canvas_corner, self_plan)
    assert round_trip == corner
    assert corner.x >= 1728
    assert corner.y >= 971
    assert corner.x + corner.width <= 1920
    assert corner.y + corner.height <= 1080
    assert fit_preview_size(640, 480) == (640, 480)
    fitted = fit_preview_size(3840, 2160)
    assert fitted[0] <= MAX_PREVIEW_WIDTH and fitted[1] <= MAX_PREVIEW_HEIGHT
    video_command = build_preview_command(
        Path("ffmpeg.exe"),
        Path("input.mp4"),
        Path("preview.png"),
        self_plan,
    )
    assert "-ss" in video_command
    assert "scale=900:506" in video_command
    image_plan = CleanupPreviewPlan("image", 640, 480, 640, 480, 0.0)
    image_command = build_preview_command(
        Path("ffmpeg.exe"),
        Path("input.png"),
        Path("preview.png"),
        image_plan,
    )
    assert "-ss" not in image_command

    class FakeWindow:
        pass

    class FakeEngine:
        EngineWindow = FakeWindow

    install_media_cleanup_workbench(FakeEngine)
    assert "media-cleanup-workbench" in registered_after_build_ui_hooks(FakeWindow)
    assert getattr(FakeWindow, "_galaxy_media_cleanup_workbench_installed", False) is True
