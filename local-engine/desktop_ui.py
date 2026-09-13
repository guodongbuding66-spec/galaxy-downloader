from __future__ import annotations

"""Shared Desktop UI facade backed by the runtime design-token registry.

The original implementation stays isolated in ``_desktop_ui_impl`` so this
migration can preserve the public module contract while moving its runtime
palette and control metrics to one semantic source of truth.
"""

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
    MUTED,
    PANEL,
    PANEL_2,
    PANEL_3,
    SUBTLE,
    SUCCESS,
    TEXT,
    TYPE,
    WARNING,
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

# Named semantic values used by ActionButton in the legacy implementation.
# Expose them here for new code and for migration tests; the implementation
# consumes the equivalent registry values through its runtime aliases.
DANGER_CONTRAST = COLOR["danger_contrast"]
SECONDARY_HOVER = COLOR["secondary_hover"]
FONT_FAMILY = TYPE["family"]
BUTTON_PAD_X = CONTROL["button_pad_x"]
BUTTON_PAD_Y = CONTROL["button_pad_y"]
BUTTON_COMPACT_PAD_X = CONTROL["button_compact_pad_x"]
BUTTON_COMPACT_PAD_Y = CONTROL["button_compact_pad_y"]

ActionButton = _impl.ActionButton
SPONSOR_LABELS = _impl.SPONSOR_LABELS
WEBSITE_URL = _impl.WEBSITE_URL
install_desktop_ui = _impl.install_desktop_ui


def run_self_test() -> None:
    for name, expected in _RUNTIME_ALIASES.items():
        assert getattr(_impl, name) == expected
    assert BG == COLOR["bg"]
    assert ACCENT == COLOR["accent"]
    assert DANGER_CONTRAST == COLOR["danger_contrast"]
    assert BUTTON_PAD_X == CONTROL["button_pad_x"]
    assert ActionButton.__module__ == "_desktop_ui_impl"


if __name__ == "__main__":
    run_self_test()
    print("Desktop UI token facade self-test passed")
