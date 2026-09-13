from __future__ import annotations

from types import MappingProxyType

# Semantic color tokens. These are the single runtime source for the current
# Galaxy Desktop palette; compatibility aliases in desktop_ui.py may re-export
# them while older workspaces migrate incrementally.
COLOR = MappingProxyType(
    {
        "bg": "#080C14",
        "surface": "#0F1624",
        "surface_raised": "#141E30",
        "surface_elevated": "#1A2740",
        "border": "#25324B",
        "border_subtle": "#1C2940",
        "text_primary": "#F6F8FC",
        "text_secondary": "#9AA6BB",
        "text_subtle": "#6F7D95",
        "accent": "#7C6CFF",
        "accent_hover": "#9185FF",
        "info": "#36D7C4",
        "success": "#45D18A",
        "warning": "#F2B84B",
        "danger": "#FF6278",
        "danger_hover": "#FF788B",
        "focus": "#9185FF",
        "danger_contrast": "#180408",
        "secondary_hover": "#233352",
        "on_accent": "#FFFFFF",
    }
)

SPACE = MappingProxyType(
    {
        "0": 0,
        "1": 4,
        "2": 8,
        "3": 12,
        "4": 16,
        "5": 20,
        "6": 24,
        "8": 32,
        "10": 40,
    }
)

RADIUS = MappingProxyType(
    {
        "none": 0,
        "sm": 4,
        "md": 8,
        "lg": 12,
        "pill": 999,
    }
)

TYPE = MappingProxyType(
    {
        "family": "Segoe UI",
        "caption": 7,
        "body_sm": 8,
        "body": 9,
        "title_sm": 10,
        "title": 16,
        "display": 18,
    }
)

MOTION = MappingProxyType(
    {
        "fast_ms": 100,
        "normal_ms": 180,
        "slow_ms": 260,
        "entrance_easing": "ease-out",
        "reversible_easing": "ease-in-out",
    }
)

CONTROL = MappingProxyType(
    {
        "button_pad_x": 14,
        "button_pad_y": 8,
        "button_compact_pad_x": 9,
        "button_compact_pad_y": 5,
        "target_min": 36,
        "target_comfortable": 44,
    }
)

SHADOW = MappingProxyType(
    {
        "none": "none",
        "low": "low",
        "dialog": "dialog",
    }
)

# Stable compatibility aliases used throughout existing Desktop workspaces.
BG = COLOR["bg"]
PANEL = COLOR["surface"]
PANEL_2 = COLOR["surface_raised"]
PANEL_3 = COLOR["surface_elevated"]
BORDER = COLOR["border"]
BORDER_SOFT = COLOR["border_subtle"]
TEXT = COLOR["text_primary"]
MUTED = COLOR["text_secondary"]
SUBTLE = COLOR["text_subtle"]
ACCENT = COLOR["accent"]
ACCENT_HOVER = COLOR["accent_hover"]
CYAN = COLOR["info"]
SUCCESS = COLOR["success"]
WARNING = COLOR["warning"]
DANGER = COLOR["danger"]
DANGER_HOVER = COLOR["danger_hover"]
FOCUS = COLOR["focus"]


def font(size_token: str = "body", *, bold: bool = False) -> tuple[str, int] | tuple[str, int, str]:
    """Return one Tk-compatible font tuple from the shared type scale."""
    if size_token not in TYPE or size_token == "family":
        raise KeyError(f"unknown type token: {size_token}")
    family = str(TYPE["family"])
    size = int(TYPE[size_token])
    return (family, size, "bold") if bold else (family, size)


def run_self_test() -> None:
    assert COLOR["focus"] == COLOR["accent_hover"]
    assert SPACE["1"] == 4 and SPACE["10"] == 40
    assert RADIUS["pill"] == 999
    assert TYPE["caption"] < TYPE["body"] < TYPE["title"]
    assert MOTION["fast_ms"] < MOTION["normal_ms"] < MOTION["slow_ms"]
    assert CONTROL["target_min"] >= 36
    assert BG == "#080C14" and ACCENT == "#7C6CFF" and DANGER == "#FF6278"
    assert font("body") == ("Segoe UI", 9)
    assert font("body_sm", bold=True) == ("Segoe UI", 8, "bold")
    try:
        COLOR["bg"] = "#000000"  # type: ignore[index]
    except TypeError:
        pass
    else:  # pragma: no cover - MappingProxyType must stay immutable.
        raise AssertionError("design token mappings must be immutable")


if __name__ == "__main__":
    run_self_test()
    print("Desktop design token registry self-test passed")
