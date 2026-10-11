from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import transfer_center  # noqa: E402
from aria2_file_selection import run_aria2_file_selection_self_test, selected_files_for  # noqa: E402
from aria2_recovery import run_aria2_recovery_self_test  # noqa: E402
from aria2_source_policy import run_aria2_source_policy_self_test  # noqa: E402
from aria2_task_provider import run_aria2_task_provider_self_test  # noqa: E402
from aria2_transfer import build_aria2_command, run_aria2_transfer_self_test  # noqa: E402
from resume_bridge import run_resume_bridge_self_test  # noqa: E402
from task_center import run_task_center_self_test  # noqa: E402
from torrent_metadata import run_torrent_metadata_self_test  # noqa: E402
from transfer_center import run_transfer_center_self_test  # noqa: E402
from transfer_preferences import (  # noqa: E402
    run_transfer_preferences_self_test,
    save_aria2_connections_preference,
)


class Aria2TransferTests(unittest.TestCase):
    def test_lifecycle_parser_retry_and_security_boundaries(self) -> None:
        run_aria2_transfer_self_test()

    def test_strict_magnet_and_torrent_source_policy(self) -> None:
        run_aria2_source_policy_self_test()

    def test_selective_file_adapter_and_local_metadata_parser(self) -> None:
        run_aria2_file_selection_self_test()
        run_torrent_metadata_self_test()

    def test_transfer_preferences_preserve_existing_network_settings(self) -> None:
        run_transfer_preferences_self_test()

    def test_restart_recovery_uses_existing_resume_store(self) -> None:
        run_aria2_recovery_self_test()

    def test_task_provider_projection_actions_and_resume_dedupe(self) -> None:
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

    def test_torrent_session_uses_persisted_connection_setting(self) -> None:
        magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root / "downloads"
            downloads.mkdir()

            class FakeEngine:
                @staticmethod
                def app_dir() -> Path:
                    return root

                @staticmethod
                def state_dir() -> Path:
                    target = root / "state"
                    target.mkdir(parents=True, exist_ok=True)
                    return target

                @staticmethod
                def default_download_dir() -> Path:
                    return downloads

            self.assertEqual(save_aria2_connections_preference(FakeEngine, "6"), 6)
            with patch.object(transfer_center, "find_aria2c", return_value=Path("aria2c")):
                with patch.object(transfer_center, "_managed_download_dir", return_value=downloads / "torrents"):
                    session = transfer_center.start_torrent_transfer(FakeEngine, magnet)
            self.assertEqual(session.options.connections, 6)

    def test_torrent_session_preserves_selected_file_indexes(self) -> None:
        magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root / "downloads"
            downloads.mkdir()

            class FakeEngine:
                @staticmethod
                def app_dir() -> Path:
                    return root

                @staticmethod
                def state_dir() -> Path:
                    target = root / "state"
                    target.mkdir(parents=True, exist_ok=True)
                    return target

                @staticmethod
                def default_download_dir() -> Path:
                    return downloads

            with patch.object(transfer_center, "find_aria2c", return_value=Path("aria2c")):
                with patch.object(transfer_center, "_managed_download_dir", return_value=downloads / "torrents"):
                    session = transfer_center.start_torrent_transfer(FakeEngine, magnet, selected_files=(5, 2, 3, 3))
            self.assertEqual(selected_files_for(session.options), (2, 3, 5))
            command = build_aria2_command(Path("aria2c"), session.options)
            self.assertIn("--select-file=2-3,5", command)
            self.assertLess(command.index("--select-file=2-3,5"), command.index("--"))

    def test_invalid_source_wins_over_missing_aria2_error(self) -> None:
        class FakeEngine:
            pass

        with patch.object(transfer_center, "find_aria2c", return_value=None):
            with self.assertRaisesRegex(transfer_center.TransferError, "Magnet"):
                transfer_center.start_torrent_transfer(FakeEngine, "magnet:?xt=urn:btih:1234")
            with self.assertRaisesRegex(transfer_center.TransferError, "aria2c"):
                transfer_center.start_torrent_transfer(
                    FakeEngine,
                    "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
                )

    def test_bridge_v5_pause_resume_discard_contract_is_unchanged(self) -> None:
        run_resume_bridge_self_test()

    def test_transfer_facade_preserves_legacy_contract(self) -> None:
        run_transfer_center_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
