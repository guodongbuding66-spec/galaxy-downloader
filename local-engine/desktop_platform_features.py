from __future__ import annotations

from desktop_clipboard import install_desktop_clipboard_monitor, run_desktop_clipboard_monitor_self_test
from desktop_hotkey import (
    install_desktop_global_hotkey,
    run_desktop_global_hotkey_self_test,
    verify_windows_hotkey_api,
)
from desktop_tray import (
    install_desktop_tray,
    run_desktop_tray_self_test,
    verify_windows_tray_dependencies,
)


def install_desktop_platform_features(engine_module):
    """Install desktop integrations after the core download workbench.

    Platform implementations stay behind this boundary so Job/download code
    never depends directly on Win32/macOS/Linux desktop APIs.
    """
    install_desktop_clipboard_monitor(engine_module)
    install_desktop_tray(engine_module)
    install_desktop_global_hotkey(engine_module)
    engine_module._galaxy_desktop_platform_features_installed = True
    return engine_module.EngineWindow


def run_desktop_platform_features_self_test() -> None:
    run_desktop_clipboard_monitor_self_test()
    run_desktop_tray_self_test()
    run_desktop_global_hotkey_self_test()
    assert verify_windows_tray_dependencies() is True
    assert verify_windows_hotkey_api() is True
