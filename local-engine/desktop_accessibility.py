from __future__ import annotations

import os
import tkinter as tk
from collections.abc import Iterator
from typing import Any

_REDUCED_MOTION_VALUES = frozenset({"1", "true", "yes", "on", "reduce", "reduced"})


def reduced_motion_requested(environ: dict[str, str] | None = None) -> bool:
    """Return the explicit reduced-motion preference for Desktop UI.

    Galaxy's Tk desktop intentionally avoids decorative animation. This flag is
    still exposed as a runtime contract so future motion must opt out when the
    user requests reduced motion. The environment override is deterministic on
    Windows/macOS/Linux and works for portable builds where a desktop settings
    service may be unavailable.
    """
    values = os.environ if environ is None else environ
    raw = str(values.get("GALAXY_REDUCE_MOTION") or values.get("REDUCE_MOTION") or "").strip().lower()
    return raw in _REDUCED_MOTION_VALUES


def _walk_widgets(widget: tk.Misc) -> Iterator[tk.Misc]:
    for child in widget.winfo_children():
        yield child
        yield from _walk_widgets(child)


def _widget_accepts_focus(widget: tk.Misc) -> bool:
    try:
        state = str(widget.cget("state")) if "state" in widget.keys() else "normal"
    except tk.TclError:
        return False
    if state in {"disabled", "hidden"}:
        return False
    try:
        takefocus = str(widget.cget("takefocus")) if "takefocus" in widget.keys() else ""
    except tk.TclError:
        return False
    if takefocus in {"0", "false", "False"}:
        return False
    return isinstance(widget, (tk.Entry, tk.Button, tk.Checkbutton, tk.Radiobutton, tk.Listbox, tk.Text, tk.Scale, tk.Spinbox, tk.Canvas)) or bool(takefocus)


def focus_first_control(dialog: tk.Misc) -> tk.Misc | None:
    """Focus the first enabled keyboard-focusable descendant, if any."""
    for widget in _walk_widgets(dialog):
        if not _widget_accepts_focus(widget):
            continue
        try:
            if not widget.winfo_viewable():
                continue
            widget.focus_set()
            return widget
        except tk.TclError:
            continue
    return None


def _invoke_dialog_close(top: tk.Toplevel) -> None:
    callback = getattr(top, "_galaxy_escape_handler", None)
    if callable(callback):
        callback()
        return
    # Respect a dialog's WM_DELETE_WINDOW handler so Escape follows the same
    # cleanup path as the window close button (important for transfer sessions,
    # worker handles, temporary servers, and other resource-owning dialogs).
    try:
        protocol_command = str(top.protocol("WM_DELETE_WINDOW") or "").strip()
    except tk.TclError:
        protocol_command = ""
    if protocol_command:
        top.tk.call(protocol_command)
    else:
        top.destroy()


def close_dialog_from_escape(event: Any) -> str | None:
    """Close the containing Toplevel unless that dialog explicitly opts out."""
    widget = getattr(event, "widget", None)
    if widget is None:
        return None
    try:
        top = widget.winfo_toplevel()
    except (AttributeError, tk.TclError):
        return None
    if not isinstance(top, tk.Toplevel):
        return None
    if bool(getattr(top, "_galaxy_escape_disabled", False)):
        return None
    try:
        _invoke_dialog_close(top)
    except tk.TclError:
        return None
    return "break"


def _focus_dialog_on_map(event: Any) -> None:
    widget = getattr(event, "widget", None)
    if not isinstance(widget, tk.Toplevel):
        return
    if bool(getattr(widget, "_galaxy_initial_focus_disabled", False)):
        return
    try:
        widget.after_idle(lambda: focus_first_control(widget))
    except tk.TclError:
        return


def configure_dialog_accessibility(
    dialog: tk.Toplevel,
    *,
    close_handler=None,
    focus_initial: bool = True,
) -> tk.Toplevel:
    """Apply the per-dialog keyboard contract to an already-created Toplevel."""
    if close_handler is not None:
        dialog._galaxy_escape_handler = close_handler  # type: ignore[attr-defined]
    if not focus_initial:
        dialog._galaxy_initial_focus_disabled = True  # type: ignore[attr-defined]
    dialog.bind("<Escape>", close_dialog_from_escape, add="+")
    if focus_initial:
        try:
            dialog.after_idle(lambda: focus_first_control(dialog))
        except tk.TclError:
            pass
    return dialog


def install_desktop_accessibility(window: tk.Misc) -> None:
    """Install one global keyboard/motion contract for every Desktop Toplevel."""
    if bool(getattr(window, "_galaxy_accessibility_installed", False)):
        return
    window._galaxy_accessibility_installed = True  # type: ignore[attr-defined]
    window._galaxy_reduced_motion = reduced_motion_requested()  # type: ignore[attr-defined]
    window.bind_class("Toplevel", "<Escape>", close_dialog_from_escape, add="+")
    window.bind_class("Toplevel", "<Map>", _focus_dialog_on_map, add="+")


def run_self_test() -> None:
    assert reduced_motion_requested({"GALAXY_REDUCE_MOTION": "1"})
    assert reduced_motion_requested({"REDUCE_MOTION": "true"})
    assert reduced_motion_requested({"GALAXY_REDUCE_MOTION": "YES"})
    assert not reduced_motion_requested({})
    assert not reduced_motion_requested({"GALAXY_REDUCE_MOTION": "0"})
    assert close_dialog_from_escape(object()) is None
