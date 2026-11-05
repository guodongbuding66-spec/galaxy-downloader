"""Interruptible motion for the native workbench. No runtime animation dependency."""
from __future__ import annotations

import os
import time
import tkinter as tk

from desktop_design_tokens import COLOR, MOTION
from desktop_workbench_style import ORBIT, button

# Motion Prompt #057 · MIT License (c) 2026 Shohei Ohtaki · https://showheyohtaki.github.io/motion-prompt/#057
# The 250 ms underline and easeInOutCubic are ported from the element and its UI kit.
# The two real panes switch immediately so keyboard focus never waits for a fade.
TAB_DURATION_MS = 250


def system_reduces_motion() -> bool:
    if os.name == "nt":
        import ctypes
        enabled = ctypes.c_int()
        try:
            # SPI_GETCLIENTAREAANIMATION
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
                return not bool(enabled.value)
        except (AttributeError, OSError):
            pass
    return False


def _ease_in_out_cubic(x: float) -> float:
    return 4 * x * x * x if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


class Tween:
    def __init__(self, owner, reduced, paint):
        self.owner, self.reduced, self.paint = owner, reduced, paint
        self.current = self.target = 0.0
        self.job = None
        owner.bind("<Destroy>", self._destroy, add="+")

    def _destroy(self, event):
        if event.widget is self.owner:
            self.cancel()

    def cancel(self):
        if self.job is not None:
            self.owner.after_cancel(self.job)
            self.job = None

    def finish(self):
        self.cancel()
        self.current = self.target
        self.paint(self.current)

    def go(self, target, duration, *, snap=False):
        self.cancel()
        self.target = target
        if self.reduced() or snap or abs(target - self.current) < 0.001:
            self.finish()
            return
        start, started = self.current, time.monotonic()

        def frame():
            self.job = None
            t = min(1.0, (time.monotonic() - started) * 1000 / duration)
            self.current = start + (target - start) * _ease_in_out_cubic(t)
            self.paint(self.current)
            if t < 1.0:
                self.job = self.owner.after(16, frame)

        frame()


class ModeTabs(tk.Frame):
    def __init__(self, parent, reduced, on_select):
        super().__init__(parent, bg=COLOR["surface"])
        self.index = 0
        self.on_select = on_select
        row = tk.Frame(self, bg=COLOR["surface"])
        row.pack(anchor="w")
        self.buttons = []
        for i, title in enumerate(("视频与音频", "网页原图")):
            row.grid_columnconfigure(i, weight=1, uniform="mode")
            control = button(row, title, lambda index=i: self.select(index), kind="Tab")
            control.grid(row=0, column=i, sticky="ew", ipadx=8)
            control.bind("<Left>", lambda _event, index=i: self._move(1 - index))
            control.bind("<Right>", lambda _event, index=i: self._move(1 - index))
            self.buttons.append(control)
        self.buttons[0].state(["selected"])
        self.indicator = tk.Canvas(self, height=2, bg=ORBIT["line"], highlightthickness=0)
        self.indicator.pack(anchor="w")
        row.bind("<Configure>", lambda event: self.indicator.configure(width=event.width))
        self._bar = self.indicator.create_rectangle(0, 0, 0, 2, fill=COLOR["accent"], width=0)
        self.tween = Tween(self, reduced, self._paint)
        self.indicator.bind("<Configure>", lambda _event: self._paint(self.tween.current))

    def _paint(self, position):
        width = self.indicator.winfo_width() / 2
        self.indicator.coords(self._bar, width * position, 0, width * (position + 1), 2)

    def _move(self, index):
        self.buttons[index].focus_set()
        self.select(index)
        return "break"

    def select(self, index):
        if self.index == index:
            return
        self.buttons[self.index].state(["!selected"])
        self.index = index
        self.buttons[index].state(["selected"])
        self.on_select(index)
        self.tween.go(float(index), TAB_DURATION_MS)


class ProgressMeter(tk.Canvas):
    def __init__(self, parent, variable, reduced):
        super().__init__(parent, height=6, bg=ORBIT["line"], highlightthickness=0)
        self.variable = variable
        self._bar = self.create_rectangle(0, 0, 0, 6, fill=COLOR["accent"], width=0)
        self.tween = Tween(self, reduced, self._paint)
        self.bind("<Configure>", lambda _event: self._paint(self.tween.current))
        self.trace = variable.trace_add("write", self._update)
        self.bind("<Destroy>", self._remove_trace, add="+")
        self._update()

    def _paint(self, value):
        self.coords(self._bar, 0, 0, self.winfo_width() * value / 100, 6)

    def _update(self, *_args):
        value = min(100.0, max(0.0, float(self.variable.get())))
        # A reset/new job never animates a stale bar backwards.
        self.tween.go(value, MOTION["normal_ms"], snap=value <= self.tween.target)

    def _remove_trace(self, event):
        if event.widget is self:
            self.variable.trace_remove("write", self.trace)
