from __future__ import annotations

import os
import tkinter as tk

from desktop_hooks import register_after_build_ui_hook


def _windows_scaling(window: tk.Misc) -> float | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        hwnd = int(window.winfo_id())
        dpi = int(ctypes.windll.user32.GetDpiForWindow(hwnd))
    except Exception:
        return None
    if dpi <= 0:
        return None
    return max(1.0, min(4.0, dpi / 72.0))


def _fit_window_to_screen(window: tk.Misc) -> None:
    """Keep the native workbench entirely inside the available display."""
    try:
        screen_w = max(640, int(window.winfo_screenwidth()))
        screen_h = max(560, int(window.winfo_screenheight()))
    except tk.TclError:
        return

    horizontal_margin = 24
    vertical_margin = 48
    available_w = max(640, screen_w - horizontal_margin)
    available_h = max(560, screen_h - vertical_margin)
    target_w = min(1320, available_w)
    target_h = min(880, available_h)

    min_w = min(960, target_w)
    min_h = min(680, target_h)
    try:
        window.minsize(min_w, min_h)
        x = max(0, (screen_w - target_w) // 2)
        y = max(0, (screen_h - target_h) // 2)
        window.geometry(f"{target_w}x{target_h}+{x}+{y}")
        window.update_idletasks()
    except tk.TclError:
        return


def _responsive_header(window: tk.Misc) -> None:
    """Wrap the secondary toolbar under the brand when width is constrained.

    Several optional desktop modules append actions beside “复制诊断”. Keeping
    all of them on the same row as the brand clipped the right-most buttons on
    1000–1100px work areas. Re-flowing the existing native controls preserves
    every command and keyboard target without creating a second toolbar API.
    """
    copy_button = getattr(window, "_copy_diag_button", None)
    if copy_button is None:
        return
    try:
        actions = copy_button.master
        header = actions.master
        siblings = [child for child in header.winfo_children() if child is not actions]
        identity = siblings[0] if siblings else None
        width = int(window.winfo_width())
        if width <= 1160 and identity is not None:
            actions.pack_forget()
            identity.pack_forget()
            identity.pack(side="top", fill="x", anchor="w")
            actions.pack(side="top", fill="x", anchor="w", pady=(12, 0))
        elif identity is not None:
            actions.pack_forget()
            identity.pack_forget()
            identity.pack(side="left", fill="x", expand=True)
            actions.pack(side="right", anchor="center")
        window.update_idletasks()
    except tk.TclError:
        return


def _polish_compact_controls(window: tk.Misc) -> None:
    """Remove small-screen text clipping without changing feature behavior."""
    gallery = getattr(window, "_gallery_dl_fallback_button", None)
    if gallery is not None:
        try:
            gallery.configure(text="gallery-dl")
        except tk.TclError:
            pass

    # The former all-caps LOCAL chip was visually louder than its importance.
    # Keep the local-only cue, but in normal sentence-style UI copy.
    panel = getattr(window, "_quick_download_panel", None)
    if panel is None:
        return

    def visit(widget: tk.Misc) -> None:
        try:
            if widget.winfo_class() == "Label" and str(widget.cget("text")) == "LOCAL":
                widget.configure(text="本机")
            for child in widget.winfo_children():
                visit(child)
        except tk.TclError:
            return

    visit(panel)


def apply_native_dpi(window: tk.Misc) -> None:
    """Respect Windows DPI, fit the window, then adapt the native layout."""
    scaling = _windows_scaling(window)
    if scaling is not None:
        try:
            window.tk.call("tk", "scaling", scaling)
            window.update_idletasks()
        except tk.TclError:
            pass
    _fit_window_to_screen(window)
    _responsive_header(window)
    _polish_compact_controls(window)


def install_native_dpi_policy(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_native_dpi_installed", False):
        return window_cls
    register_after_build_ui_hook(window_cls, "native-dpi", apply_native_dpi, order=1000)
    window_cls._galaxy_native_dpi_installed = True
    return window_cls


def run_self_test() -> None:
    assert callable(apply_native_dpi)
    assert callable(_fit_window_to_screen)
    assert callable(_responsive_header)
    assert callable(_polish_compact_controls)
    assert callable(install_native_dpi_policy)


if __name__ == "__main__":
    run_self_test()
    print("Native DPI policy self-test passed")
