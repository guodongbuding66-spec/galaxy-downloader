"""Exercise and capture the real Windows Tk application in CI."""
from __future__ import annotations

import json
import sys
import time
import tkinter as tk
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-engine"))
import entrypoint  # noqa: F401, E402  # installs the actual desktop composition
import engine  # noqa: E402


def snapshot(widget):
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    return ImageGrab.grab(bbox=(x, y, x + widget.winfo_width(), y + widget.winfo_height()), all_screens=True)


def settle(app, seconds=0.12):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        app.update()
        time.sleep(0.012)


def visible_in(widget, bounds):
    x = widget.winfo_rootx() - bounds.winfo_rootx()
    y = widget.winfo_rooty() - bounds.winfo_rooty()
    return (widget.winfo_ismapped() and x >= 0 and y >= 0
            and x + widget.winfo_width() <= bounds.winfo_width()
            and y + widget.winfo_height() <= bounds.winfo_height())


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "qa")
    out.mkdir(parents=True, exist_ok=True)
    app = engine.EngineWindow(None)
    try:
        width = min(1280, app.winfo_screenwidth() - 22)
        height = min(800, app.winfo_screenheight() - 72)
        app.geometry(f"{width}x{height}+4+4")
        app.deiconify()
        app.lift()
        app.attributes("-topmost", True)
        settle(app, 0.45)
        assert app._orbit_shell
        assert visible_in(app._quick_parse_button, app._workbench_canvas), "parse action clipped"
        assert visible_in(app._quick_url_entry, app._workbench_canvas), "link input clipped"
        snapshot(app).save(out / "native-workbench.png")
        action_pixels = snapshot(app._quick_parse_button).convert("RGB").getdata()
        assert sum(pixel == (79, 125, 255) for pixel in action_pixels) > 300, "primary action not painted"
        rail_visible = bool(app._rail_canvas.winfo_ismapped())
        rail_width = app._rail_canvas.winfo_width()
        print(f"Window={app.winfo_width()}x{app.winfo_height()} rail={rail_width} mapped={rail_visible} main={app._workbench_canvas.winfo_width()}", flush=True)
        if app.winfo_width() >= 1120:
            assert rail_visible and rail_width <= 248, "wide queue must fit its allocated column"
        else:
            assert not rail_visible, "queue must collapse in a narrow window"
        assert not app._orbit_meter.winfo_ismapped(), "idle metrics add noise"
        assert app._orbit_advanced_button.winfo_ismapped(), "settings should be discoverable"
        assert app._quick_parse_button.winfo_height() >= 44, "primary hit area too small"
        tabs = app._orbit_tabs
        saved_reduced = app._orbit_reduce_motion.get()
        app._orbit_reduce_motion.set(False)
        app._quick_url_var.set("https://example.com/media")  # exercise retained input; never submit
        tabs.buttons[1].invoke()
        assert tabs.index == 1 and app._quick_url_var.get() == "https://example.com/media"
        assert tabs.tween.job is not None, "tab marker did not animate"
        tabs.buttons[0].invoke()
        assert tabs.index == 0 and app._quick_url_var.get() == "https://example.com/media"
        settle(app, 0.3)
        assert tabs.tween.current == 0 and tabs.tween.job is None, "rapid tab reversal did not settle"
        app._quick_url_var.set("")
        settle(app)
        frames = [snapshot(tabs)]
        tabs.buttons[1].invoke()
        while tabs.tween.job is not None:
            settle(app, 0.025)
            frames.append(snapshot(tabs))
        frames.append(snapshot(tabs))
        assert len(frames) >= 3 and tabs.tween.current == 1
        frames[0].save(out / "native-tab-motion.gif", save_all=True, append_images=frames[1:], duration=[450] + [42] * (len(frames) - 2) + [650], loop=0, disposal=2)
        assert visible_in(app._original_images_button, app), "original image action clipped"
        assert not app._quick_parse_button.winfo_ismapped(), "video action competes with original image mode"
        snapshot(app).save(out / "native-original-images.png")

        app._orbit_reduce_motion.set(True)
        tabs.buttons[0].invoke()
        assert tabs.tween.current == 0 and tabs.tween.job is None, "reduced motion did not snap"
        app._orbit_reduce_motion.set(saved_reduced)
        tabs.buttons[0].focus_force()
        settle(app)
        assert app.focus_get() is tabs.buttons[0], "tab did not receive keyboard focus"
        tabs.buttons[0].event_generate("<KeyPress-Right>", when="tail")
        settle(app)
        assert tabs.index == 1, "arrow key did not switch modes"
        tabs.buttons[1].event_generate("<Control-KeyPress-l>")
        settle(app)
        assert app.focus_get() is app._quick_url_entry, "Ctrl+L did not focus the link input"
        tabs.buttons[0].invoke()
        settle(app)
        assert app._orbit_tools_menu.index("end") >= 5, "secondary tools were lost"
        assert app._original_images_button.winfo_exists()
        assert app._queue_pause_button.winfo_exists()
        assert app._clipboard_preview_button.winfo_exists()
        app._orbit_advanced_button.invoke()
        settle(app)
        assert app._advanced_panel.winfo_ismapped()
        app._orbit_advanced_button.invoke()
        settle(app)
        assert not app._advanced_panel.winfo_ismapped()

        compact_width = min(960, width)
        compact_height = min(650, height)
        app.geometry(f"{compact_width}x{compact_height}+4+4")
        settle(app)
        assert visible_in(app._quick_parse_button, app._workbench_canvas), "compact parse action clipped"
        assert visible_in(app._quick_url_entry, app), "compact link input clipped"
        snapshot(app).save(out / "native-workbench-compact.png")
        existing = set(app.winfo_children())
        app._orbit_queue_nav.invoke()
        settle(app)
        queue_windows = [child for child in app.winfo_children() if child not in existing and isinstance(child, tk.Toplevel)]
        assert queue_windows, "queue is not reachable from compact navigation"
        for dialog in queue_windows:
            dialog.destroy()
        (out / "native-runtime.json").write_text(json.dumps({
            "nativeWindowCreated": True, "width": width, "height": height,
            "compactWidth": app.winfo_width(), "compactHeight": app.winfo_height(),
            "inputRetainedAcrossModes": True, "rapidReversalSettled": True,
            "reducedMotionSnap": True, "advancedDisclosure": True,
            "keyboardNavigation": True, "compactQueueReachable": True,
            "realMotionFrames": len(frames), "mock": False,
        }, indent=2), encoding="utf-8")
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
