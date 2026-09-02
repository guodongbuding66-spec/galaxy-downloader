from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "local-engine" / "media_cleanup_workbench.py"
MARKER = "from media_cleanup_suggestions import ("


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"integration anchor missing: {label}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("media cleanup suggestion workbench already integrated")
        return

    text = replace_once(
        text,
        ")\n\nMAX_PREVIEW_WIDTH = 900\n",
        ")\nfrom media_cleanup_suggestions import (\n"
        "    CleanupRegionSuggestion,\n"
        "    suggest_visible_overlay_for_media,\n"
        ")\n\nMAX_PREVIEW_WIDTH = 900\n",
        "suggestion imports",
    )

    text = replace_once(
        text,
        "    return CleanupRegion(sx, sy, ex - sx, ey - sy).validate()\n\n\ndef media_cleanup_active(window: Any) -> bool:\n",
        "    return CleanupRegion(sx, sy, ex - sx, ey - sy).validate()\n\n\n"
        "def region_to_canvas_rect(\n"
        "    region: CleanupRegion,\n"
        "    plan: CleanupPreviewPlan,\n"
        ") -> tuple[float, float, float, float]:\n"
        "    region = region.validate()\n"
        "    if (\n"
        "        region.x + region.width > plan.source_width\n"
        "        or region.y + region.height > plan.source_height\n"
        "    ):\n"
        "        raise MediaCleanupError(\"Cleanup suggestion exceeds the source frame\")\n"
        "    x1 = region.x * plan.preview_width / plan.source_width\n"
        "    y1 = region.y * plan.preview_height / plan.source_height\n"
        "    x2 = (region.x + region.width) * plan.preview_width / plan.source_width\n"
        "    y2 = (region.y + region.height) * plan.preview_height / plan.source_height\n"
        "    return x1, y1, x2, y2\n\n\n"
        "def media_cleanup_active(window: Any) -> bool:\n",
        "source-to-preview mapping",
    )

    text = replace_once(
        text,
        '        "regions": [],\n        "result": None,\n',
        '        "regions": [],\n        "suggestions": [],\n        "suggestion_running": False,\n        "result": None,\n',
        "suggestion state",
    )

    text = replace_once(
        text,
        '    ui._label(toolbar, variable=source_var, size=8, color=ui.MUTED, bg=ui.BG).pack(\n'
        '        side="left", fill="x", expand=True\n'
        '    )\n\n'
        '    preview_card = tk.Frame(\n',
        '    ui._label(toolbar, variable=source_var, size=8, color=ui.MUTED, bg=ui.BG).pack(\n'
        '        side="left", fill="x", expand=True\n'
        '    )\n\n'
        '    suggestion_row = tk.Frame(shell, bg=ui.BG)\n'
        '    suggestion_row.pack(fill="x", pady=(8, 0))\n'
        '    ui._label(suggestion_row, "自动建议", size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")\n'
        '    suggestion_profile_var = tk.StringVar(value="自动")\n'
        '    suggestion_profile = ttk.Combobox(\n'
        '        suggestion_row,\n'
        '        textvariable=suggestion_profile_var,\n'
        '        values=("自动", "豆包", "Gemini"),\n'
        '        state="readonly",\n'
        '        width=11,\n'
        '    )\n'
        '    suggestion_profile.pack(side="left", padx=(8, 0))\n'
        '    suggestion_var = tk.StringVar(value="尚未生成建议")\n'
        '    ui._label(\n'
        '        suggestion_row, variable=suggestion_var, size=8, color=ui.SUBTLE, bg=ui.BG\n'
        '    ).pack(side="left", padx=(12, 0), fill="x", expand=True)\n\n'
        '    preview_card = tk.Frame(\n',
        "suggestion toolbar",
    )

    old_running = '''    def set_running(running: bool) -> None:\n        window._galaxy_media_cleanup_running = bool(running)\n        if running:\n            choose_button.state(["disabled"])\n            run_button.state(["disabled"])\n            undo_button.state(["disabled"])\n            clear_button.state(["disabled"])\n            cancel_button.state(["!disabled"])\n        else:\n            choose_button.state(["!disabled"])\n            run_button.state(["!disabled"] if state["regions"] else ["disabled"])\n            undo_button.state(["!disabled"] if state["regions"] else ["disabled"])\n            clear_button.state(["!disabled"] if state["regions"] else ["disabled"])\n            cancel_button.state(["disabled"])\n'''
    new_running = '''    def set_running(running: bool) -> None:\n        window._galaxy_media_cleanup_running = bool(running)\n        suggesting = bool(state.get("suggestion_running"))\n        busy = bool(running or suggesting)\n        if busy:\n            choose_button.state(["disabled"])\n            run_button.state(["disabled"])\n            undo_button.state(["disabled"])\n            clear_button.state(["disabled"])\n            suggestion_button.state(["disabled"])\n            accept_suggestion_button.state(["disabled"])\n            ignore_suggestion_button.state(["disabled"])\n            cancel_button.state(["!disabled"] if running else ["disabled"])\n        else:\n            choose_button.state(["!disabled"])\n            run_button.state(["!disabled"] if state["regions"] else ["disabled"])\n            undo_button.state(["!disabled"] if state["regions"] else ["disabled"])\n            clear_button.state(["!disabled"] if state["regions"] else ["disabled"])\n            suggestion_button.state(["!disabled"] if state.get("source") else ["disabled"])\n            accept_suggestion_button.state(["!disabled"] if state["suggestions"] else ["disabled"])\n            ignore_suggestion_button.state(["!disabled"] if state["suggestions"] else ["disabled"])\n            cancel_button.state(["disabled"])\n'''
    text = replace_once(text, old_running, new_running, "busy control policy")

    text = replace_once(
        text,
        '''    def clear_preview_temp() -> None:\n        preview_dir = state.get("preview_dir")\n        state["preview_dir"] = None\n        if preview_dir:\n            shutil.rmtree(str(preview_dir), ignore_errors=True)\n\n    def update_regions_label() -> None:\n''',
        '''    def clear_preview_temp() -> None:\n        preview_dir = state.get("preview_dir")\n        state["preview_dir"] = None\n        if preview_dir:\n            shutil.rmtree(str(preview_dir), ignore_errors=True)\n\n    def clear_suggestions(*, message: str = "尚未生成建议") -> None:\n        for item, _suggestion in state["suggestions"]:\n            try:\n                canvas.delete(item)\n            except tk.TclError:\n                pass\n        state["suggestions"] = []\n        suggestion_var.set(message)\n        if \"accept_suggestion_button\" in locals():\n            set_running(media_cleanup_active(window))\n\n    def update_regions_label() -> None:\n''',
        "suggestion cleanup",
    )

    text = replace_once(
        text,
        '''        state.update(source=source, probe=probe, plan=plan, preview_dir=preview_dir, photo=photo, result=None)\n        reset_regions()\n        canvas.delete("all")\n''',
        '''        state.update(source=source, probe=probe, plan=plan, preview_dir=preview_dir, photo=photo, result=None)\n        reset_regions()\n        clear_suggestions()\n        canvas.delete("all")\n''',
        "clear old suggestions on source change",
    )

    text = replace_once(
        text,
        '''        cleanup_status_var.set("拖动鼠标框选需要清理的可见水印区域")\n        progress_var.set(0.0)\n        output_button.state(["disabled"])\n\n    def choose_source() -> None:\n''',
        '''        cleanup_status_var.set("拖动鼠标框选需要清理的可见水印区域，或先使用自动建议")\n        progress_var.set(0.0)\n        output_button.state(["disabled"])\n        set_running(False)\n\n    def choose_source() -> None:\n''',
        "enable suggestion after source load",
    )

    text = replace_once(
        text,
        '''        except Exception as exc:  # noqa: BLE001\n            messagebox.showerror(engine_module.APP_NAME, f"无法生成清理预览：\\n{exc}", parent=dialog)\n\n    def clamp_canvas(event) -> tuple[float, float]:\n''',
        '''        except Exception as exc:  # noqa: BLE001\n            messagebox.showerror(engine_module.APP_NAME, f"无法生成清理预览：\\n{exc}", parent=dialog)\n\n    def request_suggestions() -> None:\n        source = state.get("source")\n        probe = state.get("probe")\n        plan = state.get("plan")\n        if (\n            media_cleanup_active(window)\n            or state.get("suggestion_running")\n            or not isinstance(source, Path)\n            or not isinstance(probe, MediaProbe)\n            or not isinstance(plan, CleanupPreviewPlan)\n        ):\n            return\n        ffmpeg_directory = engine_module.ffmpeg_dir()\n        if ffmpeg_directory is None:\n            messagebox.showerror(engine_module.APP_NAME, "FFmpeg 不可用。", parent=dialog)\n            return\n        try:\n            ffmpeg_path = _tool_path(ffmpeg_directory, "ffmpeg")\n        except MediaCleanupError as exc:\n            messagebox.showerror(engine_module.APP_NAME, str(exc), parent=dialog)\n            return\n\n        profile = {"自动": "auto", "豆包": "doubao", "Gemini": "gemini"}.get(\n            suggestion_profile_var.get(), "auto"\n        )\n        clear_suggestions(message="正在分析可见像素候选区…")\n        state["suggestion_running"] = True\n        cleanup_status_var.set("正在分析可见水印候选区域…")\n        set_running(False)\n\n        def worker() -> None:\n            try:\n                suggestions = suggest_visible_overlay_for_media(\n                    ffmpeg_path,\n                    source,\n                    probe,\n                    provider_hint=profile,\n                )\n            except Exception as exc:  # noqa: BLE001\n                def failed(error=exc) -> None:\n                    state["suggestion_running"] = False\n                    suggestion_var.set("自动建议失败")\n                    cleanup_status_var.set("自动建议失败，可继续手动画框")\n                    set_running(False)\n                    messagebox.showerror(\n                        engine_module.APP_NAME, f"无法生成自动建议：\\n{error}", parent=dialog\n                    )\n\n                try:\n                    dialog.after(0, failed)\n                except Exception:\n                    state["suggestion_running"] = False\n                return\n\n            def completed() -> None:\n                state["suggestion_running"] = False\n                if state.get("source") != source or state.get("plan") != plan:\n                    set_running(False)\n                    return\n                if not suggestions:\n                    suggestion_var.set("未发现可靠候选区；请手动画框或选择豆包 / Gemini 位置先验")\n                    cleanup_status_var.set("没有自动采用任何区域")\n                    set_running(False)\n                    return\n\n                for suggestion in suggestions[:MAX_CLEANUP_REGIONS]:\n                    x1, y1, x2, y2 = region_to_canvas_rect(suggestion.region, plan)\n                    item = canvas.create_rectangle(\n                        x1,\n                        y1,\n                        x2,\n                        y2,\n                        outline=ui.ACCENT,\n                        width=2,\n                        dash=(6, 4),\n                    )\n                    state["suggestions"].append((item, suggestion))\n                primary = suggestions[0]\n                source_label = "画面边缘分析" if primary.source == "edge-analysis" else "位置先验（低置信度）"\n                suggestion_var.set(\n                    f"候选 {len(suggestions)} 个 · 置信度 {round(primary.confidence * 100)}% · {source_label}"\n                )\n                cleanup_status_var.set("虚线框仅为建议；采用后才会进入清理区域")\n                set_running(False)\n\n            try:\n                dialog.after(0, completed)\n            except Exception:\n                state["suggestion_running"] = False\n\n        threading.Thread(target=worker, name="GalaxyMediaCleanupSuggest", daemon=True).start()\n\n    def accept_suggestions() -> None:\n        if media_cleanup_active(window) or state.get("suggestion_running") or not state["suggestions"]:\n            return\n        available = MAX_CLEANUP_REGIONS - len(state["regions"])\n        if available <= 0:\n            cleanup_status_var.set(f"最多支持 {MAX_CLEANUP_REGIONS} 个清理区域")\n            return\n        accepted = state["suggestions"][:available]\n        remaining = state["suggestions"][available:]\n        for item, suggestion in accepted:\n            canvas.itemconfigure(item, dash=(), outline=ui.CYAN, width=2)\n            state["regions"].append((item, suggestion.region))\n        for item, _suggestion in remaining:\n            canvas.delete(item)\n        state["suggestions"] = []\n        suggestion_var.set(f"已采用 {len(accepted)} 个建议区域，可继续拖动补充")\n        cleanup_status_var.set("建议已确认；实线框会参与清理")\n        update_regions_label()\n        set_running(False)\n\n    def ignore_suggestions() -> None:\n        if media_cleanup_active(window) or state.get("suggestion_running"):\n            return\n        clear_suggestions(message="已忽略自动建议，可重新分析或手动画框")\n        cleanup_status_var.set("自动建议已忽略")\n\n    def clamp_canvas(event) -> tuple[float, float]:\n''',
        "suggestion worker and review actions",
    )

    text = replace_once(
        text,
        '''    def run_cleanup() -> None:\n        source = state.get("source")\n        regions = tuple(record[1] for record in state["regions"])\n''',
        '''    def run_cleanup() -> None:\n        if state.get("suggestion_running"):\n            return\n        source = state.get("source")\n        regions = tuple(record[1] for record in state["regions"])\n''',
        "block cleanup while suggesting",
    )

    text = replace_once(
        text,
        '''    choose_button = ui.ActionButton(footer, text="选择文件", command=choose_source, kind="secondary", compact=True)\n    choose_button.pack(side="left")\n    undo_button = ui.ActionButton(footer, text="撤销区域", command=undo_region, kind="ghost", compact=True)\n''',
        '''    choose_button = ui.ActionButton(footer, text="选择文件", command=choose_source, kind="secondary", compact=True)\n    choose_button.pack(side="left")\n    suggestion_button = ui.ActionButton(\n        footer, text="自动建议", command=request_suggestions, kind="secondary", compact=True\n    )\n    suggestion_button.pack(side="left", padx=(7, 0))\n    accept_suggestion_button = ui.ActionButton(\n        footer, text="采用建议", command=accept_suggestions, kind="ghost", compact=True\n    )\n    accept_suggestion_button.pack(side="left", padx=(7, 0))\n    ignore_suggestion_button = ui.ActionButton(\n        footer, text="忽略建议", command=ignore_suggestions, kind="ghost", compact=True\n    )\n    ignore_suggestion_button.pack(side="left", padx=(7, 0))\n    undo_button = ui.ActionButton(footer, text="撤销区域", command=undo_region, kind="ghost", compact=True)\n''',
        "suggestion footer actions",
    )

    text = replace_once(
        text,
        '''    run_button.state(["disabled"])\n    undo_button.state(["disabled"])\n    clear_button.state(["disabled"])\n    output_button.state(["disabled"])\n\n    def close_dialog() -> None:\n''',
        '''    run_button.state(["disabled"])\n    suggestion_button.state(["disabled"])\n    accept_suggestion_button.state(["disabled"])\n    ignore_suggestion_button.state(["disabled"])\n    undo_button.state(["disabled"])\n    clear_button.state(["disabled"])\n    output_button.state(["disabled"])\n\n    def close_dialog() -> None:\n        if state.get("suggestion_running"):\n            cleanup_status_var.set("自动建议仍在分析中，完成后即可关闭窗口")\n            return\n''',
        "initial states and close guard",
    )

    text = replace_once(
        text,
        '''    corner = canvas_rect_to_region(810, 455, 900, 506, self_plan)\n    assert corner.x >= 1728\n''',
        '''    corner = canvas_rect_to_region(810, 455, 900, 506, self_plan)\n    canvas_corner = region_to_canvas_rect(corner, self_plan)\n    round_trip = canvas_rect_to_region(*canvas_corner, self_plan)\n    assert round_trip == corner\n    assert corner.x >= 1728\n''',
        "mapping self-test",
    )

    TARGET.write_text(text, encoding="utf-8")
    print("integrated media cleanup suggestion workbench")


if __name__ == "__main__":
    main()
