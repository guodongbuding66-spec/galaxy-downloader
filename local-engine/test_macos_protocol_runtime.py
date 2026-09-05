from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from urllib.parse import urlencode

import engine
from desktop_protocol import (
    DIRECT_OBJECT_KEYWORD,
    MacOSURLProtocolProvider,
    protocol_platform_supported,
)


class AppleEventProbe:
    def __init__(self, raw_url: str) -> None:
        from Cocoa import NSAppleEventDescriptor

        self.descriptor = NSAppleEventDescriptor.descriptorWithString_(raw_url)

    def descriptorForKeyword_(self, keyword: int):
        if int(keyword) != DIRECT_OBJECT_KEYWORD:
            raise RuntimeError(f"unexpected Apple Event keyword: {keyword}")
        return self.descriptor


class TkWindowProbe:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.opened = False
        self.submitted_payload = None
        self.submit_thread = None
        self.submitted = threading.Event()

    def after(self, delay_ms: int, callback):
        return self.root.after(delay_ms, callback)

    def deiconify(self) -> None:
        self.opened = True

    def lift(self) -> None:
        return None

    def focus_force(self) -> None:
        return None

    def submit_bridge_job(self, payload) -> bool:
        self.submit_thread = threading.current_thread()
        completed = threading.Event()

        def accept() -> None:
            self.submitted_payload = dict(payload)
            self.submitted.set()
            completed.set()

        self.root.after(0, accept)
        return completed.wait(timeout=2.0)


def _pump(root: tk.Tk, predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _deliver(provider: MacOSURLProtocolProvider, raw_url: str) -> None:
    handler = provider._handler
    if handler is None:
        raise RuntimeError("macOS URL handler was not installed")
    handler.handleEvent_withReplyEvent_(AppleEventProbe(raw_url), None)


def main() -> int:
    if sys.platform != "darwin":
        raise RuntimeError("macOS protocol runtime smoke must run on Darwin")
    if not protocol_platform_supported():
        raise RuntimeError("macOS protocol backend is not enabled")

    watchdog = threading.Timer(15.0, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()

    root = tk.Tk()
    root.withdraw()
    window = TkWindowProbe(root)
    provider = MacOSURLProtocolProvider(window, engine)

    try:
        if not provider.start():
            raise RuntimeError(f"macOS protocol handler failed to start: {provider.state.error}")
        if not provider.state.active:
            raise RuntimeError("macOS protocol handler did not become active")

        _deliver(provider, "https://example.com/not-galaxy")
        root.update()
        if window.opened or window.submitted.is_set():
            raise RuntimeError("non-Galaxy URL was accepted by the Apple Event handler")

        _deliver(provider, "galaxy-downloader://open")
        if not _pump(root, lambda: window.opened):
            raise RuntimeError("galaxy-downloader://open did not surface the Tk workbench")
        if provider.state.last_action != "open":
            raise RuntimeError("open protocol action was not recorded")

        query = urlencode({"url": "https://example.com/video.mp4", "format": "best"})
        _deliver(provider, f"galaxy-downloader://download?{query}")
        if not _pump(root, window.submitted.is_set):
            raise RuntimeError("download protocol event was not submitted")
        if window.submit_thread is threading.main_thread():
            raise RuntimeError("download submission blocked the Tk/Cocoa main thread")
        if not isinstance(window.submitted_payload, dict):
            raise RuntimeError("download protocol payload was not produced")
        if window.submitted_payload.get("url") != "https://example.com/video.mp4":
            raise RuntimeError(f"unexpected protocol payload: {window.submitted_payload}")
        if provider.state.last_action != "download":
            raise RuntimeError("download protocol action was not recorded")

        provider.stop()
        if provider.state.active:
            raise RuntimeError("macOS protocol handler remained active after stop")
        return 0
    finally:
        provider.stop()
        try:
            root.destroy()
        except Exception:
            # Cocoa may already have started tearing down Tk by interpreter exit;
            # a final-window cleanup error must not mask the protocol result.
            pass
        watchdog.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
