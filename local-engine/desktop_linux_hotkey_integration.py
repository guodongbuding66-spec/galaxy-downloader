from __future__ import annotations

import sys
from typing import Any

from desktop_hooks import register_after_build_ui_hook, registered_after_build_ui_hooks
from desktop_hotkey_preferences import load_linux_hotkey_preferences
from desktop_linux_hotkey import (
    LinuxPortalGlobalHotkeyProvider,
    linux_portal_dependencies_available,
    run_linux_portal_hotkey_self_test,
)

_SKIP_START_FLAGS = {"--self-test", "--ui-smoke-test", "--version"}


def linux_portal_hotkey_should_start(*, platform: str | None = None, argv: tuple[str, ...] | None = None) -> bool:
    value = str(platform or sys.platform).lower()
    if not value.startswith("linux"):
        return False
    args = tuple(sys.argv[1:] if argv is None else argv)
    if any(flag in args for flag in _SKIP_START_FLAGS):
        return False
    return "--no-hotkey" not in args


def _schedule_workbench(window) -> None:
    def show() -> None:
        try:
            window.deiconify()
            window.lift()
            window.focus_force()
        except Exception:
            return
        entry = getattr(window, "_quick_url_entry", None)
        if entry is not None:
            try:
                entry.focus_set()
                entry.icursor("end")
            except Exception:
                return

    try:
        window.after(0, show)
    except Exception:
        # Tk may already be tearing down while a portal activation is in flight.
        return


def _install_linux_provider(window, engine_module) -> None:
    if not str(sys.platform).lower().startswith("linux"):
        return

    previous = getattr(window, "_galaxy_hotkey_provider", None)
    if previous is not None:
        try:
            previous.stop()
        except Exception:
            # The base Linux provider is normally null; provider replacement must
            # still proceed if a third-party teardown hook raises unexpectedly.
            pass

    shortcut = str(load_linux_hotkey_preferences(engine_module).get("shortcut") or "")
    provider = LinuxPortalGlobalHotkeyProvider(
        window,
        shortcut,
        on_activate=lambda: _schedule_workbench(window),
    )
    window._galaxy_hotkey_provider = provider
    if shortcut and linux_portal_hotkey_should_start():
        provider.start()

    def on_destroy(event) -> None:
        if getattr(event, "widget", None) is window:
            provider.stop()

    try:
        window.bind("<Destroy>", on_destroy, add="+")
    except Exception:
        # Some architecture fixtures expose bridge_status without a Tk bind API.
        pass


def install_linux_portal_hotkey(engine_module):
    """Overlay the Linux portal provider after the base Windows/macOS hook.

    The preference layer remains the source of the requested shortcut. This
    layer owns runtime availability/active state and therefore overrides the
    generic bridge fields only when a Linux portal provider is attached.
    """
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_linux_portal_hotkey_installed", False):
        return window_cls

    def install_provider(window) -> None:
        _install_linux_provider(window, engine_module)

    register_after_build_ui_hook(
        window_cls,
        "desktop-linux-portal-hotkey",
        install_provider,
        order=58,
    )

    original_bridge_status = window_cls.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        if not str(sys.platform).lower().startswith("linux"):
            return payload
        provider = getattr(window, "_galaxy_hotkey_provider", None)
        if not isinstance(provider, LinuxPortalGlobalHotkeyProvider):
            return payload
        state = provider.state
        payload["globalHotkeyAvailable"] = bool(state.available)
        payload["globalHotkeyActive"] = bool(state.active)
        payload["globalHotkey"] = str(state.shortcut or "")
        if state.error:
            payload["globalHotkeyError"] = str(state.error)
        else:
            payload.pop("globalHotkeyError", None)
        return payload

    window_cls.bridge_status = bridge_status
    window_cls._galaxy_linux_portal_hotkey_installed = True
    engine_module._galaxy_linux_portal_hotkey_installed = True
    return window_cls


def run_linux_portal_hotkey_integration_self_test() -> None:
    run_linux_portal_hotkey_self_test()
    assert linux_portal_hotkey_should_start(platform="linux", argv=()) is True
    assert linux_portal_hotkey_should_start(platform="linux", argv=("--no-hotkey",)) is False
    assert linux_portal_hotkey_should_start(platform="linux", argv=("--self-test",)) is False
    assert linux_portal_hotkey_should_start(platform="darwin", argv=()) is False

    class Window:
        @staticmethod
        def bridge_status(_window=None):
            return {}

    class Engine:
        EngineWindow = Window

    install_linux_portal_hotkey(Engine)
    assert "desktop-linux-portal-hotkey" in registered_after_build_ui_hooks(Window)
    assert Window._galaxy_linux_portal_hotkey_installed is True

    # The dependency is required only on Linux by requirements.txt. Do not fail
    # Windows/macOS source self-tests just because their environment skips it.
    if sys.platform.startswith("linux"):
        assert linux_portal_dependencies_available() is True
