from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from runtime_storage import state_dir as runtime_state_dir

PREFERENCES_FILENAME = "desktop-hotkey.json"
MAX_SHORTCUT_CHARS = 64

_MODIFIER_ALIASES = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "alt": "Alt",
    "option": "Alt",
    "shift": "Shift",
    "super": "Super",
    "meta": "Super",
    "win": "Super",
    "windows": "Super",
}
_MODIFIER_ORDER = ("Ctrl", "Alt", "Shift", "Super")
_REQUIRED_NON_SHIFT_MODIFIERS = {"Ctrl", "Alt", "Super"}
_NAMED_KEYS = {
    "space": "Space",
    "tab": "Tab",
    "enter": "Enter",
    "return": "Enter",
    "escape": "Escape",
    "esc": "Escape",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "insert": "Insert",
    "delete": "Delete",
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
}


def _preferences_path(engine_module) -> Path:
    target = runtime_state_dir(engine_module)
    target.mkdir(parents=True, exist_ok=True)
    return target / PREFERENCES_FILENAME


def _normalize_main_key(token: str) -> str:
    value = token.strip()
    if not value:
        raise ValueError("Shortcut must include a main key")
    lower = value.lower().replace(" ", "")
    if lower in _NAMED_KEYS:
        return _NAMED_KEYS[lower]
    if len(value) == 1 and value.isascii() and value.isalnum():
        return value.upper()
    if lower.startswith("f") and lower[1:].isdigit():
        number = int(lower[1:])
        if 1 <= number <= 24:
            return f"F{number}"
    raise ValueError("Unsupported shortcut key")


def normalize_linux_hotkey_shortcut(value: object) -> str:
    """Normalize a user-facing Linux shortcut without touching OS APIs.

    An empty value deliberately means "not configured". Non-empty shortcuts
    require at least one of Ctrl/Alt/Super so a global shortcut cannot silently
    capture an ordinary typing key or Shift-only character input.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > MAX_SHORTCUT_CHARS:
        raise ValueError("Shortcut is too long")

    parts = [part.strip() for part in text.split("+")]
    if len(parts) < 2 or any(not part for part in parts):
        raise ValueError("Shortcut must contain modifiers and one main key")

    modifier_tokens = parts[:-1]
    main_key = _normalize_main_key(parts[-1])
    modifiers: set[str] = set()
    for token in modifier_tokens:
        canonical = _MODIFIER_ALIASES.get(token.lower())
        if canonical is None:
            raise ValueError(f"Unsupported shortcut modifier: {token}")
        if canonical in modifiers:
            raise ValueError(f"Duplicate shortcut modifier: {canonical}")
        modifiers.add(canonical)

    if not modifiers.intersection(_REQUIRED_NON_SHIFT_MODIFIERS):
        raise ValueError("Shortcut must include Ctrl, Alt, or Super")

    ordered = [modifier for modifier in _MODIFIER_ORDER if modifier in modifiers]
    return "+".join([*ordered, main_key])


def clean_linux_hotkey_preferences(value: object) -> dict[str, str]:
    raw = value if isinstance(value, dict) else {}
    try:
        shortcut = normalize_linux_hotkey_shortcut(raw.get("shortcut", ""))
    except ValueError:
        # Corrupt or obsolete persisted input must never activate a broad global
        # shortcut. Fail closed until the user explicitly saves a valid value.
        shortcut = ""
    return {"shortcut": shortcut}


def load_linux_hotkey_preferences(engine_module) -> dict[str, str]:
    try:
        raw = json.loads(_preferences_path(engine_module).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {"shortcut": ""}
    return clean_linux_hotkey_preferences(raw)


def save_linux_hotkey_preferences(engine_module, shortcut: object) -> dict[str, str]:
    normalized = normalize_linux_hotkey_shortcut(shortcut)
    payload = {"shortcut": normalized}
    path = _preferences_path(engine_module)
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return payload


def linux_hotkey_preference_status(engine_module, *, platform: str | None = None) -> dict[str, Any]:
    value = str(platform or sys.platform).lower()
    configurable = value.startswith("linux")
    shortcut = ""
    if configurable:
        shortcut = str(load_linux_hotkey_preferences(engine_module).get("shortcut") or "")
    return {
        "globalHotkeyConfigurable": configurable,
        "globalHotkeyConfigured": bool(shortcut),
        "globalHotkeyPreference": shortcut,
    }


def install_linux_hotkey_preferences(engine_module):
    """Expose the Linux shortcut preference contract through bridge status.

    This layer intentionally does not claim Linux runtime availability. The
    platform backend remains fail-closed until the XDG portal runtime contract is
    implemented separately.
    """
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_linux_hotkey_preferences_installed", False):
        return window_cls

    original_bridge_status = window_cls.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        status = linux_hotkey_preference_status(engine_module)
        payload.update(status)
        if status["globalHotkeyConfigurable"]:
            # desktop_hotkey still correctly reports availability=false on Linux;
            # expose the configured value independently so Settings can edit it
            # before a portal session exists.
            payload["globalHotkey"] = status["globalHotkeyPreference"]
        return payload

    window_cls.bridge_status = bridge_status
    window_cls._galaxy_linux_hotkey_preferences_installed = True
    engine_module._galaxy_linux_hotkey_preferences_installed = True
    return window_cls


def run_linux_hotkey_preferences_self_test() -> None:
    import tempfile

    assert normalize_linux_hotkey_shortcut("") == ""
    assert normalize_linux_hotkey_shortcut(" control + shift + g ") == "Ctrl+Shift+G"
    assert normalize_linux_hotkey_shortcut("meta+alt+f12") == "Alt+Super+F12"
    assert normalize_linux_hotkey_shortcut("CTRL+Page Down") == "Ctrl+PageDown"
    assert normalize_linux_hotkey_shortcut("super+1") == "Super+1"

    for invalid in (
        "G",
        "Shift+G",
        "Ctrl+",
        "+G",
        "Ctrl+Ctrl+G",
        "Hyper+G",
        "Ctrl+Shift+Mouse1",
        "Ctrl+Shift+F25",
    ):
        try:
            normalize_linux_hotkey_shortcut(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid Linux shortcut accepted: {invalid}")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        program = root / "program"
        state = root / "state"
        program.mkdir()
        state.mkdir()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return program

            @staticmethod
            def state_dir() -> Path:
                return state

        assert load_linux_hotkey_preferences(Engine) == {"shortcut": ""}
        assert save_linux_hotkey_preferences(Engine, "alt+shift+k") == {"shortcut": "Alt+Shift+K"}
        assert load_linux_hotkey_preferences(Engine) == {"shortcut": "Alt+Shift+K"}
        assert linux_hotkey_preference_status(Engine, platform="linux") == {
            "globalHotkeyConfigurable": True,
            "globalHotkeyConfigured": True,
            "globalHotkeyPreference": "Alt+Shift+K",
        }
        assert linux_hotkey_preference_status(Engine, platform="win32") == {
            "globalHotkeyConfigurable": False,
            "globalHotkeyConfigured": False,
            "globalHotkeyPreference": "",
        }

        _preferences_path(Engine).write_text('{"shortcut":"Shift+G"}', encoding="utf-8")
        assert load_linux_hotkey_preferences(Engine) == {"shortcut": ""}
        _preferences_path(Engine).write_text("not-json", encoding="utf-8")
        assert load_linux_hotkey_preferences(Engine) == {"shortcut": ""}

        class Window:
            @staticmethod
            def bridge_status(_window=None):
                return {
                    "globalHotkeyAvailable": False,
                    "globalHotkeyActive": False,
                    "globalHotkey": "",
                }

        TestEngine = SimpleNamespace(
            EngineWindow=Window,
            app_dir=Engine.app_dir,
            state_dir=Engine.state_dir,
        )
        save_linux_hotkey_preferences(TestEngine, "ctrl+alt+h")
        install_linux_hotkey_preferences(TestEngine)
        # The host running this self-test may not be Linux. Exercise the pure
        # status helper above for platform semantics and the wrapper contract here.
        assert Window._galaxy_linux_hotkey_preferences_installed is True
