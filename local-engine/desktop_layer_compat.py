from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import desktop_ui as ui
import external_ytdlp
import media_policy


@dataclass
class _LegacyMediaPreferences:
    clip_start: str | None = None
    clip_end: str | None = None
    split_chapters: bool = False
    include_subtitle: bool = False
    include_auto_subtitles: bool = False
    subtitle_language: str | None = None
    audio_language: str | None = None
    sponsorblock_categories: tuple[str, ...] = ()
    prefer_aria2c: bool = False


def load_legacy_preferences() -> _LegacyMediaPreferences:
    raw = media_policy.load_preferences()
    subtitle_languages = list(raw.get("subtitleLanguages") or [])
    audio_languages = list(raw.get("audioLanguages") or [])
    return _LegacyMediaPreferences(
        clip_start=str(raw.get("segmentStart") or "") or None,
        clip_end=str(raw.get("segmentEnd") or "") or None,
        split_chapters=bool(raw.get("splitChapters", False)),
        include_subtitle=bool(raw.get("includeSubtitle", False)),
        include_auto_subtitles=str(raw.get("subtitleMode") or "both") in {"auto", "both"},
        subtitle_language=subtitle_languages[0] if subtitle_languages else None,
        audio_language=audio_languages[0] if audio_languages else None,
        sponsorblock_categories=tuple(raw.get("sponsorBlockCategories") or ()),
        prefer_aria2c=bool(raw.get("useAria2c", False)),
    )


def save_legacy_preferences(preferences: _LegacyMediaPreferences) -> dict[str, Any]:
    subtitle_mode = "both" if preferences.include_auto_subtitles else "manual"
    return media_policy.save_preferences(
        {
            "segmentStart": preferences.clip_start or "",
            "segmentEnd": preferences.clip_end or "",
            "splitChapters": bool(preferences.split_chapters),
            "includeSubtitle": bool(preferences.include_subtitle),
            "subtitleMode": subtitle_mode,
            "subtitleLanguages": [preferences.subtitle_language] if preferences.subtitle_language else [],
            "audioLanguages": [preferences.audio_language] if preferences.audio_language else [],
            "sponsorBlockCategories": list(preferences.sponsorblock_categories),
            "useAria2c": bool(preferences.prefer_aria2c),
        }
    )


def _install_media_preference_bridge(engine_module) -> None:
    # v0.10 desktop_ui still calls an object-oriented preference API while
    # v0.14 media_policy stores a validated dict schema. Keep that translation
    # in one place instead of leaking legacy fields back into media_policy.
    ui.load_preferences = load_legacy_preferences
    ui.save_preferences = save_legacy_preferences
    ui.aria2c_available = lambda: media_policy.aria2c_available(engine_module)


def _install_dependency_probe_bridge(engine_module) -> None:
    # The older visual shell expects these probes directly on engine.py, while
    # v0.14 moved yt-dlp discovery into external_ytdlp.py.
    if not hasattr(engine_module, "external_ytdlp_available"):
        engine_module.external_ytdlp_available = lambda: (
            external_ytdlp.external_ytdlp_path(engine_module.app_dir()) is not None
        )
    if not hasattr(engine_module, "ffmpeg_available"):
        engine_module.ffmpeg_available = lambda: engine_module.ffmpeg_dir() is not None


def _install_queue_anchor_bridge(window_cls) -> None:
    # v0.11-v0.13 wrappers decorate the old periodic queue hook. 0.14 moved the
    # visible queue into Task Center, but keeping a no-op refresh seam allows the
    # wrappers to synchronize history/storage state without restoring a second
    # queue implementation.
    if not hasattr(window_cls, "_galaxy_queue_tick"):
        def queue_tick(window) -> None:
            try:
                window.after(650, window._galaxy_queue_tick)
            except Exception:
                pass
        window_cls._galaxy_queue_tick = queue_tick


def install_desktop_layer_compat(engine_module):
    """Bridge legacy v0.10-v0.13 desktop wrappers onto the v0.14 engine API."""
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_layer_compat_installed", False):
        return window_cls

    _install_media_preference_bridge(engine_module)
    _install_dependency_probe_bridge(engine_module)
    _install_queue_anchor_bridge(window_cls)

    original_build = window_cls._build_ui

    def build_ui(window) -> None:
        original_build(window)
        # Older wrappers expect the inline queue widgets to exist. The real queue
        # remains Task Center-backed; these hidden anchors only satisfy the stable
        # integration contract while the wrappers are flattened in a later release.
        import tkinter as tk

        if not hasattr(window, "_queue_panel"):
            window._queue_panel = tk.Frame(window)
        if not hasattr(window, "_queue_count_var"):
            window._queue_count_var = tk.StringVar(master=window, value="当前 0 · 等待 0")
        if not hasattr(window, "_queue_clear_button"):
            window._queue_clear_button = ui.ActionButton(
                window,
                text="清空",
                command=lambda: None,
                kind="ghost",
                compact=True,
            )
            # Do not pack this compatibility-only widget.
        if not hasattr(window, "_queue_summary_var"):
            window._queue_summary_var = tk.StringVar(master=window, value="等待 0 项")

    window_cls._build_ui = build_ui
    window_cls._galaxy_desktop_layer_compat_installed = True
    engine_module._galaxy_desktop_layer_compat_installed = True
    return window_cls
