from __future__ import annotations

import ctypes
import os
import sys
import threading
import tkinter as tk

from desktop_hotkey import (
    EventHotKeyID,
    K_EVENT_CLASS_KEYBOARD,
    K_EVENT_HOTKEY_PRESSED,
    K_EVENT_PARAM_DIRECT_OBJECT,
    MAC_HOTKEY_ID,
    MAC_HOTKEY_SIGNATURE,
    MacOSCarbonGlobalHotkeyProvider,
    TYPE_EVENT_HOTKEY_ID,
    hotkey_platform_supported,
)


class TkWindowProbe:
    """Small Tk-thread probe used by the native Carbon lifecycle smoke."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.triggered = False

    def after(self, delay_ms: int, callback):
        return self.root.after(delay_ms, callback)

    def deiconify(self) -> None:
        self.triggered = True

    def lift(self) -> None:
        return None

    def focus_force(self) -> None:
        return None


def _configure_event_dispatch(carbon) -> None:
    carbon.CreateEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_double,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    carbon.CreateEvent.restype = ctypes.c_int32
    carbon.SetEventParameter.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    carbon.SetEventParameter.restype = ctypes.c_int32
    carbon.SendEventToEventTarget.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    carbon.SendEventToEventTarget.restype = ctypes.c_int32
    carbon.ReleaseEvent.argtypes = [ctypes.c_void_p]
    carbon.ReleaseEvent.restype = None


def _send_hotkey_event(provider: MacOSCarbonGlobalHotkeyProvider, *, signature: int, hotkey_id: int) -> int:
    carbon = provider._carbon
    if carbon is None:
        raise RuntimeError("Carbon backend was released before event dispatch")
    _configure_event_dispatch(carbon)

    event_ref = ctypes.c_void_p()
    status = int(
        carbon.CreateEvent(
            None,
            K_EVENT_CLASS_KEYBOARD,
            K_EVENT_HOTKEY_PRESSED,
            0.0,
            0,
            ctypes.byref(event_ref),
        )
    )
    if status != 0 or not event_ref:
        raise RuntimeError(f"CreateEvent failed ({status})")

    try:
        event_hotkey_id = EventHotKeyID(signature, hotkey_id)
        status = int(
            carbon.SetEventParameter(
                event_ref,
                K_EVENT_PARAM_DIRECT_OBJECT,
                TYPE_EVENT_HOTKEY_ID,
                ctypes.sizeof(event_hotkey_id),
                ctypes.byref(event_hotkey_id),
            )
        )
        if status != 0:
            raise RuntimeError(f"SetEventParameter failed ({status})")
        return int(carbon.SendEventToEventTarget(event_ref, provider._event_target))
    finally:
        carbon.ReleaseEvent(event_ref)


def main() -> int:
    if sys.platform != "darwin":
        raise RuntimeError("macOS global hotkey runtime smoke must run on Darwin")
    if not hotkey_platform_supported():
        raise RuntimeError("macOS global hotkey backend is not enabled")

    # Fail closed instead of allowing a native event-loop regression to consume
    # the full Actions timeout.
    watchdog = threading.Timer(12.0, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()

    root = tk.Tk()
    root.withdraw()
    window = TkWindowProbe(root)
    provider = MacOSCarbonGlobalHotkeyProvider(window)

    try:
        if not provider.start():
            raise RuntimeError(f"macOS hotkey failed to register: {provider.state.error}")
        if not provider.state.active:
            raise RuntimeError("macOS hotkey did not become active")

        # First prove the handler filters unrelated Carbon hot-key IDs.
        _send_hotkey_event(
            provider,
            signature=MAC_HOTKEY_SIGNATURE,
            hotkey_id=MAC_HOTKEY_ID + 1,
        )
        root.update()
        if window.triggered:
            raise RuntimeError("unrelated Carbon hotkey incorrectly triggered the workbench")

        status = _send_hotkey_event(
            provider,
            signature=MAC_HOTKEY_SIGNATURE,
            hotkey_id=MAC_HOTKEY_ID,
        )
        if status != 0:
            raise RuntimeError(f"SendEventToEventTarget failed ({status})")

        root.update()
        if not window.triggered:
            raise RuntimeError("registered Carbon hotkey did not schedule the Tk workbench")

        provider.stop()
        if provider.state.active:
            raise RuntimeError("macOS hotkey remained active after stop")
        return 0
    finally:
        provider.stop()
        try:
            root.destroy()
        except Exception:
            # Tk can already be torn down by Cocoa during final interpreter cleanup;
            # that teardown-only condition must not mask the Carbon lifecycle result.
            pass
        watchdog.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
