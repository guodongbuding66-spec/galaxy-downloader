from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from types import SimpleNamespace
from urllib.parse import urlparse

from desktop_hooks import register_after_build_ui_hook, registered_after_build_ui_hooks

PROTOCOL_SCHEME = "galaxy-downloader"
GURL_EVENT_CLASS = int.from_bytes(b"GURL", "big")
GURL_EVENT_ID = int.from_bytes(b"GURL", "big")
DIRECT_OBJECT_KEYWORD = int.from_bytes(b"----", "big")
_SKIP_START_FLAGS = {"--self-test", "--ui-smoke-test", "--version"}
_HANDLER_CLASS = None


def protocol_platform_supported(platform: str | None = None) -> bool:
    """Return whether this module owns a tested runtime URL-event backend."""
    return str(platform or sys.platform).lower() == "darwin"


def protocol_should_start(*, platform: str | None = None, argv: tuple[str, ...] | None = None) -> bool:
    args = tuple(sys.argv[1:] if argv is None else argv)
    if any(flag in args for flag in _SKIP_START_FLAGS):
        return False
    return protocol_platform_supported(platform)


def _show_workbench(window) -> None:
    try:
        window.deiconify()
        window.lift()
        window.focus_force()
    except Exception:
        return


def _schedule_workbench(window) -> bool:
    try:
        window.after(0, lambda: _show_workbench(window))
        return True
    except Exception:
        return False


def _macos_handler_class():
    global _HANDLER_CLASS
    if _HANDLER_CLASS is not None:
        return _HANDLER_CLASS

    from Cocoa import NSObject

    class GalaxyURLAppleEventHandler(NSObject):
        __slots__ = ("_galaxy_provider",)

        def handleEvent_withReplyEvent_(self, event, _reply_event):
            provider = getattr(self, "_galaxy_provider", None)
            if provider is not None:
                provider.handle_apple_event(event)

    _HANDLER_CLASS = GalaxyURLAppleEventHandler
    return _HANDLER_CLASS


@dataclass
class ProtocolState:
    available: bool
    active: bool = False
    last_action: str = ""
    error: str = ""


class MacOSURLProtocolProvider:
    """Receive LaunchServices GURL Apple Events inside an already-running Tk app."""

    def __init__(self, window, engine_module) -> None:
        self.window = window
        self.engine_module = engine_module
        self.state = ProtocolState(available=True)
        self._manager = None
        self._handler = None
        self._stop_lock = threading.Lock()

    def start(self) -> bool:
        if self.state.active:
            return True
        if threading.current_thread() is not threading.main_thread():
            self.state.error = "macOS protocol handler must be registered on the main thread"
            return False
        try:
            from Cocoa import NSAppleEventManager

            manager = NSAppleEventManager.sharedAppleEventManager()
            if manager is None:
                raise RuntimeError("NSAppleEventManager is unavailable")
            handler_cls = _macos_handler_class()
            handler = handler_cls.alloc().init()
            if handler is None:
                raise RuntimeError("macOS URL event handler could not be created")
            handler._galaxy_provider = self
            self._manager = manager
            self._handler = handler
            manager.setEventHandler_andSelector_forEventClass_andEventID_(
                handler,
                "handleEvent:withReplyEvent:",
                GURL_EVENT_CLASS,
                GURL_EVENT_ID,
            )
            self.state.active = True
            self.state.error = ""
            return True
        except Exception as exc:  # noqa: BLE001
            self.state.error = str(exc)[:240]
            self.stop()
            return False

    def handle_apple_event(self, event) -> None:
        try:
            descriptor = event.descriptorForKeyword_(DIRECT_OBJECT_KEYWORD)
            raw = "" if descriptor is None else str(descriptor.stringValue() or "").strip()
            self.dispatch_url(raw)
        except Exception as exc:  # noqa: BLE001
            self.state.error = str(exc)[:240]

    def dispatch_url(self, raw: str) -> bool:
        value = str(raw or "").strip()
        if not value:
            self.state.error = "Empty Galaxy protocol URL"
            return False
        try:
            parsed = urlparse(value)
        except Exception as exc:  # noqa: BLE001
            self.state.error = f"Invalid Galaxy protocol URL: {exc}"[:240]
            return False

        expected_scheme = str(getattr(self.engine_module, "PROTOCOL", PROTOCOL_SCHEME) or PROTOCOL_SCHEME).lower()
        if parsed.scheme.lower() != expected_scheme:
            self.state.error = "Unsupported protocol scheme"
            return False
        action = (parsed.netloc or parsed.path.lstrip("/")).strip().lower()
        if action == "open":
            self.state.last_action = "open"
            self.state.error = ""
            scheduled = _schedule_workbench(self.window)
            if not scheduled:
                self.state.error = "Tk workbench is unavailable"
            return scheduled
        if action != "download":
            self.state.error = f"Unsupported Galaxy protocol action: {action or 'missing'}"[:240]
            return False

        try:
            job = self.engine_module.parse_job(value)
            payload = self.engine_module.job_to_payload(job)
        except Exception as exc:  # noqa: BLE001
            self.state.error = f"Invalid Galaxy download request: {exc}"[:240]
            return False

        submit = getattr(self.window, "submit_bridge_job", None)
        if not callable(submit):
            self.state.error = "Desktop download submission is unavailable"
            return False

        self.state.last_action = "download"
        self.state.error = ""

        def worker() -> None:
            try:
                accepted = bool(submit(payload))
                if not accepted:
                    self.state.error = "Galaxy protocol download was not accepted"
            except Exception as exc:  # noqa: BLE001
                self.state.error = f"Galaxy protocol download failed: {exc}"[:240]

        threading.Thread(target=worker, name="GalaxyProtocolSubmit", daemon=True).start()
        return True

    def stop(self) -> None:
        with self._stop_lock:
            manager = self._manager
            self._manager = None
            self._handler = None
            self.state.active = False
        if manager is None:
            return
        try:
            manager.removeEventHandlerForEventClass_andEventID_(GURL_EVENT_CLASS, GURL_EVENT_ID)
        except Exception:
            # Cocoa can already be dismantling when Tk emits its final Destroy;
            # a teardown-only native error must not leave local state marked active.
            pass


class NullURLProtocolProvider:
    def __init__(self, error: str = "") -> None:
        self.state = ProtocolState(available=False, active=False, error=error)

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        self.state.active = False


def create_protocol_provider(window, engine_module):
    if not protocol_platform_supported():
        return NullURLProtocolProvider("Runtime URL-event backend is not enabled for this platform")
    return MacOSURLProtocolProvider(window, engine_module)


def _install_protocol_for_window(window, engine_module) -> None:
    provider = create_protocol_provider(window, engine_module)
    window._galaxy_protocol_provider = provider
    if protocol_should_start():
        provider.start()

    def on_destroy(event) -> None:
        if getattr(event, "widget", None) is not window:
            return
        provider.stop()

    try:
        window.bind("<Destroy>", on_destroy, add="+")
    except Exception:
        return


def install_desktop_protocol(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_protocol_installed", False):
        return window_cls

    register_after_build_ui_hook(
        window_cls,
        "desktop-macos-protocol",
        lambda window: _install_protocol_for_window(window, engine_module),
        order=58,
    )
    window_cls._galaxy_desktop_protocol_installed = True
    engine_module._galaxy_desktop_protocol_installed = True
    return window_cls


def verify_macos_protocol_runtime() -> bool:
    if sys.platform != "darwin":
        return True
    try:
        from Cocoa import NSAppleEventDescriptor, NSAppleEventManager, NSObject  # noqa: F401

        manager = NSAppleEventManager.sharedAppleEventManager()
        return manager is not None and all(
            hasattr(manager, name)
            for name in (
                "setEventHandler_andSelector_forEventClass_andEventID_",
                "removeEventHandlerForEventClass_andEventID_",
            )
        )
    except Exception:
        return False


def run_desktop_protocol_self_test() -> None:
    assert protocol_platform_supported("darwin") is True
    assert protocol_platform_supported("win32") is False
    assert protocol_platform_supported("linux") is False
    assert protocol_should_start(platform="darwin", argv=("--self-test",)) is False
    assert protocol_should_start(platform="darwin", argv=("--ui-smoke-test",)) is False
    assert protocol_should_start(platform="darwin", argv=()) is True
    assert protocol_should_start(platform="linux", argv=()) is False
    assert GURL_EVENT_CLASS == 0x4755524C
    assert GURL_EVENT_ID == 0x4755524C
    assert DIRECT_OBJECT_KEYWORD == 0x2D2D2D2D

    class Window:
        pass

    engine = SimpleNamespace(EngineWindow=Window)
    install_desktop_protocol(engine)
    assert "desktop-macos-protocol" in registered_after_build_ui_hooks(Window)
    assert Window._galaxy_desktop_protocol_installed is True
