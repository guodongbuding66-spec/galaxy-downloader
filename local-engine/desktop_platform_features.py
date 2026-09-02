from __future__ import annotations

from desktop_clipboard import install_desktop_clipboard_monitor, run_desktop_clipboard_monitor_self_test
from desktop_tray import (
    install_desktop_tray,
    run_desktop_tray_self_test,
    verify_windows_tray_dependencies,
)


def install_desktop_platform_features(engine_module):
    """Install opt-in/platform integrations after the core download workbench.

    Keeping these integrations behind one boundary prevents the main downloader
    and Job policies from accumulating Windows/Linux/macOS-specific behavior.
    Global hotkeys and other desktop providers can join this layer later.
    """
    install_desktop_clipboard_monitor(engine_module)
    install_desktop_tray(engine_module)
    engine_module._galaxy_desktop_platform_features_installed = True
    return engine_module.EngineWindow


def run_desktop_platform_features_self_test() -> None:
    run_desktop_clipboard_monitor_self_test()
    run_desktop_tray_self_test()
