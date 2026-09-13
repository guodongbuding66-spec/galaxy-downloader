from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "docs" / "design"
DESKTOP_UI = ROOT / "local-engine" / "desktop_ui.py"

REQUIRED_FILES = (
    "DESIGN.md",
    "TOKENS.md",
    "ICONOGRAPHY.md",
    "MOTION.md",
    "COMPONENTS.md",
    "ACCESSIBILITY.md",
    "SCREEN_MAP.md",
)

REQUIRED_COMPONENTS = (
    "Button",
    "IconButton",
    "Input",
    "Select",
    "Checkbox",
    "Switch",
    "Segmented Control",
    "Tabs",
    "Sidebar Item",
    "Table",
    "Progress",
    "Toast",
    "Dialog",
    "Drawer",
    "Tooltip",
    "Empty State",
    "Skeleton",
    "Error State",
)

RUNTIME_COLORS = {
    "BG": "#080C14",
    "PANEL": "#0F1624",
    "PANEL_2": "#141E30",
    "PANEL_3": "#1A2740",
    "BORDER": "#25324B",
    "BORDER_SOFT": "#1C2940",
    "TEXT": "#F6F8FC",
    "MUTED": "#9AA6BB",
    "SUBTLE": "#6F7D95",
    "ACCENT": "#7C6CFF",
    "ACCENT_HOVER": "#9185FF",
    "CYAN": "#36D7C4",
    "SUCCESS": "#45D18A",
    "DANGER": "#FF6278",
    "DANGER_HOVER": "#FF788B",
    "WARNING": "#F2B84B",
}


def assert_design_files() -> None:
    missing = [name for name in REQUIRED_FILES if not (DESIGN / name).is_file()]
    assert not missing, f"missing design-system docs: {missing}"
    for name in REQUIRED_FILES:
        text = (DESIGN / name).read_text(encoding="utf-8")
        assert text.startswith("# "), f"{name} must start with an H1"
        assert len(text.strip()) >= 300, f"{name} is too small to be an actionable contract"


def assert_runtime_token_mapping() -> None:
    source = DESKTOP_UI.read_text(encoding="utf-8")
    tokens = (DESIGN / "TOKENS.md").read_text(encoding="utf-8")
    for name, value in RUNTIME_COLORS.items():
        pattern = rf"^{re.escape(name)}\s*=\s*\"{re.escape(value)}\"$"
        assert re.search(pattern, source, flags=re.MULTILINE), f"runtime token changed without design update: {name}"
        assert value in tokens and f"`{name}`" in tokens, f"token mapping missing: {name}"


def assert_component_contract() -> None:
    text = (DESIGN / "COMPONENTS.md").read_text(encoding="utf-8")
    for component in REQUIRED_COMPONENTS:
        assert f"## {component}" in text, f"component contract missing: {component}"


def assert_accessibility_contract() -> None:
    text = (DESIGN / "ACCESSIBILITY.md").read_text(encoding="utf-8").lower()
    for phrase in ("keyboard", "focus", "visible label", "color", "reduced motion", "disabled"):
        assert phrase in text, f"accessibility contract missing: {phrase}"


def assert_screen_map() -> None:
    text = (DESIGN / "SCREEN_MAP.md").read_text(encoding="utf-8")
    for screen in (
        "Home / Download Workbench",
        "Downloads",
        "Media Library",
        "Transcript",
        "AI",
        "Courses",
        "Reader",
        "Music",
        "Subscriptions",
        "Transfer Center",
        "Plugins",
        "Settings",
    ):
        assert screen in text, f"screen map missing: {screen}"


def run_test() -> None:
    assert_design_files()
    assert_runtime_token_mapping()
    assert_component_contract()
    assert_accessibility_contract()
    assert_screen_map()


if __name__ == "__main__":
    run_test()
    print("Design system documentation contract passed")
