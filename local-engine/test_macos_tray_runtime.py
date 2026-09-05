from __future__ import annotations

import os
import sys
import threading
import tkinter as tk

from desktop_tray import WindowsPystrayProvider, tray_platform_supported


def main() -> int:
    if sys.platform != "darwin":
        raise RuntimeError("macOS tray runtime smoke must run on Darwin")
    if not tray_platform_supported():
        raise RuntimeError("macOS tray backend is not enabled")

    # Fail closed instead of allowing a GUI integration regression to consume the
    # full Actions job timeout if run_detached() or Tk's event loop stops making
    # progress.
    watchdog = threading.Timer(12.0, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()

    root = tk.Tk()
    root.withdraw()
    provider = WindowsPystrayProvider(root, "Galaxy Local Engine", platform="darwin")

    try:
        if not provider.start():
            raise RuntimeError(f"macOS tray failed to start: {provider.state.error}")
        if not provider.state.active or provider.icon is None:
            raise RuntimeError("macOS tray did not become active")

        module_name = provider.icon.__class__.__module__
        if "darwin" not in module_name.lower():
            raise RuntimeError(f"unexpected pystray backend: {module_name}")

        completed = {"value": False}

        def finish() -> None:
            provider.stop()
            completed["value"] = True
            root.quit()

        root.after(900, finish)
        root.mainloop()

        if not completed["value"]:
            raise RuntimeError("Tk main loop exited before tray lifecycle completed")
        if provider.state.active:
            raise RuntimeError("macOS tray remained active after stop")
        return 0
    finally:
        provider.stop()
        try:
            root.destroy()
        except Exception:
            pass
        watchdog.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
