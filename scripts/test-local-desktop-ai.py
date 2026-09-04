from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_ai import install_desktop_ai, run_desktop_ai_self_test
from desktop_hooks import registered_after_build_ui_hooks


class FakeWindow:
    pass


class FakeEngine:
    EngineWindow = FakeWindow


def run_test() -> None:
    installed = install_desktop_ai(FakeEngine)
    assert installed is FakeWindow
    assert getattr(FakeWindow, "_galaxy_desktop_ai_installed", False) is True
    assert "desktop-ai" in registered_after_build_ui_hooks(FakeWindow)
    # Idempotent install must not duplicate the hook.
    install_desktop_ai(FakeEngine)
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-ai") == 1
    run_desktop_ai_self_test()


if __name__ == "__main__":
    run_test()
    print("Desktop AI self-test passed")
