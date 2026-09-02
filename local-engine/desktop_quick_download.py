from __future__ import annotations

import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Any

import bridge
import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook

_BROWSER_LABELS = {
    "不使用浏览器登录": "none",
    "Microsoft Edge": "edge",
    "Google Chrome": "chrome",
    "Firefox": "firefox",
    "Brave": "brave",
}
_BROWSER_BY_KEY = {value: label for label, value in _BROWSER_LABELS.items()}


@dataclass(frozen=True)
class QuickPreview:
    source_url: str
    title: str
    platform: str
    duration_seconds: float | None
    video_options: tuple[dict[str, Any], ...]
    audio_options: tuple[dict[str, Any], ...]
    default_video_id: str | None
    default_audio_id: str | None
    collection_count: int

    @property
    def has_exact_formats(self) -> bool:
        return bool(self.video_options or self.audio_options)


def _text(value: object, fallback: str = "") -> str:
    text = " ".join(str(value or "").split()).strip()
    return text or fallback


def _safe_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "时长未知"
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _human_size(value: object) -> str | None:
    try:
        size = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if size <= 0:
        return None
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return None


def _option_label(option: dict[str, Any]) -> str:
    label = _text(option.get("label"), _text(option.get("formatId"), "未知格式"))
    size = _human_size(option.get("filesize") or option.get("filesizeApprox"))
    return f"{label} · {size}" if size else label


def _valid_public_option(option: object, expected_prefix: str) -> dict[str, Any] | None:
    if not isinstance(option, dict):
        return None
    option_id = _text(option.get("id"))
    format_id = _text(option.get("formatId"))
    if not option_id.startswith(f"{expected_prefix}:") or not format_id:
        return None
    # The Local Bridge owns format-id validation. The desktop treats this
    # object as an opaque identity and never turns labels or URLs into selectors.
    return dict(option)


def preview_from_parse_result(source_url: str, result: object) -> QuickPreview:
    if not isinstance(result, dict) or not result.get("success"):
        if isinstance(result, dict):
            message = _text(result.get("error") or result.get("message"), "无法解析这个链接。")
            code = _text(result.get("code"))
            if code:
                message = f"{code}: {message}"
        else:
            message = "本地解析器返回了无效结果。"
        raise ValueError(message)

    data = result.get("data")
    if not isinstance(data, dict):
        raise ValueError("解析成功但没有可预览的媒体信息。")

    catalog = data.get("formatCatalog") if isinstance(data.get("formatCatalog"), dict) else {}
    videos = tuple(
        item
        for raw in (catalog.get("videoOptions") if isinstance(catalog, dict) else []) or []
        if (item := _valid_public_option(raw, "video")) is not None
    )
    audios = tuple(
        item
        for raw in (catalog.get("audioOptions") if isinstance(catalog, dict) else []) or []
        if (item := _valid_public_option(raw, "audio")) is not None
    )
    default_video_id = _text(catalog.get("defaultVideoId")) if isinstance(catalog, dict) else ""
    default_audio_id = _text(catalog.get("defaultAudioId")) if isinstance(catalog, dict) else ""
    if default_video_id and not any(_text(item.get("id")) == default_video_id for item in videos):
        default_video_id = ""
    if default_audio_id and not any(_text(item.get("id")) == default_audio_id for item in audios):
        default_audio_id = ""

    return QuickPreview(
        source_url=_text(source_url),
        title=_text(data.get("title"), "未命名媒体"),
        platform=_text(data.get("platform"), "unknown"),
        duration_seconds=_safe_float(data.get("duration")),
        video_options=videos,
        audio_options=audios,
        default_video_id=default_video_id or (_text(videos[0].get("id")) if videos else None),
        default_audio_id=default_audio_id or (_text(audios[0].get("id")) if audios else None),
        collection_count=max(1, int(_safe_float(data.get("collectionCount")) or 1)),
    )


def _option_by_id(options: tuple[dict[str, Any], ...], option_id: str | None) -> dict[str, Any] | None:
    target = _text(option_id)
    return next((item for item in options if _text(item.get("id")) == target), None)


def build_quick_download_payload(
    preview: QuickPreview,
    *,
    selected_video_id: str | None,
    selected_audio_id: str | None,
    browser: str = "none",
) -> dict[str, Any]:
    video = _option_by_id(preview.video_options, selected_video_id)
    audio = _option_by_id(preview.audio_options, selected_audio_id)
    if preview.video_options and video is None:
        raise ValueError("请选择一个有效的视频格式。")
    if not preview.video_options and preview.audio_options and audio is None:
        raise ValueError("请选择一个有效的音频格式。")
    if video is None and audio is None:
        raise ValueError("这个解析结果没有可用于本机下载的真实媒体格式。")

    payload: dict[str, Any] = {
        "sourceUrl": preview.source_url,
        "browser": browser if browser in _BROWSER_BY_KEY else "none",
        "collectionMode": "single",
        "includeSubtitle": False,
        "includeCover": False,
        "skipPreviouslyDownloaded": False,
        "displayTitle": preview.title[:120],
    }

    if video is not None:
        video_format_id = _text(video.get("formatId"))
        stream_type = _text(video.get("streamType"))
        muxed = stream_type == "muxed"
        payload["videoFormatId"] = video_format_id
        payload["selectedVideoHasAudio"] = muxed
        height = video.get("height")
        payload["videoQuality"] = f"{int(height)}p" if isinstance(height, (int, float)) and height > 0 else video_format_id
        if muxed:
            payload["includeAudio"] = True
            payload["audioFormatId"] = None
        elif audio is not None:
            payload["includeAudio"] = True
            payload["audioFormatId"] = _text(audio.get("formatId"))
            abr = audio.get("audioBitrate")
            payload["audioQuality"] = str(int(round(float(abr)))) if isinstance(abr, (int, float)) and abr > 0 else _text(audio.get("formatId"), "best")
        else:
            payload["includeAudio"] = False
            payload["audioFormatId"] = None
    else:
        payload["includeAudio"] = True
        payload["audioFormatId"] = _text(audio.get("formatId")) if audio else None
        payload["videoFormatId"] = None
        payload["selectedVideoHasAudio"] = False
        payload["videoQuality"] = "audio-only"
        abr = audio.get("audioBitrate") if audio else None
        payload["audioQuality"] = str(int(round(float(abr)))) if isinstance(abr, (int, float)) and abr > 0 else _text(audio.get("formatId") if audio else "", "best")
    return payload


def _submission_result(result: object) -> tuple[bool, str, str]:
    if isinstance(result, tuple) and len(result) >= 2:
        return bool(result[0]), _text(result[1]), ""
    accepted = bool(getattr(result, "accepted", False))
    message = _text(getattr(result, "message", ""))
    code = _text(getattr(result, "code", ""))
    return accepted, message, code


def _window_exists(window: tk.Misc | None) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def _browser_key(label: str) -> str:
    return _BROWSER_LABELS.get(_text(label), "none")


def _show_parse_error(window, message: str) -> None:
    window._quick_state_var.set(message[:280])
    window._quick_download_button.state(["disabled"])
    window._quick_preview_panel.pack_forget()


def _sync_format_controls(window, preview: QuickPreview) -> None:
    video_display = {_option_label(item): _text(item.get("id")) for item in preview.video_options}
    audio_display = {_option_label(item): _text(item.get("id")) for item in preview.audio_options}
    window._quick_video_display = video_display
    window._quick_audio_display = audio_display
    window._quick_video_combo.configure(values=tuple(video_display))
    window._quick_audio_combo.configure(values=tuple(audio_display))

    def default_label(mapping: dict[str, str], target_id: str | None) -> str:
        return next((label for label, option_id in mapping.items() if option_id == target_id), next(iter(mapping), ""))

    window._quick_video_var.set(default_label(video_display, preview.default_video_id))
    window._quick_audio_var.set(default_label(audio_display, preview.default_audio_id))

    if video_display:
        window._quick_video_combo.configure(state="readonly")
    else:
        window._quick_video_combo.configure(state="disabled")
    if audio_display:
        window._quick_audio_combo.configure(state="readonly")
    else:
        window._quick_audio_combo.configure(state="disabled")


def _submit_quick_download(window, engine_module) -> None:
    preview = getattr(window, "_quick_preview", None)
    if not isinstance(preview, QuickPreview):
        _show_parse_error(window, "请先解析链接并选择格式。")
        return
    video_id = getattr(window, "_quick_video_display", {}).get(window._quick_video_var.get())
    audio_id = getattr(window, "_quick_audio_display", {}).get(window._quick_audio_var.get())
    browser = _browser_key(window._quick_browser_var.get())
    try:
        payload = build_quick_download_payload(
            preview,
            selected_video_id=video_id,
            selected_audio_id=audio_id,
            browser=browser,
        )
    except ValueError as exc:
        _show_parse_error(window, str(exc))
        return

    window._quick_download_button.state(["disabled"])
    window._quick_parse_button.state(["disabled"])
    window._quick_state_var.set("正在提交到本机下载队列…")

    def worker() -> None:
        try:
            result = window.submit_bridge_job(payload)
            accepted, message, code = _submission_result(result)
        except Exception as exc:  # noqa: BLE001
            accepted, message, code = False, str(exc), ""

        def finish() -> None:
            if not _window_exists(window):
                return
            window._quick_parse_button.state(["!disabled"])
            window._quick_download_button.state(["!disabled"])
            if accepted:
                prefix = "已加入等待队列" if code == "QUEUED" else "已开始下载"
                window._quick_state_var.set(f"{prefix} · {message or preview.title}"[:280])
            else:
                window._quick_state_var.set(f"提交失败{f' ({code})' if code else ''}：{message or '未知错误'}"[:280])

        try:
            window.after(0, finish)
        except tk.TclError:
            pass

    threading.Thread(target=worker, name="GalaxyQuickSubmit", daemon=True).start()


def _parse_quick_url(window, engine_module) -> None:
    source_url = _text(window._quick_url_var.get())
    if not source_url:
        _show_parse_error(window, "请粘贴一个 HTTP(S) 媒体链接。")
        return
    try:
        source_url = engine_module._validated_source_url(source_url)
    except ValueError as exc:
        _show_parse_error(window, str(exc))
        return

    generation = int(getattr(window, "_quick_parse_generation", 0)) + 1
    window._quick_parse_generation = generation
    window._quick_preview = None
    window._quick_parse_button.state(["disabled"])
    window._quick_download_button.state(["disabled"])
    window._quick_preview_panel.pack_forget()
    window._quick_state_var.set("正在本机解析媒体信息和真实格式…")
    browser = _browser_key(window._quick_browser_var.get())

    def worker() -> None:
        try:
            result = bridge.parse_with_bundled_ytdlp(source_url, browser)
            preview = preview_from_parse_result(source_url, result)
            error = "" if preview.has_exact_formats else "已识别页面，但没有可精确选择的视频/音频格式。"
        except Exception as exc:  # noqa: BLE001
            preview = None
            error = str(exc)

        def finish() -> None:
            if not _window_exists(window) or generation != int(getattr(window, "_quick_parse_generation", 0)):
                return
            window._quick_parse_button.state(["!disabled"])
            if preview is None:
                _show_parse_error(window, error or "解析失败。")
                return
            window._quick_preview = preview
            window._quick_title_var.set(preview.title[:140])
            meta = f"{preview.platform} · {_human_duration(preview.duration_seconds)}"
            if preview.collection_count > 1:
                meta += f" · {preview.collection_count} 个项目（当前先下载第 1 项）"
            window._quick_meta_var.set(meta)
            _sync_format_controls(window, preview)
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
        except tk.TclError:
            pass

    threading.Thread(target=worker, name="GalaxyQuickParse", daemon=True).start()


def _paste_quick_url(window) -> None:
    try:
        value = _text(window.clipboard_get())
    except tk.TclError:
        value = ""
    if value:
        window._quick_url_var.set(value)
        window._quick_state_var.set("链接已粘贴。点击“解析预览”后才会联网解析。")


def _build_quick_panel(window, engine_module) -> None:
    main = window.cancel_button.master.master
    first_child = main.winfo_children()[0] if main.winfo_children() else None
    panel = tk.Frame(main, bg=ui.PANEL_2, padx=14, pady=12, highlightthickness=1, highlightbackground=ui.BORDER_SOFT)
    if first_child is not None:
        panel.pack(fill="x", before=first_child, pady=(0, 14))
    else:
        panel.pack(fill="x", pady=(0, 14))
    window._quick_download_panel = panel

    head = tk.Frame(panel, bg=ui.PANEL_2)
    head.pack(fill="x")
    ui._label(head, "快速下载", size=10, weight="bold", bg=ui.PANEL_2).pack(side="left")
    ui._label(head, "粘贴 → 解析 → 选真实格式 → 下载", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(side="right")

    row = tk.Frame(panel, bg=ui.PANEL_2)
    row.pack(fill="x", pady=(9, 0))
    row.grid_columnconfigure(0, weight=1)
    window._quick_url_var = tk.StringVar()
    entry = tk.Entry(
        row,
        textvariable=window._quick_url_var,
        font=("Segoe UI", 9),
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
    )
    entry.grid(row=0, column=0, sticky="ew", ipady=7)
    window._quick_url_entry = entry
    ui.ActionButton(row, text="粘贴", command=lambda: _paste_quick_url(window), kind="ghost", compact=True).grid(row=0, column=1, padx=(7, 0))
    window._quick_parse_button = ui.ActionButton(
        row,
        text="解析预览",
        command=lambda: _parse_quick_url(window, engine_module),
        kind="primary",
        compact=True,
    )
    window._quick_parse_button.grid(row=0, column=2, padx=(7, 0))
    entry.bind("<Return>", lambda _event: _parse_quick_url(window, engine_module))

    options = tk.Frame(panel, bg=ui.PANEL_2)
    options.pack(fill="x", pady=(8, 0))
    ui._label(options, "登录环境", size=7, color=ui.MUTED, bg=ui.PANEL_2).pack(side="left")
    window._quick_browser_var = tk.StringVar(value=_BROWSER_BY_KEY["none"])
    ttk.Combobox(
        options,
        textvariable=window._quick_browser_var,
        values=tuple(_BROWSER_LABELS),
        state="readonly",
        width=18,
        style="Galaxy.TCombobox",
    ).pack(side="left", padx=(7, 10))
    ui._label(
        options,
        "默认不读取浏览器 Cookie；只有你主动选择登录浏览器并解析时才尝试。",
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(side="left")

    window._quick_state_var = tk.StringVar(value="粘贴链接后点击解析。普通启动和剪贴板读取不会自动联网。")
    ui._label(
        panel,
        variable=window._quick_state_var,
        size=7,
        color=ui.CYAN,
        bg=ui.PANEL_2,
        wraplength=650,
        justify="left",
    ).pack(anchor="w", pady=(7, 0))

    preview_panel = tk.Frame(panel, bg=ui.PANEL_3, padx=12, pady=10, highlightthickness=1, highlightbackground=ui.BORDER)
    window._quick_preview_panel = preview_panel
    window._quick_title_var = tk.StringVar()
    window._quick_meta_var = tk.StringVar()
    ui._label(preview_panel, variable=window._quick_title_var, size=10, weight="bold", bg=ui.PANEL_3, wraplength=620, justify="left").pack(anchor="w")
    ui._label(preview_panel, variable=window._quick_meta_var, size=7, color=ui.MUTED, bg=ui.PANEL_3).pack(anchor="w", pady=(3, 8))

    format_row = tk.Frame(preview_panel, bg=ui.PANEL_3)
    format_row.pack(fill="x")
    format_row.grid_columnconfigure(1, weight=1)
    format_row.grid_columnconfigure(3, weight=1)
    ui._label(format_row, "视频", size=7, color=ui.SUBTLE, bg=ui.PANEL_3).grid(row=0, column=0, sticky="w")
    window._quick_video_var = tk.StringVar()
    window._quick_video_combo = ttk.Combobox(format_row, textvariable=window._quick_video_var, state="disabled", style="Galaxy.TCombobox")
    window._quick_video_combo.grid(row=0, column=1, sticky="ew", padx=(6, 12))
    ui._label(format_row, "音频", size=7, color=ui.SUBTLE, bg=ui.PANEL_3).grid(row=0, column=2, sticky="w")
    window._quick_audio_var = tk.StringVar()
    window._quick_audio_combo = ttk.Combobox(format_row, textvariable=window._quick_audio_var, state="disabled", style="Galaxy.TCombobox")
    window._quick_audio_combo.grid(row=0, column=3, sticky="ew", padx=(6, 0))

    footer = tk.Frame(preview_panel, bg=ui.PANEL_3)
    footer.pack(fill="x", pady=(9, 0))
    ui._label(
        footer,
        "格式来自本机 yt-dlp 的真实 format_id；不会用临时 CDN URL 充当格式身份。",
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_3,
    ).pack(side="left")
    window._quick_download_button = ui.ActionButton(
        footer,
        text="下载所选格式",
        command=lambda: _submit_quick_download(window, engine_module),
        kind="primary",
        compact=True,
    )
    window._quick_download_button.pack(side="right")
    window._quick_download_button.state(["disabled"])

    window._quick_preview = None
    window._quick_video_display = {}
    window._quick_audio_display = {}
    window._quick_parse_generation = 0


def install_desktop_quick_download(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_quick_download_installed", False):
        return window_cls

    register_after_build_ui_hook(
        window_cls,
        "desktop-quick-download",
        lambda window: _build_quick_panel(window, engine_module),
        order=40,
    )
    window_cls._galaxy_desktop_quick_download_installed = True
    return window_cls


def run_desktop_quick_download_self_test() -> None:
    result = {
        "success": True,
        "data": {
            "title": "Example",
            "platform": "youtube",
            "duration": 61,
            "formatCatalog": {
                "videoOptions": [
                    {
                        "id": "video:137",
                        "formatId": "137",
                        "label": "1080p · AVC · MP4",
                        "streamType": "video-only",
                        "height": 1080,
                    }
                ],
                "audioOptions": [
                    {
                        "id": "audio:251",
                        "formatId": "251",
                        "label": "160 kbps · OPUS · WEBM",
                        "streamType": "audio-only",
                        "audioBitrate": 160,
                    }
                ],
                "defaultVideoId": "video:137",
                "defaultAudioId": "audio:251",
            },
        },
    }
    preview = preview_from_parse_result("https://example.test/watch", result)
    payload = build_quick_download_payload(
        preview,
        selected_video_id="video:137",
        selected_audio_id="audio:251",
    )
    assert payload["videoFormatId"] == "137"
    assert payload["audioFormatId"] == "251"
    assert "downloadUrl" not in str(payload)
