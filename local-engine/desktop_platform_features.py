from __future__ import annotations

from desktop_clipboard import install_desktop_clipboard_monitor, run_desktop_clipboard_monitor_self_test
from desktop_hotkey import (
    install_desktop_global_hotkey,
    run_desktop_global_hotkey_self_test,
    verify_windows_hotkey_api,
)
from desktop_library import install_desktop_library, run_desktop_library_self_test
from desktop_tray import (
    install_desktop_tray,
    run_desktop_tray_self_test,
    verify_windows_tray_dependencies,
)
from media_library import install_media_library, run_media_library_self_test


def install_desktop_platform_features(engine_module):
    """Install desktop integrations after the core download workbench.

    OS-specific providers remain behind this boundary so Job/download code never
    depends directly on Win32/macOS/Linux APIs. The media library is also wired
    here because this bootstrap runs only after history and the desktop hook
    registry are ready; the library core itself remains platform-neutral.
    """
    install_desktop_clipboard_monitor(engine_module)
    install_desktop_tray(engine_module)
    install_desktop_global_hotkey(engine_module)

    window_cls = engine_module.EngineWindow
    if hasattr(window_cls, "_run_job") and callable(getattr(engine_module, "default_download_dir", None)):
        install_media_library(engine_module)
        install_desktop_library(engine_module)

    engine_module._galaxy_desktop_platform_features_installed = True
    return window_cls


def run_desktop_platform_features_self_test() -> None:
    run_desktop_clipboard_monitor_self_test()
    run_desktop_tray_self_test()
    run_desktop_global_hotkey_self_test()
    run_media_library_self_test()
    run_desktop_library_self_test()
    assert verify_windows_tray_dependencies() is True
    assert verify_windows_hotkey_api() is True
