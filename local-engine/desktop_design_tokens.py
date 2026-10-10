from __future__ import annotations

from types import MappingProxyType

# Galaxy Native Workbench v1.6.1
# Neutral graphite surfaces + one blue action accent. The desktop application
# is an operational tool, not a neon dashboard; keep state colors semantic.
COLOR = MappingProxyType(
    {
        "bg": "#121315",
        "surface": "#161719",
        "surface_raised": "#1C1E22",
        "surface_elevated": "#22252A",
        "border": "#30333A",
        "border_subtle": "#26292F",
        "text_primary": "#F1F2F4",
        "text_secondary": "#A6A9AE",
        "text_subtle": "#777B82",
        "accent": "#6F8FFF",
        "accent_hover": "#829CFF",
        "info": "#78A9D4",
        "success": "#5FAF88",
        "warning": "#C99A54",
        "danger": "#D76A6A",
        "danger_hover": "#E17A7A",
        "focus": "#8EA6FF",
        "danger_contrast": "#250E10",
        "secondary_hover": "#2A2D33",
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

LAYOUT = MappingProxyType(
    {
        "none": SPACE["0"],
        "micro": SPACE["1"],
        "inline": SPACE["2"],
        "content": SPACE["3"],
        "section": SPACE["4"],
        "panel": SPACE["5"],
        "page": SPACE["6"],
    }
)

RADIUS = MappingProxyType(
    {
        "none": 0,
        "sm": 4,
        "md": 6,
        "lg": 8,
        "pill": 999,
    }
)

# Deliberately larger than the former 7/8/9pt scale. The old native UI was
# difficult to read on common 100-125% Windows scaling.
TYPE = MappingProxyType(
    {
        "family": "Segoe UI",
        "caption": 8,
        "body_sm": 9,
        "body": 10,
        "title_sm": 11,
        "title": 17,
        "brand": 18,
        "display": 20,
    }
)

MOTION = MappingProxyType(
    {
        "fast_ms": 100,
        "normal_ms": 150,
        "slow_ms": 220,
        "entrance_easing": "ease-out",
        "reversible_easing": "ease-in-out",
    }
)

CONTROL = MappingProxyType(
    {
        "button_pad_x": 14,
        "button_pad_y": 8,
        "button_compact_pad_x": 10,
        "button_compact_pad_y": 6,
        "target_min": 44,
        "target_comfortable": 44,
        "focus_ring_width": 2,
    }
)

SHADOW = MappingProxyType(
    {
        "none": "none",
        "low": "low",
        "dialog": "dialog",
    }
)

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
    if size_token not in TYPE or size_token == "family":
        raise KeyError(f"unknown type token: {size_token}")
    family = str(TYPE["family"])
    size = int(TYPE[size_token])
    return (family, size, "bold") if bold else (family, size)


def target_padding(line_height: int, *, compact: bool = False) -> int:
    if line_height <= 0:
        raise ValueError("line_height must be positive")
    base = int(CONTROL["button_compact_pad_y"] if compact else CONTROL["button_pad_y"])
    required = max(0, int(CONTROL["target_min"]) - int(line_height))
    return max(base, (required + 1) // 2)


def run_self_test() -> None:
    assert COLOR["focus"] != COLOR["bg"]
    assert SPACE["1"] == 4 and SPACE["10"] == 40
    assert tuple(LAYOUT.values()) == (0, 4, 8, 12, 16, 20, 24)
    assert all(value in SPACE.values() for value in LAYOUT.values())
    assert RADIUS["pill"] == 999
    assert TYPE["caption"] < TYPE["body"] < TYPE["title"] < TYPE["brand"] < TYPE["display"]
    assert MOTION["fast_ms"] < MOTION["normal_ms"] < MOTION["slow_ms"]
    assert CONTROL["target_min"] >= 44
    assert CONTROL["focus_ring_width"] >= 2
    assert BG == "#121315" and ACCENT == "#6F8FFF" and DANGER == "#D76A6A"
    assert font("body") == ("Segoe UI", 10)
    assert font("body_sm", bold=True) == ("Segoe UI", 9, "bold")
    assert target_padding(16) >= CONTROL["button_pad_y"]
    assert target_padding(64) == CONTROL["button_pad_y"]
    try:
        target_padding(0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid line height must fail closed")
    try:
        COLOR["bg"] = "#000000"  # type: ignore[index]
    except TypeError:
        pass
    else:
        raise AssertionError("design token mappings must be immutable")


if __name__ == "__main__":
    run_self_test()
    print("Desktop design token registry self-test passed")
