from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from desktop_hooks import register_after_build_ui_hook, registered_after_build_ui_hooks

HOTKEY_LABEL = "Ctrl+Shift+G"
HOTKEY_ID = 0x474C  # "GL"
MOD_SHIFT = 0x0004
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
VK_G = 0x47
_SKIP_START_FLAGS = {"--self-test", "--ui-smoke-test", "--version"}


def hotkey_platform_supported(platform: str | None = None) -> bool:
    return str(platform or sys.platform).lower().startswith("win")


def hotkey_should_start(*, platform: str | None = None, argv: tuple[str, ...] | None = None) -> bool:
    args = tuple(sys.argv[1:] if argv is None else argv)
    if any(flag in args for flag in _SKIP_START_FLAGS):
        return False
    if "--no-hotkey" in args:
        return False
    return hotkey_platform_supported(platform)


def _show_workbench(window) -> None:
    try:
        window.deiconify()
        window.lift()
        window.focus_force()
    except Exception:
        pass
    entry = getattr(window, "_quick_url_entry", None)
    if entry is not None:
        try:
            entry.focus_set()
            entry.icursor("end")
        except Exception:
            pass


def _schedule_workbench(window) -> None:
    try:
        window.after(0, lambda: _show_workbench(window))
    except Exception:
        pass


@dataclass
class HotkeyState:
    available: bool
    active: bool = False
    shortcut: str = HOTKEY_LABEL
    error: str = ""


class WindowsGlobalHotkeyProvider:
    """Register a process-global hotkey on a dedicated Win32 message thread."""

    def __init__(self, window) -> None:
        self.window = window
        self.state = HotkeyState(available=True)
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._stop_lock = threading.Lock()

    @staticmethod
    def _user32():
        return ctypes.WinDLL("user32", use_last_error=True)

    @staticmethod
    def _kernel32():
        return ctypes.WinDLL("kernel32", use_last_error=True)

    def start(self, timeout: float = 2.0) -> bool:
        if self.state.active:
            return True
        if self._thread is not None and self._thread.is_alive():
            return False
        self._ready.clear()
        self.state.error = ""
        self._thread = threading.Thread(
            target=self._message_loop,
            name="GalaxyGlobalHotkey",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=max(0.1, timeout)):
            self.state.error = "Timed out while registering global hotkey"
            self.stop()
            return False
        return bool(self.state.active)

    def _message_loop(self) -> None:
        user32 = self._user32()
        kernel32 = self._kernel32()
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self._thread_id = int(kernel32.GetCurrentThreadId())

        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL

        modifiers = MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT
        registered = bool(user32.RegisterHotKey(None, HOTKEY_ID, modifiers, VK_G))
        if not registered:
            error_code = ctypes.get_last_error()
            self.state.active = False
            self.state.error = f"RegisterHotKey failed ({error_code})"
            self._ready.set()
            self._thread_id = 0
            return

        self.state.active = True
        self.state.error = ""
        self._ready.set()
        message = wintypes.MSG()
        try:
            while True:
                result = int(user32.GetMessageW(ctypes.byref(message), None, 0, 0))
                if result == 0:  # WM_QUIT
                    break
                if result < 0:
                    self.state.error = f"GetMessageW failed ({ctypes.get_last_error()})"
                    break
                if int(message.message) == WM_HOTKEY and int(message.wParam) == HOTKEY_ID:
                    _schedule_workbench(self.window)
        finally:
            try:
                user32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception:
                pass
            self.state.active = False
            self._thread_id = 0

    def stop(self) -> None:
        with self._stop_lock:
            thread = self._thread
            thread_id = int(self._thread_id or 0)
            self._thread = None
        if thread is None:
            self.state.active = False
            return
        if thread_id:
            try:
                user32 = self._user32()
                user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                user32.PostThreadMessageW.restype = wintypes.BOOL
                user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        if thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=1.0)
        self.state.active = False


class NullGlobalHotkeyProvider:
    def __init__(self, error: str = "") -> None:
        self.state = HotkeyState(available=False, active=False, error=error)

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        self.state.active = False


def create_hotkey_provider(window):
    if not hotkey_platform_supported():
        return NullGlobalHotkeyProvider("Global hotkey backend is not enabled for this platform")
    return WindowsGlobalHotkeyProvider(window)


def _install_hotkey_for_window(window) -> None:
    provider = create_hotkey_provider(window)
    window._galaxy_hotkey_provider = provider
    if hotkey_should_start():
        provider.start()

    def on_destroy(event) -> None:
        if getattr(event, "widget", None) is not window:
            return
        provider.stop()

    try:
        window.bind("<Destroy>", on_destroy, add="+")
    except Exception:
        pass


def install_desktop_global_hotkey(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_global_hotkey_installed", False):
        return window_cls

    register_after_build_ui_hook(
        window_cls,
        "desktop-global-hotkey",
        _install_hotkey_for_window,
        order=57,
    )

    original_bridge_status = window_cls.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        provider = getattr(window, "_galaxy_hotkey_provider", None)
        state = getattr(provider, "state", None)
        payload["globalHotkeyAvailable"] = bool(getattr(state, "available", False))
        payload["globalHotkeyActive"] = bool(getattr(state, "active", False))
        payload["globalHotkey"] = HOTKEY_LABEL
        return payload

    window_cls.bridge_status = bridge_status
    window_cls._galaxy_desktop_global_hotkey_installed = True
    engine_module._galaxy_desktop_global_hotkey_installed = True
    return window_cls


def verify_windows_hotkey_api() -> bool:
    if not hotkey_platform_supported():
        return True
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        return all(hasattr(user32, name) for name in ("RegisterHotKey", "UnregisterHotKey", "GetMessageW", "PostThreadMessageW"))
    except Exception:
        return False


def run_desktop_global_hotkey_self_test() -> None:
    assert hotkey_platform_supported("win32") is True
    assert hotkey_platform_supported("linux") is False
    assert hotkey_should_start(platform="win32", argv=("--self-test",)) is False
    assert hotkey_should_start(platform="win32", argv=("--no-hotkey",)) is False
    assert hotkey_should_start(platform="linux", argv=()) is False
    assert HOTKEY_LABEL == "Ctrl+Shift+G"
    assert MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT == 0x4006

    class Window:
        @staticmethod
        def bridge_status(_window=None):
            return {}

    engine = SimpleNamespace(EngineWindow=Window)
    install_desktop_global_hotkey(engine)
    assert "desktop-global-hotkey" in registered_after_build_ui_hooks(Window)
    assert Window._galaxy_desktop_global_hotkey_installed is True
