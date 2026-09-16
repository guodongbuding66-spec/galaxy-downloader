from __future__ import annotations

import ast
import importlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))


def _contains_raw_spacing_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_contains_raw_spacing_literal(item) for item in node.elts)
    if isinstance(node, ast.IfExp):
        return _contains_raw_spacing_literal(node.body) or _contains_raw_spacing_literal(node.orelse)
    if isinstance(node, ast.BinOp):
        return _contains_raw_spacing_literal(node.left) or _contains_raw_spacing_literal(node.right)
    if isinstance(node, ast.UnaryOp):
        return _contains_raw_spacing_literal(node.operand)
    return False


def _raw_spacing_violations(source_path: pathlib.Path) -> list[str]:
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in {"padx", "pady", "padding"} and _contains_raw_spacing_literal(keyword.value):
                    violations.append(f"line {getattr(keyword, 'lineno', '?')}: {keyword.arg}")
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value in {"padx", "pady", "padding"}
                    and value is not None
                    and _contains_raw_spacing_literal(value)
                ):
                    violations.append(f"line {getattr(key, 'lineno', '?')}: {key.value}")
    return violations


def _assert_spacing_is_tokenized(source_path: pathlib.Path) -> None:
    source = source_path.read_text(encoding="utf-8")
    violations = _raw_spacing_violations(source_path)
    assert not violations, "raw page spacing literals found: " + ", ".join(violations)
    assert 'from desktop_design_tokens import LAYOUT' in source
    assert 'LAYOUT["page"]' in source
    assert 'LAYOUT["section"]' in source
    assert 'LAYOUT["content"]' in source
    assert 'LAYOUT["inline"]' in source
    assert 'LAYOUT["micro"]' in source
    assert _contains_raw_spacing_literal(ast.parse("4", mode="eval").body)
    conditional = ast.parse("(SPACE_A if index == 0 else SPACE_B)", mode="eval").body
    assert not _contains_raw_spacing_literal(conditional)
    conditional_bad = ast.parse("(4 if index == 0 else SPACE_B)", mode="eval").body
    assert _contains_raw_spacing_literal(conditional_bad)


def _assert_transfer_workspace_tokenized(source_path: pathlib.Path) -> None:
    source = source_path.read_text(encoding="utf-8")
    violations = _raw_spacing_violations(source_path)
    assert not violations, f"raw transfer spacing literals found in {source_path.name}: " + ", ".join(violations)
    assert 'from desktop_design_tokens import LAYOUT, font' in source
    assert 'LAYOUT["section"]' in source
    assert 'LAYOUT["content"]' in source
    assert 'LAYOUT["inline"]' in source
    assert 'LAYOUT["micro"]' in source
    assert '"Segoe UI"' not in source, f"direct font family leaked into {source_path.name}"
    assert "'#ffffff'" not in source and '"#ffffff"' not in source, f"raw color leaked into {source_path.name}"


def _assert_accessibility_contract() -> None:
    source = (LOCAL_ENGINE / "desktop_accessibility.py").read_text(encoding="utf-8")
    ui_source = (LOCAL_ENGINE / "desktop_ui.py").read_text(encoding="utf-8")
    assert '"<Escape>"' in source
    assert '"<Map>"' in source
    assert 'protocol("WM_DELETE_WINDOW")' in source
    assert "focus_first_control" in source
    assert "GALAXY_REDUCE_MOTION" in source
    assert "install_desktop_accessibility(window)" in ui_source
    assert "takefocus=True" in ui_source
    assert "highlightcolor=FOCUS" in ui_source


def main() -> None:
    tokens = importlib.import_module("desktop_design_tokens")
    ui = importlib.import_module("desktop_ui")
    impl = importlib.import_module("_desktop_ui_impl")
    accessibility = importlib.import_module("desktop_accessibility")

    tokens.run_self_test()
    ui.run_self_test()
    accessibility.run_self_test()

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

    for helper in ("_divider", "_section_title", "_status_chip", "_metric"):
        assert getattr(ui, helper) is getattr(impl, helper), helper
    try:
        getattr(ui, "_definitely_missing_helper")
    except AttributeError:
        pass
    else:
        raise AssertionError("unknown helpers must still raise AttributeError")

    assert ui.FONT_FAMILY == tokens.TYPE["family"]
    assert ui.BUTTON_PAD_X == tokens.CONTROL["button_pad_x"]
    assert ui.BUTTON_PAD_Y == tokens.CONTROL["button_pad_y"]
    assert ui.BUTTON_COMPACT_PAD_X == tokens.CONTROL["button_compact_pad_x"]
    assert ui.BUTTON_COMPACT_PAD_Y == tokens.CONTROL["button_compact_pad_y"]
    assert ui.FOCUS_RING_WIDTH == tokens.CONTROL["focus_ring_width"]
    assert tokens.CONTROL["target_min"] >= 44
    assert tokens.CONTROL["focus_ring_width"] >= 2
    assert tuple(tokens.LAYOUT.values()) == (0, 4, 8, 12, 16, 20, 24)
    assert all(value in tokens.SPACE.values() for value in tokens.LAYOUT.values())
    assert ui._TYPE_SIZE_BY_LEGACY[7] == tokens.TYPE["caption"]
    assert ui._TYPE_SIZE_BY_LEGACY[8] == tokens.TYPE["body_sm"]
    assert ui._TYPE_SIZE_BY_LEGACY[9] == tokens.TYPE["body"]
    assert ui._TYPE_SIZE_BY_LEGACY[10] == tokens.TYPE["title_sm"]
    assert ui._TYPE_SIZE_BY_LEGACY[16] == tokens.TYPE["title"]
    assert ui._TYPE_SIZE_BY_LEGACY[17] == tokens.TYPE["brand"]
    assert ui._TYPE_SIZE_BY_LEGACY[18] == tokens.TYPE["display"]

    for line_height in (12, 16, 20, 32, 44, 64):
        for compact in (False, True):
            pad_y = tokens.target_padding(line_height, compact=compact)
            base = tokens.CONTROL["button_compact_pad_y" if compact else "button_pad_y"]
            assert pad_y >= base
            if line_height < tokens.CONTROL["target_min"]:
                assert line_height + 2 * pad_y >= tokens.CONTROL["target_min"]
    try:
        tokens.target_padding(0)
    except ValueError:
        pass
    else:
        raise AssertionError("target padding must reject invalid font metrics")

    assert callable(ui.install_desktop_ui)
    assert isinstance(ui.SPONSOR_LABELS, tuple)
    assert ui.WEBSITE_URL.startswith("https://")

    source = (LOCAL_ENGINE / "desktop_ui.py").read_text(encoding="utf-8")
    for value in tokens.COLOR.values():
        assert value not in source, f"semantic color literal leaked into desktop_ui.py: {value}"

    _assert_spacing_is_tokenized(LOCAL_ENGINE / "_desktop_ui_impl.py")
    for name in ("desktop_transfers.py", "desktop_qr_transfer.py", "desktop_telegram_download.py"):
        _assert_transfer_workspace_tokenized(LOCAL_ENGINE / name)
    _assert_accessibility_contract()

    print("Desktop UI design-token, focus, Escape-dialog, and reduced-motion contracts passed")


if __name__ == "__main__":
    main()
