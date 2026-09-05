from __future__ import annotations

from bandwidth_policy import install_bandwidth_policy, run_bandwidth_policy_self_test
from desktop_bandwidth import install_desktop_bandwidth, run_desktop_bandwidth_self_test
from desktop_clipboard import install_desktop_clipboard_monitor, run_desktop_clipboard_monitor_self_test
from desktop_hotkey import (
    install_desktop_global_hotkey,
    run_desktop_global_hotkey_self_test,
    verify_windows_hotkey_api,
)
from desktop_hotkey_preferences import (
    install_linux_hotkey_preferences,
    run_linux_hotkey_preferences_self_test,
)
from desktop_library import install_desktop_library, run_desktop_library_self_test
from desktop_subscriptions import install_desktop_subscriptions, run_desktop_subscriptions_self_test
from desktop_tray import (
    install_desktop_tray,
    run_desktop_tray_self_test,
    verify_windows_tray_dependencies,
)
from media_library import install_media_library, run_media_library_self_test
from subscription_scheduler import run_subscription_scheduler_self_test
from subscriptions import run_subscriptions_self_test


def _has_job_policy_contract(engine_module) -> bool:
    """Return whether the engine exposes the full mutable Job policy surface.

    Runtime Local Engine modules always provide this contract. A few architecture
    self-tests intentionally use a lightweight EngineWindow-only namespace to
    validate desktop hook composition; those fixtures must not be forced to fake
    the complete download engine just because a platform UI hook is installed.
    """
    window_cls = getattr(engine_module, "EngineWindow", None)
    return bool(
        getattr(engine_module, "Job", None)
        and callable(getattr(engine_module, "parse_job", None))
        and callable(getattr(engine_module, "job_from_payload", None))
        and callable(getattr(engine_module, "job_to_payload", None))
        and window_cls is not None
        and callable(getattr(window_cls, "build_options", None))
        and callable(getattr(window_cls, "_run_external_job", None))
        and callable(getattr(window_cls, "bridge_status", None))
    )


def install_desktop_platform_features(engine_module):
    """Install desktop integrations after the core download workbench.

    OS-specific providers remain behind this boundary so Job/download code never
    depends directly on Win32/macOS/Linux APIs. Local library/subscription
    surfaces are wired here because this bootstrap runs only after history,
    queue submission and the desktop hook registry are ready.
    """
    if _has_job_policy_contract(engine_module):
        install_bandwidth_policy(engine_module)
    install_desktop_bandwidth(engine_module)
    install_desktop_clipboard_monitor(engine_module)
    install_desktop_tray(engine_module)
    install_desktop_global_hotkey(engine_module)
    install_linux_hotkey_preferences(engine_module)

    window_cls = engine_module.EngineWindow
    if hasattr(window_cls, "_run_job") and callable(getattr(engine_module, "default_download_dir", None)):
        install_media_library(engine_module)
        install_desktop_library(engine_module)
        install_desktop_subscriptions(engine_module)

    engine_module._galaxy_desktop_platform_features_installed = True
    return window_cls


def run_desktop_platform_features_self_test() -> None:
    run_bandwidth_policy_self_test()
    run_desktop_bandwidth_self_test()
    run_desktop_clipboard_monitor_self_test()
    run_desktop_tray_self_test()
    run_desktop_global_hotkey_self_test()
    run_linux_hotkey_preferences_self_test()
    run_media_library_self_test()
    run_desktop_library_self_test()
    run_subscriptions_self_test()
    run_subscription_scheduler_self_test()
    run_desktop_subscriptions_self_test()
    assert _has_job_policy_contract(object()) is False
    assert verify_windows_tray_dependencies() is True
    assert verify_windows_hotkey_api() is True
