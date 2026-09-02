from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import bridge
import desktop_quick_download as quick
import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook, registered_after_build_ui_hooks


_PHASE_LABELS = (
    "1  粘贴链接",
    "2  解析预览",
    "3  选择格式",
    "4  下载 / 排队",
)


def workbench_phase_from_state(value: object) -> int:
    text = quick._text(value).lower()
    if any(token in text for token in ("提交", "已开始下载", "已加入等待队列", "下载任务", "队列")):
        return 4
    if any(token in text for token in ("解析完成", "视频 ", "音频 ", "选择格式", "真实格式")):
        return 3
    if any(token in text for token in ("校验", "解析", "联网")):
        return 2
    return 1


def audio_control_mode(video_option: object, audio_count: int) -> str:
    if isinstance(video_option, dict) and quick._text(video_option.get("streamType")) == "muxed":
        return "embedded"
    if audio_count > 0:
        return "separate"
    return "none"


def _set_phase(window, phase: int) -> None:
    labels = getattr(window, "_workbench_phase_widgets", ())
    for index, label in enumerate(labels, start=1):
        active = index == phase
        complete = index < phase
        label.configure(
            fg=ui.TEXT if active else (ui.CYAN if complete else ui.SUBTLE),
            bg=ui.PANEL_3 if active else ui.PANEL_2,
        )


def _selected_video_option(window) -> dict[str, Any] | None:
    preview = getattr(window, "_quick_preview", None)
    if not isinstance(preview, quick.QuickPreview):
        return None
    option_id = getattr(window, "_quick_video_display", {}).get(window._quick_video_var.get())
    return quick._option_by_id(preview.video_options, option_id)


def _update_format_summary(window) -> None:
    summary_var = getattr(window, "_workbench_format_summary_var", None)
    if summary_var is None:
        return
    preview = getattr(window, "_quick_preview", None)
    if not isinstance(preview, quick.QuickPreview):
        summary_var.set("解析后会显示真实 format_id 对应的清晰度、编码和音频组合。")
        return

    video_label = quick._text(window._quick_video_var.get(), "仅音频")
    audio_label = quick._text(window._quick_audio_var.get(), "无独立音频")
    video = _selected_video_option(window)
    mode = audio_control_mode(video, len(preview.audio_options))
    if mode == "embedded":
        audio_label = "视频已包含音频"
    elif mode == "none":
        audio_label = "无独立音频"
    summary_var.set(f"当前选择：{video_label}  ·  {audio_label}"[:240])


def _sync_audio_control(window) -> None:
    preview = getattr(window, "_quick_preview", None)
    if not isinstance(preview, quick.QuickPreview):
        return
    video = _selected_video_option(window)
    mode = audio_control_mode(video, len(preview.audio_options))
    hint_var = getattr(window, "_workbench_audio_hint_var", None)
    if mode == "embedded":
        window._quick_audio_combo.configure(state="disabled")
        if hint_var is not None:
            hint_var.set("当前视频已包含音频，无需再选择独立音轨。")
    elif mode == "separate":
        window._quick_audio_combo.configure(state="readonly")
        if hint_var is not None:
            hint_var.set("当前视频为独立视频流，可选择音频轨道后由 FFmpeg 合并。")
    else:
        window._quick_audio_combo.configure(state="disabled")
        if hint_var is not None:
            hint_var.set("当前解析结果没有独立音频轨道。")
    _update_format_summary(window)


def _show_parse_failure(window, generation: int, message: str) -> None:
    if not quick._window_exists(window) or generation != int(getattr(window, "_quick_parse_generation", 0)):
        return
    window._quick_parse_button.state(["!disabled"])
    quick._show_parse_error(window, message or "解析失败。")


def _parse_quick_url_async(window, engine_module) -> None:
    source_url = quick._text(window._quick_url_var.get())
    if not source_url:
        quick._show_parse_error(window, "请粘贴一个 HTTP(S) 媒体链接。")
        return

    generation = int(getattr(window, "_quick_parse_generation", 0)) + 1
    window._quick_parse_generation = generation
    window._quick_preview = None
    window._quick_parse_button.state(["disabled"])
    window._quick_download_button.state(["disabled"])
    window._quick_preview_panel.pack_forget()
    window._quick_state_var.set("正在后台校验公网链接…")
    browser = quick._browser_key(window._quick_browser_var.get())

    def worker() -> None:
        try:
            # validated_source_url may perform DNS resolution. Keep it off the Tk
            # main thread so weak networks cannot freeze the desktop UI.
            validated_url = engine_module._validated_source_url(source_url)
            result = bridge.parse_with_bundled_ytdlp(validated_url, browser)
            preview = quick.preview_from_parse_result(validated_url, result)
            error = "" if preview.has_exact_formats else "已识别页面，但没有可精确选择的视频/音频格式。"
        except Exception as exc:  # noqa: BLE001
            preview = None
            error = str(exc)

        def finish() -> None:
            if preview is None:
                _show_parse_failure(window, generation, error)
                return
            if not quick._window_exists(window) or generation != int(getattr(window, "_quick_parse_generation", 0)):
                return
            window._quick_parse_button.state(["!disabled"])
            window._quick_preview = preview
            window._quick_title_var.set(preview.title[:140])
            meta = f"{preview.platform} · {quick._human_duration(preview.duration_seconds)}"
            if preview.collection_count > 1:
                meta += f" · {preview.collection_count} 个项目（当前先下载第 1 项）"
            window._quick_meta_var.set(meta)
            quick._sync_format_controls(window, preview)
            _sync_audio_control(window)
            window._quick_preview_panel.pack(fill="x", pady=(10, 0))
            if preview.has_exact_formats:
                window._quick_download_button.state(["!disabled"])
                window._quick_state_var.set(
                    f"解析完成 · 视频 {len(preview.video_options)} 个格式 · 音频 {len(preview.audio_options)} 个格式"
                )
            else:
                window._quick_download_button.state(["disabled"])
                window._quick_state_var.set(error)

        try:
            window.after(0, finish)
        except Exception:
            pass

    threading.Thread(target=worker, name="GalaxyWorkbenchParse", daemon=True).start()


def _submit_with_phase(window, engine_module) -> None:
    _set_phase(window, 4)
    quick._submit_quick_download(window, engine_module)


def _install_flow_bar(window) -> None:
    panel = window._quick_download_panel
    children = panel.winfo_children()
    head = children[0] if children else None
    flow = ui.tk.Frame(panel, bg=ui.PANEL_2)
    if head is not None:
        flow.pack(fill="x", after=head, pady=(9, 0))
    else:
        flow.pack(fill="x", pady=(9, 0))
    widgets = []
    for index, text in enumerate(_PHASE_LABELS):
        label = ui._label(
            flow,
            text,
            size=7,
            weight="bold",
            color=ui.SUBTLE,
            bg=ui.PANEL_2,
            padx=8,
            pady=5,
        )
        label.pack(side="left", padx=(0 if index == 0 else 5, 0))
        widgets.append(label)
    window._workbench_phase_widgets = tuple(widgets)
    _set_phase(window, 1)


def _install_preview_summary(window) -> None:
    preview = window._quick_preview_panel
    children = preview.winfo_children()
    footer = children[-1] if children else None
    summary = ui.tk.Frame(preview, bg=ui.PANEL_3)
    if footer is not None:
        summary.pack(fill="x", before=footer, pady=(8, 0))
    else:
        summary.pack(fill="x", pady=(8, 0))

    window._workbench_format_summary_var = ui.tk.StringVar(
        value="解析后会显示真实 format_id 对应的清晰度、编码和音频组合。"
    )
    ui._label(
        summary,
        variable=window._workbench_format_summary_var,
        size=7,
        color=ui.CYAN,
        bg=ui.PANEL_3,
        wraplength=610,
        justify="left",
    ).pack(anchor="w")
    window._workbench_audio_hint_var = ui.tk.StringVar(value="选择视频格式后会自动判断是否需要独立音轨。")
    ui._label(
        summary,
        variable=window._workbench_audio_hint_var,
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_3,
        wraplength=610,
        justify="left",
    ).pack(anchor="w", pady=(2, 0))


def _enhance_quick_panel(window, engine_module) -> None:
    if not hasattr(window, "_quick_download_panel"):
        return
    panel = window._quick_download_panel
    panel.configure(padx=16, pady=14, highlightbackground=ui.BORDER)
    window._quick_url_entry.configure(font=("Segoe UI", 10))
    window._quick_parse_button.configure(text="解析并预览")
    window._quick_download_button.configure(text="下载 / 加入队列")

    _install_flow_bar(window)
    _install_preview_summary(window)

    window._quick_parse_button.configure(command=lambda: _parse_quick_url_async(window, engine_module))
    window._quick_url_entry.bind("<Return>", lambda _event: _parse_quick_url_async(window, engine_module))
    window._quick_download_button.configure(command=lambda: _submit_with_phase(window, engine_module))
    window._quick_video_combo.bind("<<ComboboxSelected>>", lambda _event: _sync_audio_control(window), add="+")
    window._quick_audio_combo.bind("<<ComboboxSelected>>", lambda _event: _update_format_summary(window), add="+")

    def on_state_change(*_args) -> None:
        _set_phase(window, workbench_phase_from_state(window._quick_state_var.get()))

    window._quick_state_var.trace_add("write", on_state_change)
    window._workbench_state_trace = on_state_change


def install_desktop_download_workbench(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_download_workbench_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-download-workbench",
        lambda window: _enhance_quick_panel(window, engine_module),
        order=45,
    )
    window_cls._galaxy_desktop_download_workbench_installed = True

    # Runtime engines already have the complete Job and queue contract here.
    # Keep the light hook-registry unit fixture compatible by installing the
    # protocol preview layer only when those capabilities are present.
    if hasattr(engine_module, "Job") and hasattr(window_cls, "submit_bridge_job"):
        from desktop_preview_handoff import install_desktop_preview_handoff

        install_desktop_preview_handoff(engine_module)

    # Clipboard monitoring is a presentation-layer capability. It is explicitly
    # opt-in and never parses/network-fetches clipboard content automatically.
    from desktop_clipboard import install_desktop_clipboard_monitor

    install_desktop_clipboard_monitor(engine_module)
    return window_cls


def run_desktop_download_workbench_self_test() -> None:
    assert workbench_phase_from_state("粘贴链接后点击解析") == 2
    assert workbench_phase_from_state("正在后台校验公网链接") == 2
    assert workbench_phase_from_state("解析完成 · 视频 8 个格式 · 音频 4 个格式") == 3
    assert workbench_phase_from_state("已加入等待队列") == 4
    assert audio_control_mode({"streamType": "muxed"}, 5) == "embedded"
    assert audio_control_mode({"streamType": "video-only"}, 5) == "separate"
    assert audio_control_mode({"streamType": "video-only"}, 0) == "none"

    from desktop_clipboard import run_desktop_clipboard_monitor_self_test
    from desktop_preview_handoff import run_desktop_preview_handoff_self_test

    run_desktop_preview_handoff_self_test()
    run_desktop_clipboard_monitor_self_test()

    class Window:
        @staticmethod
        def bridge_status(_window=None):
            return {}

    engine = SimpleNamespace(EngineWindow=Window)
    install_desktop_download_workbench(engine)
    assert "desktop-download-workbench" in registered_after_build_ui_hooks(Window)
    assert Window._galaxy_desktop_download_workbench_installed is True
    assert Window._galaxy_desktop_clipboard_monitor_installed is True