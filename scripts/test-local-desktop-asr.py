from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_asr import install_desktop_asr, run_desktop_asr_self_test
from desktop_hooks import registered_after_build_ui_hooks


class FakeWindow:
    pass


class FakeEngine:
    EngineWindow = FakeWindow


def run_test() -> None:
    install_desktop_asr(FakeEngine)
    assert getattr(FakeWindow, "_galaxy_desktop_asr_installed", False) is True
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-asr") == 1
    install_desktop_asr(FakeEngine)
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-asr") == 1
    run_desktop_asr_self_test()


if __name__ == "__main__":
    run_test()
    print("Desktop ASR self-test passed")
