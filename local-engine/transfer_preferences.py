from __future__ import annotations

"""Shared persisted preferences for Galaxy network transfer engines.

The storage file intentionally remains ``bandwidth-options.json`` for backward
compatibility with existing Galaxy installs. New transfer-engine preferences
are added as independent keys so upgrading does not discard the user's current
bandwidth limit.
"""

import json
import threading
from pathlib import Path
from typing import Any

from runtime_storage import state_dir as runtime_state_dir

PREFERENCES_FILENAME = "bandwidth-options.json"
DEFAULT_ARIA2_CONNECTIONS = 16
MIN_ARIA2_CONNECTIONS = 1
MAX_ARIA2_CONNECTIONS = 16
_PREFERENCES_LOCK = threading.RLock()


def normalize_aria2_connections(value: object, *, default: int = DEFAULT_ARIA2_CONNECTIONS) -> int:
    try:
        fallback = max(MIN_ARIA2_CONNECTIONS, min(int(default), MAX_ARIA2_CONNECTIONS))
    except (TypeError, ValueError):
        fallback = DEFAULT_ARIA2_CONNECTIONS
    if value in (None, ""):
        return fallback
    try:
        connections = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return max(MIN_ARIA2_CONNECTIONS, min(connections, MAX_ARIA2_CONNECTIONS))


def _preferences_path(engine_module) -> Path:
    target = runtime_state_dir(engine_module)
    target.mkdir(parents=True, exist_ok=True)
    return target / PREFERENCES_FILENAME


def load_transfer_preferences(engine_module) -> dict[str, Any]:
    with _PREFERENCES_LOCK:
        try:
            payload = json.loads(_preferences_path(engine_module).read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}


def update_transfer_preferences(engine_module, **updates: object) -> dict[str, Any]:
    with _PREFERENCES_LOCK:
        payload = load_transfer_preferences(engine_module)
        payload.update(updates)
        path = _preferences_path(engine_module)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return dict(payload)


def load_aria2_connections_preference(engine_module) -> int:
    payload = load_transfer_preferences(engine_module)
    return normalize_aria2_connections(payload.get("aria2Connections"))


def save_aria2_connections_preference(engine_module, value: object) -> int:
    connections = normalize_aria2_connections(value)
    update_transfer_preferences(engine_module, aria2Connections=connections)
    return connections


def run_transfer_preferences_self_test() -> None:
    import tempfile

    assert normalize_aria2_connections(None) == 16
    assert normalize_aria2_connections(1) == 1
    assert normalize_aria2_connections("8") == 8
    assert normalize_aria2_connections(0) == 1
    assert normalize_aria2_connections(99) == 16
    assert normalize_aria2_connections("bad") == 16

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                target = root / "state"
                target.mkdir(parents=True, exist_ok=True)
                return target

        path = _preferences_path(Engine)
        path.write_text('{"bandwidthLimitKbps": 2048, "futureKey": true}', encoding="utf-8")
        assert load_aria2_connections_preference(Engine) == 16
        assert save_aria2_connections_preference(Engine, "6") == 6
        payload = load_transfer_preferences(Engine)
        assert payload["bandwidthLimitKbps"] == 2048
        assert payload["aria2Connections"] == 6
        assert payload["futureKey"] is True


if __name__ == "__main__":
    run_transfer_preferences_self_test()
    print("transfer_preferences self-test: OK")
