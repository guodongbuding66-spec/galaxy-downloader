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


def apply_native_dpi(window: tk.Misc) -> None:
    """Restore Windows DPI-aware Tk scaling after legacy UI composition.

    V1.7's visual layer previously forced `tk scaling` to 1.0, which makes text
    and controls physically too small at 125/150/200% Windows display scaling.
    The application now derives Tk's point-to-pixel scale from the real native
    window DPI. On other platforms Tk keeps its own default.
    """
    scaling = _windows_scaling(window)
    if scaling is None:
        return
    try:
        window.tk.call("tk", "scaling", scaling)
        window.update_idletasks()
    except tk.TclError:
        return


def install_native_dpi_policy(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_native_dpi_installed", False):
        return window_cls
    register_after_build_ui_hook(window_cls, "native-dpi", apply_native_dpi, order=1000)
    window_cls._galaxy_native_dpi_installed = True
    return window_cls


def run_self_test() -> None:
    assert callable(apply_native_dpi)
    assert callable(install_native_dpi_policy)


if __name__ == "__main__":
    run_self_test()
    print("Native DPI policy self-test passed")
