from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from managed_tool_actions import (  # noqa: E402
    ManagedToolActionAdapters,
    ManagedToolActionRequest,
    managed_tool_action_policy,
    perform_managed_tool_action,
    public_managed_tool_action_result,
    run_managed_tool_actions_self_test,
    supported_managed_tool_actions,
)


class ManagedToolActionTests(unittest.TestCase):
    def test_supported_action_matrix_is_explicit(self) -> None:
        self.assertEqual(
            supported_managed_tool_actions("ffmpeg"),
            ("check", "install", "update", "seed", "reset"),
        )
        self.assertEqual(supported_managed_tool_actions("yt-dlp"), ("seed", "update", "reset"))
        self.assertEqual(supported_managed_tool_actions("unknown"), ())
        self.assertTrue(managed_tool_action_policy("ffmpeg", "check")["network"])
        self.assertFalse(managed_tool_action_policy("ffmpeg", "seed")["network"])
        self.assertTrue(managed_tool_action_policy("ffmpeg", "seed")["mutating"])

    def test_user_initiation_is_required_before_adapter_invocation(self) -> None:
        called = []

        def forbidden(*_args, **_kwargs):
            called.append(True)
            raise AssertionError("adapter must not run")

        adapters = ManagedToolActionAdapters(
            ffmpeg_check=forbidden,
            ffmpeg_install=forbidden,
            ffmpeg_seed=forbidden,
            ffmpeg_reset=forbidden,
            ytdlp_seed=forbidden,
            ytdlp_update=forbidden,
            ytdlp_reset=forbidden,
        )
        result = perform_managed_tool_action(
            object(),
            ManagedToolActionRequest("ffmpeg", "update", False),
            adapters=adapters,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.state, "user-initiation-required")
        self.assertFalse(result.network_action)
        self.assertEqual(called, [])

    def test_unsupported_tool_or_action_fails_without_adapter(self) -> None:
        unsupported_tool = perform_managed_tool_action(
            object(), ManagedToolActionRequest("whisper", "install", True)
        )
        self.assertEqual(unsupported_tool.state, "unsupported-tool")
        unsupported_action = perform_managed_tool_action(
            object(), ManagedToolActionRequest("yt-dlp", "check", True)
        )
        self.assertEqual(unsupported_action.state, "unsupported-action")

    def test_ffmpeg_check_normalizes_update_status(self) -> None:
        native = SimpleNamespace(
            ok=True,
            state="update_available",
            current_source="managed",
            current_version="ffmpeg version old",
            available_version="N-200000-gabc",
            available_release_tag="autobuild-2026-09-02-20-00",
            update_available=True,
            message="update available",
        )
        adapters = ManagedToolActionAdapters(ffmpeg_check=lambda _engine: native)
        result = perform_managed_tool_action(
            object(), ManagedToolActionRequest("ffmpeg", "check", True), adapters=adapters
        )
        self.assertTrue(result.ok)
        self.assertFalse(result.changed)
        self.assertEqual(result.state, "update_available")
        self.assertEqual(result.source, "managed")
        self.assertEqual(result.available_version, "N-200000-gabc")
        self.assertTrue(result.update_available)
        self.assertTrue(result.network_action)

    def test_ffmpeg_install_and_update_share_verified_online_adapter(self) -> None:
        calls = []

        def install(_engine):
            calls.append("install")
            return SimpleNamespace(
                ok=True,
                changed=True,
                version="ffmpeg version new",
                source="managed",
                message="installed",
            )

        adapters = ManagedToolActionAdapters(ffmpeg_install=install)
        for action in ("install", "update"):
            with self.subTest(action=action):
                result = perform_managed_tool_action(
                    object(), ManagedToolActionRequest("ffmpeg", action, True), adapters=adapters
                )
                self.assertTrue(result.ok)
                self.assertTrue(result.changed)
                self.assertEqual(result.state, "completed")
                self.assertTrue(result.network_action)
        self.assertEqual(calls, ["install", "install"])

    def test_ytdlp_update_forwards_only_valid_channel_field(self) -> None:
        channels = []

        def update(_engine, *, channel):
            channels.append(channel)
            return SimpleNamespace(
                ok=True,
                changed=False,
                version="2026.09.02",
                source="managed",
                message="up to date",
            )

        adapters = ManagedToolActionAdapters(ytdlp_update=update)
        result = perform_managed_tool_action(
            object(),
            ManagedToolActionRequest("yt-dlp", "update", True, channel="nightly"),
            adapters=adapters,
        )
        self.assertTrue(result.ok)
        self.assertTrue(result.network_action)
        self.assertEqual(channels, ["nightly"])

        invalid = perform_managed_tool_action(
            object(),
            ManagedToolActionRequest("ffmpeg", "seed", True, channel="nightly"),
            adapters=adapters,
        )
        self.assertFalse(invalid.ok)
        self.assertEqual(invalid.state, "invalid-request")

    def test_seed_and_reset_are_mutating_but_offline_contract_actions(self) -> None:
        native = SimpleNamespace(
            ok=True,
            changed=True,
            version="v1",
            source="managed",
            message="done",
        )
        adapters = ManagedToolActionAdapters(
            ffmpeg_seed=lambda _engine: native,
            ffmpeg_reset=lambda _engine: native,
            ytdlp_seed=lambda _engine: native,
            ytdlp_reset=lambda _engine: native,
        )
        for tool in ("ffmpeg", "yt-dlp"):
            for action in ("seed", "reset"):
                with self.subTest(tool=tool, action=action):
                    result = perform_managed_tool_action(
                        object(), ManagedToolActionRequest(tool, action, True), adapters=adapters
                    )
                    self.assertTrue(result.ok)
                    self.assertFalse(result.network_action)
                    self.assertTrue(managed_tool_action_policy(tool, action)["mutating"])

    def test_adapter_exception_is_normalized_and_does_not_escape(self) -> None:
        def fail(_engine):
            raise RuntimeError("provider failed")

        result = perform_managed_tool_action(
            object(),
            ManagedToolActionRequest("ffmpeg", "check", True),
            adapters=ManagedToolActionAdapters(ffmpeg_check=fail),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.state, "error")
        self.assertTrue(result.network_action)
        self.assertIn("provider failed", result.message)

    def test_public_result_is_bridge_safe_and_json_serializable(self) -> None:
        native = SimpleNamespace(
            ok=True,
            changed=True,
            version="v1",
            source="managed",
            message="done",
        )
        result = perform_managed_tool_action(
            object(),
            ManagedToolActionRequest("ffmpeg", "seed", True),
            adapters=ManagedToolActionAdapters(ffmpeg_seed=lambda _engine: native),
        )
        payload = public_managed_tool_action_result(result)
        json.dumps(payload)
        self.assertNotIn("path", " ".join(payload.keys()).lower())
        self.assertEqual(payload["networkAction"], False)

    def test_embedded_self_test(self) -> None:
        run_managed_tool_actions_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
