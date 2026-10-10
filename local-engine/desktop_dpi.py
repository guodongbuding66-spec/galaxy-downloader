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
    """Keep the native workbench entirely inside the available display.

    V1.7 originally requested 1320x880 with a 1100x760 minimum. On small
    laptops, VMs and GitHub's Windows desktop this can exceed the usable screen,
    clipping the queue rail or bottom actions. Fit the final window after all
    desktop hooks are installed while keeping a practical lower bound.
    """
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


def apply_native_dpi(window: tk.Misc) -> None:
    """Respect Windows DPI and then fit the workbench to the visible screen."""
    scaling = _windows_scaling(window)
    if scaling is not None:
        try:
            window.tk.call("tk", "scaling", scaling)
            window.update_idletasks()
        except tk.TclError:
            pass
    _fit_window_to_screen(window)


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
    assert callable(install_native_dpi_policy)


if __name__ == "__main__":
    run_self_test()
    print("Native DPI policy self-test passed")
