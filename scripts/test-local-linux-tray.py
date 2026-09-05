#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

# Force the contract under test before desktop_tray imports pystray lazily.
os.environ["PYSTRAY_BACKEND"] = "appindicator"

from desktop_tray import (  # noqa: E402
    LINUX_TRAY_BACKEND,
    LinuxAppIndicatorProvider,
    TRAY_ACTIONS,
    tray_dependency_available,
    tray_platform_supported,
    verify_linux_tray_dependencies,
)


class FakeWindow:
    def __init__(self) -> None:
        self.scheduled = 0

    def after(self, _delay: int, callback) -> None:
        self.scheduled += 1
        callback()

    def deiconify(self) -> None:
        pass

    def lift(self) -> None:
        pass

    def focus_force(self) -> None:
        pass

    def withdraw(self) -> None:
        pass

    def open_folder(self) -> None:
        pass

    def close_app(self) -> None:
        pass

    def set_queue_paused(self, _paused: bool) -> bool:
        return True

    def pause_active_job(self) -> bool:
        return True


def main() -> int:
    assert sys.platform.startswith("linux"), sys.platform
    assert LINUX_TRAY_BACKEND == "appindicator"
    assert os.environ.get("PYSTRAY_BACKEND") == "appindicator"
    assert tray_platform_supported("linux") is True
    assert tray_dependency_available("linux") is True
    assert verify_linux_tray_dependencies() is True
    assert TRAY_ACTIONS == (
        "show",
        "hide",
        "downloads",
        "open-downloads",
        "pause-all",
        "exit",
    )

    window = FakeWindow()
    provider = LinuxAppIndicatorProvider(window, "Galaxy Local Engine")
    assert provider.start() is True, provider.state.error
    assert provider.state.available is True
    assert provider.state.active is True
    assert provider.icon is not None
    assert "appindicator" in provider.icon.__class__.__module__.lower()
    assert provider._loop_thread is not None
    assert provider._loop_thread.is_alive() is True

    # Leave the GObject loop alive briefly so an immediate asynchronous backend
    # failure cannot masquerade as a successful start handshake.
    time.sleep(0.25)
    assert provider._loop_thread is not None and provider._loop_thread.is_alive()

    provider.stop()
    assert provider.state.active is False
    assert provider.icon is None
    assert provider._loop_thread is None
    assert provider.start() is True, provider.state.error
    provider.stop()
    assert provider.state.active is False

    print("Linux AppIndicator tray lifecycle OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
