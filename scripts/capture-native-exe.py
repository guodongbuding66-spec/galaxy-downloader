"""Capture the client area of the final, visible Windows executable."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import ImageGrab


def main(exe: Path, out: Path) -> None:
    user = ctypes.windll.user32
    user.SetProcessDPIAware()
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = (callback, wintypes.LPARAM)
    user.IsWindowVisible.argtypes = (wintypes.HWND,)
    user.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    user.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT)
    user.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    def windows():
        found = []

        @callback
        def collect(handle, _arg):
            title = ctypes.create_unicode_buffer(256)
            if user.IsWindowVisible(handle) and user.GetWindowTextW(handle, title, len(title)):
                if title.value == "Galaxy · 媒体下载工作台":
                    found.append(handle)
            return True

        user.EnumWindows(collect, 0)
        return found

    existing = set(windows())
    process = subprocess.Popen([str(exe.resolve())])
    handle = None
    try:
        end = time.monotonic() + 30
        while time.monotonic() < end:
            handle = next((item for item in windows() if item not in existing), None)
            if handle:
                break
            if process.poll() is not None:
                raise RuntimeError(f"Executable exited before displaying its window: {process.returncode}")
            time.sleep(0.15)
        if not handle:
            raise RuntimeError("Packaged native window was not visible")
        width = min(1280, user.GetSystemMetrics(0) - 20)
        height = min(800, user.GetSystemMetrics(1) - 52)
        if not user.SetWindowPos(handle, wintypes.HWND(-1), 4, 4, width, height, 0x40):
            raise ctypes.WinError()
        time.sleep(0.65)
        client, origin = wintypes.RECT(), wintypes.POINT()
        if not user.GetClientRect(handle, ctypes.byref(client)) or not user.ClientToScreen(handle, ctypes.byref(origin)):
            raise ctypes.WinError()
        width, height = client.right, client.bottom
        assert width >= 900 and height >= 600
        screenshot = ImageGrab.grab((origin.x, origin.y, origin.x + width, origin.y + height), all_screens=True).convert("RGB")
        # The expected large near-black client surface rejects a blank frame or unrelated overlay.
        colors = screenshot.resize((100, 70)).getdata()
        assert sum(max(pixel) < 60 for pixel in colors) > 4200, "Captured client was not the dark workspace"
        out.mkdir(exist_ok=True, parents=True)
        screenshot.save(out / "native-exe.png")
        (out / "native-exe-runtime.json").write_text(json.dumps({
            "capturedPackagedExe": True, "width": width, "height": height, "mock": False,
        }, indent=2), encoding="utf-8")
    finally:
        if handle:
            user.PostMessageW(handle, 0x0010, 0, 0)  # WM_CLOSE
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=8)
            process.wait(timeout=8)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
