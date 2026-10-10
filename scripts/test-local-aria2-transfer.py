from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from aria2_recovery import run_aria2_recovery_self_test  # noqa: E402
from aria2_source_policy import run_aria2_source_policy_self_test  # noqa: E402
from aria2_task_provider import run_aria2_task_provider_self_test  # noqa: E402
from aria2_transfer import run_aria2_transfer_self_test  # noqa: E402
from task_center import run_task_center_self_test  # noqa: E402
from transfer_center import run_transfer_center_self_test  # noqa: E402


class Aria2TransferTests(unittest.TestCase):
    def test_lifecycle_parser_retry_and_security_boundaries(self) -> None:
        run_aria2_transfer_self_test()

    def test_strict_magnet_and_torrent_source_policy(self) -> None:
        run_aria2_source_policy_self_test()

    def test_restart_recovery_uses_existing_resume_store(self) -> None:
        run_aria2_recovery_self_test()

    def test_task_provider_projection_and_actions(self) -> None:
        run_aria2_task_provider_self_test()

    def test_task_center_routes_provider_pause_resume(self) -> None:
        run_task_center_self_test()
        source = (LOCAL_ENGINE / "task_center.py").read_text(encoding="utf-8")
        for marker in (
            'provider_can_pause = bool(provider and "pause" in provider_actions)',
            'active_pause_button.configure(text="暂停任务" if provider_can_pause else "暂停当前")',
            'provider_can_resume = bool(provider and "resume" in provider_actions)',
            'if provider is not None and "pause" in tuple(provider.get("providerActions") or ()):',
            'run_provider_action("pause")',
            'if provider is not None and "resume" in tuple(provider.get("providerActions") or ()):',
            'run_provider_action("resume")',
            'rows[0].get("kind") == "provider" and "resume" in tuple(rows[0].get("providerActions") or ())',
        ):
            self.assertIn(marker, source)

    def test_transfer_facade_preserves_legacy_contract(self) -> None:
        run_transfer_center_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
