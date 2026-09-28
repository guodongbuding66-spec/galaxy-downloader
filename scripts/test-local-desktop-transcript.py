from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_hooks import registered_after_build_ui_hooks, registered_desktop_presenter
from desktop_transcript import install_desktop_transcript, run_desktop_transcript_self_test


class FakeWindow:
    pass


class FakeEngine:
    EngineWindow = FakeWindow


def run_test() -> None:
    installed = install_desktop_transcript(FakeEngine)
    assert installed is FakeWindow
    assert getattr(FakeWindow, "_galaxy_desktop_transcript_installed", False) is True
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-transcript") == 1
    assert registered_desktop_presenter(FakeWindow, "transcript") == "desktop-transcript"
    install_desktop_transcript(FakeEngine)
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-transcript") == 1
    run_desktop_transcript_self_test()


if __name__ == "__main__":
    run_test()
    print("Desktop Transcript self-test passed")
