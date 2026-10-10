from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "docs" / "design"
DESKTOP_UI = ROOT / "local-engine" / "desktop_ui.py"
RUNTIME_TOKENS = ROOT / "local-engine" / "desktop_design_tokens.py"

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

# compatibility alias -> (semantic runtime token, approved value)
RUNTIME_COLORS = {
    "BG": ("bg", "#0E1116"),
    "PANEL": ("surface", "#141922"),
    "PANEL_2": ("surface_raised", "#1A2130"),
    "PANEL_3": ("surface_elevated", "#202A3A"),
    "BORDER": ("border", "#334052"),
    "BORDER_SOFT": ("border_subtle", "#273241"),
    "TEXT": ("text_primary", "#F7F9FC"),
    "MUTED": ("text_secondary", "#C2CAD6"),
    "SUBTLE": ("text_subtle", "#8F9AAA"),
    "ACCENT": ("accent", "#4F7DFF"),
    "ACCENT_HOVER": ("accent_hover", "#6C94FF"),
    "CYAN": ("info", "#75A7D8"),
    "SUCCESS": ("success", "#65BE92"),
    "DANGER": ("danger", "#E27676"),
    "DANGER_HOVER": ("danger_hover", "#EC8787"),
    "WARNING": ("warning", "#D9A85F"),
}


def assert_design_files() -> None:
    missing = [name for name in REQUIRED_FILES if not (DESIGN / name).is_file()]
    assert not missing, f"missing design-system docs: {missing}"
    for name in REQUIRED_FILES:
        text = (DESIGN / name).read_text(encoding="utf-8")
        assert text.startswith("# "), f"{name} must start with an H1"
        assert len(text.strip()) >= 300, f"{name} is too small to be an actionable contract"


def assert_runtime_token_mapping() -> None:
    runtime_source = RUNTIME_TOKENS.read_text(encoding="utf-8")
    facade_source = DESKTOP_UI.read_text(encoding="utf-8")
    docs = (DESIGN / "TOKENS.md").read_text(encoding="utf-8")

    for alias, (semantic_name, value) in RUNTIME_COLORS.items():
        semantic_pattern = rf'^\s*"{re.escape(semantic_name)}"\s*:\s*"{re.escape(value)}",?$'
        assert re.search(semantic_pattern, runtime_source, flags=re.MULTILINE), (
            f"runtime semantic token changed without design update: {semantic_name}"
        )
        alias_pattern = rf'^{re.escape(alias)}\s*=\s*COLOR\["{re.escape(semantic_name)}"\]$'
        assert re.search(alias_pattern, runtime_source, flags=re.MULTILINE), (
            f"runtime compatibility alias is not token-backed: {alias}"
        )
        assert value in docs and f"`{alias}`" in docs, f"token mapping missing: {alias}"
        assert value not in facade_source, f"desktop_ui duplicated semantic color literal: {alias}"

    assert "from desktop_design_tokens import (" in facade_source
    assert "_RUNTIME_ALIASES" in facade_source


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
