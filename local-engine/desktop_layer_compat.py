from __future__ import annotations

import tkinter as tk
from typing import Any

import desktop_ui as ui


def _window_exists(window: tk.Misc) -> bool:
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def install_desktop_layer_compat(engine_module):
    """Keep the v0.11-v0.13 desktop wrappers compatible with the v0.14 shell.

    The v0.14 base UI moved queue/history presentation into the unified Task
    Center and removed the old inline queue panel. The older enhancement layers
    still intentionally own history counts, pause state, settings and storage
    health, and therefore expect a few private anchors from the old shell.

    This adapter provides only those anchors. It does *not* restore the old
    inline queue UI or duplicate queue state. The real queue remains owned by
    job_queue.py / queue_controls.py and the visible queue remains Task Center.
    """
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_layer_compat_installed", False):
        return window_cls

    original_build = window_cls._build_ui

    # desktop_extras decorates this old renderer during installation. Task
    # Center no longer calls it, but keeping a harmless callable preserves the
    # layer contract while the old decoration is phased out incrementally.
    if not hasattr(ui, "_render_queue"):
        def _render_queue(_window, _pending: list[Any]) -> None:
            return None

        ui._render_queue = _render_queue  # type: ignore[attr-defined]

    # desktop_extras and desktop_runtime chain this hook. The base v0.14 shell
    # no longer needed it, so recreate it as a lightweight state refresh hook.
    if not hasattr(window_cls, "_galaxy_queue_tick"):
        def queue_tick(window) -> None:
            pending = getattr(window, "pending_jobs", [])
            try:
                waiting = len(pending)
            except TypeError:
                waiting = 0
            paused = bool(getattr(window, "queue_paused", False))
            summary = f"等待 {waiting} 项"
            if paused:
                summary += " · 暂停"
            variable = getattr(window, "_queue_summary_var", None)
            if variable is not None:
                try:
                    variable.set(summary)
                except tk.TclError:
                    pass

        window_cls._galaxy_queue_tick = queue_tick

    def build_ui(window) -> None:
        original_build(window)

        # v0.14 creates Task Center entry buttons in the side panel. v0.11 and
        # v0.12 add their richer replacements later in the wrapper chain. Hide
        # the base placeholders but keep the widget/master as a layout anchor.
        queue_anchor = getattr(window, "_queue_manager_button", None)
        if queue_anchor is not None:
            try:
                queue_anchor.pack_forget()
            except tk.TclError:
                pass
            window._queue_clear_button = queue_anchor

        history_anchor = getattr(window, "_history_button", None)
        if history_anchor is not None:
            try:
                history_anchor.pack_forget()
            except tk.TclError:
                pass

        # Some v0.11 pause-state code still writes the old count variable. It is
        # no longer rendered, but retaining the variable prevents a paused queue
        # from short-circuiting the visible summary update.
        if not hasattr(window, "_queue_count_var"):
            window._queue_count_var = tk.StringVar(master=window, value="当前 0 · 等待 0")

        def tick() -> None:
            if not _window_exists(window):
                return
            refresh = getattr(window, "_galaxy_queue_tick", None)
            if callable(refresh):
                try:
                    refresh()
                except tk.TclError:
                    return
            try:
                window.after(900, tick)
            except tk.TclError:
                return

        window.after(0, tick)

    window_cls._build_ui = build_ui
    window_cls._galaxy_desktop_layer_compat_installed = True
    engine_module._galaxy_desktop_layer_compat_installed = True
    return window_cls
