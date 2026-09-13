from __future__ import annotations

import importlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))


def main() -> None:
    tokens = importlib.import_module("desktop_design_tokens")
    ui = importlib.import_module("desktop_ui")
    impl = importlib.import_module("_desktop_ui_impl")

    ui.run_self_test()

    aliases = {
        "BG": "bg",
        "PANEL": "surface",
        "PANEL_2": "surface_raised",
        "PANEL_3": "surface_elevated",
        "BORDER": "border",
        "BORDER_SOFT": "border_subtle",
        "TEXT": "text_primary",
        "MUTED": "text_secondary",
        "SUBTLE": "text_subtle",
        "ACCENT": "accent",
        "ACCENT_HOVER": "accent_hover",
        "CYAN": "info",
        "SUCCESS": "success",
        "WARNING": "warning",
        "DANGER": "danger",
        "DANGER_HOVER": "danger_hover",
    }
    for public_name, token_name in aliases.items():
        expected = tokens.COLOR[token_name]
        assert getattr(ui, public_name) == expected
        assert getattr(impl, public_name) == expected

    assert impl.ActionButton is ui.ActionButton
    assert impl._label is ui._label
    assert impl._entry is ui._entry
    assert impl._check is ui._check

    assert ui.FONT_FAMILY == tokens.TYPE["family"]
    assert ui.BUTTON_PAD_X == tokens.CONTROL["button_pad_x"]
    assert ui.BUTTON_PAD_Y == tokens.CONTROL["button_pad_y"]
    assert ui.BUTTON_COMPACT_PAD_X == tokens.CONTROL["button_compact_pad_x"]
    assert ui.BUTTON_COMPACT_PAD_Y == tokens.CONTROL["button_compact_pad_y"]
    assert ui._TYPE_SIZE_BY_LEGACY[7] == tokens.TYPE["caption"]
    assert ui._TYPE_SIZE_BY_LEGACY[8] == tokens.TYPE["body_sm"]
    assert ui._TYPE_SIZE_BY_LEGACY[9] == tokens.TYPE["body"]
    assert ui._TYPE_SIZE_BY_LEGACY[10] == tokens.TYPE["title_sm"]
    assert ui._TYPE_SIZE_BY_LEGACY[16] == tokens.TYPE["title"]

    # Public entrypoints used by engine.py and workspace hooks remain stable.
    assert callable(ui.install_desktop_ui)
    assert isinstance(ui.SPONSOR_LABELS, tuple)
    assert ui.WEBSITE_URL.startswith("https://")

    print("Desktop UI design-token facade contract passed")


if __name__ == "__main__":
    main()
