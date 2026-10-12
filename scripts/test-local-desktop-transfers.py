from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_hooks import registered_after_build_ui_hooks
from desktop_transfers import install_desktop_transfers, run_desktop_transfers_self_test


class FakeWindow:
    def resume_job(self, _job_id=None) -> bool:
        return False

    def discard_resume_job(self, _job_id: str) -> bool:
        return False

    def close_app(self) -> None:
        return None


class FakeEngine:
    EngineWindow = FakeWindow
    _test_root = ROOT

    @staticmethod
    def app_dir() -> Path:
        return Path(FakeEngine._test_root)

    @staticmethod
    def default_download_dir() -> Path:
        target = Path(FakeEngine._test_root) / "downloads"
        target.mkdir(parents=True, exist_ok=True)
        return target


def run_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        FakeEngine._test_root = Path(directory)
        install_desktop_transfers(FakeEngine)
        assert getattr(FakeWindow, "_galaxy_desktop_transfers_installed", False)
        assert registered_after_build_ui_hooks(FakeWindow).count("desktop-transfers") == 1
        assert getattr(FakeEngine, "_galaxy_aria2_task_provider_installed", False)
        assert getattr(FakeEngine, "_galaxy_aria2_recovery_installed", False)
        install_desktop_transfers(FakeEngine)
        assert registered_after_build_ui_hooks(FakeWindow).count("desktop-transfers") == 1
        run_desktop_transfers_self_test()


if __name__ == "__main__":
    run_test()
    print("Desktop Transfers self-test passed")
