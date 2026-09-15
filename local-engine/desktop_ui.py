from __future__ import annotations

"""Shared Desktop UI facade backed by the runtime design-token registry.

The original implementation stays isolated in ``_desktop_ui_impl`` so this
migration can preserve the public module contract while moving runtime palette,
typography, interaction metrics, and primary button spacing to one semantic
source of truth.
"""

import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

import _desktop_ui_impl as _impl
from desktop_design_tokens import (
    ACCENT,
    ACCENT_HOVER,
    BG,
    BORDER,
    BORDER_SOFT,
    COLOR,
    CONTROL,
    CYAN,
    DANGER,
    DANGER_HOVER,
    FOCUS,
    MUTED,
    PANEL,
    PANEL_2,
    PANEL_3,
    SUBTLE,
    SUCCESS,
    TEXT,
    TYPE,
    WARNING,
    font,
    target_padding,
)

# Rebind the implementation's dynamic module globals before any widgets are
# constructed. Existing functions/classes resolve these values at call time.
_RUNTIME_ALIASES = {
    "BG": BG,
    "PANEL": PANEL,
    "PANEL_2": PANEL_2,
    "PANEL_3": PANEL_3,
    "BORDER": BORDER,
    "BORDER_SOFT": BORDER_SOFT,
    "TEXT": TEXT,
    "MUTED": MUTED,
    "SUBTLE": SUBTLE,
    "ACCENT": ACCENT,
    "ACCENT_HOVER": ACCENT_HOVER,
    "CYAN": CYAN,
    "SUCCESS": SUCCESS,
    "DANGER": DANGER,
    "DANGER_HOVER": DANGER_HOVER,
    "WARNING": WARNING,
}
for _name, _value in _RUNTIME_ALIASES.items():
    setattr(_impl, _name, _value)

DANGER_CONTRAST = COLOR["danger_contrast"]
SECONDARY_HOVER = COLOR["secondary_hover"]
FONT_FAMILY = str(TYPE["family"])
BUTTON_PAD_X = int(CONTROL["button_pad_x"])
BUTTON_PAD_Y = int(CONTROL["button_pad_y"])
BUTTON_COMPACT_PAD_X = int(CONTROL["button_compact_pad_x"])
BUTTON_COMPACT_PAD_Y = int(CONTROL["button_compact_pad_y"])
FOCUS_RING_WIDTH = int(CONTROL["focus_ring_width"])

# Preserve the legacy numeric call signature while sourcing every currently
# used Desktop type size from TYPE. This lets page call sites migrate to named
# tokens independently without leaving 17/18pt display exceptions outside the
# runtime scale.
_TYPE_SIZE_BY_LEGACY = {
    7: int(TYPE["caption"]),
    8: int(TYPE["body_sm"]),
    9: int(TYPE["body"]),
    10: int(TYPE["title_sm"]),
    16: int(TYPE["title"]),
    17: int(TYPE["brand"]),
    18: int(TYPE["display"]),
}


class ActionButton(_impl.ActionButton):
    """Compatibility button backed by shared type, target, and focus tokens."""

    def __init__(
        self,
        master,
        *,
        text: str,
        command: Callable[[], None],
        kind: str = "secondary",
        width: int | None = None,
        compact: bool = False,
    ) -> None:
        super().__init__(
            master,
            text=text,
            command=command,
            kind=kind,
            width=width,
            compact=compact,
        )
        button_font = font("body_sm" if compact else "body", bold=True)
        try:
            line_height = int(tkfont.Font(master=self, font=button_font).metrics("linespace"))
        except (tk.TclError, RuntimeError):
            # Keep construction resilient on unusual Tk builds. The fallback is
            # deterministic and still drives target_padding through the token
            # contract rather than adding a second hard-coded padding value.
            line_height = max(1, int(TYPE["body_sm" if compact else "body"]) * 2)
        self.configure(
            font=button_font,
            padx=BUTTON_COMPACT_PAD_X if compact else BUTTON_PAD_X,
            pady=target_padding(line_height, compact=compact),
            takefocus=True,
            highlightthickness=FOCUS_RING_WIDTH,
            highlightbackground=self._base,
            highlightcolor=FOCUS,
        )


def _label(
    master,
    text: str | None = None,
    *,
    variable=None,
    size=9,
    weight="normal",
    color=TEXT,
    bg=PANEL,
    **kwargs,
):
    widget = _ORIGINAL_LABEL(
        master,
        text,
        variable=variable,
        size=size,
        weight=weight,
        color=color,
        bg=bg,
        **kwargs,
    )
    if isinstance(size, str):
        if size not in TYPE or size == "family":
            raise KeyError(f"unknown type token: {size}")
        token_size = int(TYPE[size])
    else:
        token_size = _TYPE_SIZE_BY_LEGACY.get(int(size), int(size))
    widget.configure(font=(FONT_FAMILY, token_size, weight))
    return widget


def _entry(master, variable: tk.Variable, width: int) -> tk.Entry:
    widget = _ORIGINAL_ENTRY(master, variable, width)
    widget.configure(font=font("body_sm"))
    return widget


def _check(master, text: str, variable: tk.BooleanVar) -> tk.Checkbutton:
    widget = _ORIGINAL_CHECK(master, text, variable)
    widget.configure(font=font("body_sm"))
    return widget


# Capture legacy helpers once, then replace the implementation globals. All
# existing implementation functions resolve these names dynamically, so every
# current workspace receives token-backed controls without a call-site rewrite.
_ORIGINAL_LABEL = _impl._label
_ORIGINAL_ENTRY = _impl._entry
_ORIGINAL_CHECK = _impl._check
_impl.ActionButton = ActionButton
_impl._label = _label
_impl._entry = _entry
_impl._check = _check

SPONSOR_LABELS = _impl.SPONSOR_LABELS
WEBSITE_URL = _impl.WEBSITE_URL
install_desktop_ui = _impl.install_desktop_ui


def __getattr__(name: str):
    """Delegate legacy helpers that have not migrated to token wrappers yet.

    Existing Desktop workspaces historically imported ``desktop_ui`` as a
    helper module and called internal helpers such as ``_divider``. Keeping a
    single delegation point preserves that contract while avoiding duplicate
    implementations in this facade. Token-overridden names above always win.
    """

    try:
        return getattr(_impl, name)
    except AttributeError as exc:
        raise AttributeError(f"module 'desktop_ui' has no attribute {name!r}") from exc


def run_self_test() -> None:
    for name, expected in _RUNTIME_ALIASES.items():
        assert getattr(_impl, name) == expected
    assert BG == COLOR["bg"]
    assert ACCENT == COLOR["accent"]
    assert DANGER_CONTRAST == COLOR["danger_contrast"]
    assert BUTTON_PAD_X == CONTROL["button_pad_x"]
    assert FONT_FAMILY == TYPE["family"]
    assert FOCUS_RING_WIDTH == CONTROL["focus_ring_width"]
    assert CONTROL["target_min"] >= 44
    assert _impl.ActionButton is ActionButton
    assert _impl._label is _label
    assert _impl._entry is _entry
    assert _impl._check is _check
    assert __getattr__("_divider") is _impl._divider
    assert __getattr__("_section_title") is _impl._section_title
    assert issubclass(ActionButton, tk.Button)
    assert _TYPE_SIZE_BY_LEGACY[8] == TYPE["body_sm"]
    assert _TYPE_SIZE_BY_LEGACY[9] == TYPE["body"]
    assert _TYPE_SIZE_BY_LEGACY[17] == TYPE["brand"]
    assert _TYPE_SIZE_BY_LEGACY[18] == TYPE["display"]
    assert target_padding(16) >= BUTTON_PAD_Y


if __name__ == "__main__":
    run_self_test()
    print("Desktop UI token facade self-test passed")
