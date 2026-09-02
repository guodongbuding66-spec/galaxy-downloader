from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from managed_tool_metadata import (  # noqa: E402
    MANAGED_TOOL_METADATA_SCHEMA,
    ManagedToolMetadata,
    write_managed_tool_metadata,
)
from managed_tool_registry import (  # noqa: E402
    DEFAULT_MANAGED_TOOL_SPECS,
    ManagedToolObservation,
    evaluate_tool_health,
    public_tool_health,
    registry_summary,
    run_managed_tool_registry_self_test,
)


class ManagedToolRegistryTests(unittest.TestCase):
    @property
    def ffmpeg_spec(self):
        return next(item for item in DEFAULT_MANAGED_TOOL_SPECS if item.tool == "ffmpeg")

    @property
    def ytdlp_spec(self):
        return next(item for item in DEFAULT_MANAGED_TOOL_SPECS if item.tool == "yt-dlp")

    def metadata(self, *, platform_name: str = "windows", arch: str = "x86-64", binary_version: str = "ffmpeg version test"):
        return ManagedToolMetadata(
            schemaVersion=MANAGED_TOOL_METADATA_SCHEMA,
            tool="ffmpeg",
            source="online",
            platform=platform_name,
            arch=arch,
            binaryVersion=binary_version,
            installedAt="2026-09-02T00:00:00Z",
            providerId="btbn-ffmpeg-builds",
            artifactVersion="N-126313-g1ae4048218",
            releaseTag="autobuild-2026-09-01-13-13",
            publishedAt="2026-09-01T13:36:08Z",
            sha256="a" * 64,
            assetName="ffmpeg-N-126313-g1ae4048218-win64-gpl.zip",
            releaseUrl="https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-09-01-13-13",
            provenanceUrl="https://ffmpeg.org/download.html",
        )

    def test_required_missing_dependency_is_error(self) -> None:
        status = evaluate_tool_health(
            self.ffmpeg_spec,
            ManagedToolObservation(False, "unavailable", None),
        )
        self.assertEqual(status.state, "missing")
        self.assertEqual(status.health, "error")
        self.assertFalse(registry_summary((status,))["dependenciesReady"])

    def test_bundled_dependency_is_healthy_without_metadata(self) -> None:
        status = evaluate_tool_health(
            self.ffmpeg_spec,
            ManagedToolObservation(True, "bundled", "ffmpeg version bundled"),
        )
        self.assertEqual(status.state, "bundled")
        self.assertEqual(status.health, "ok")
        self.assertEqual(status.metadata_state, "not-managed")

    def test_managed_tool_without_required_provenance_is_not_a_false_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = evaluate_tool_health(
                self.ytdlp_spec,
                ManagedToolObservation(True, "managed", "2026.08.19", root),
            )
        self.assertEqual(status.state, "managed")
        self.assertEqual(status.health, "ok")
        self.assertEqual(status.metadata_state, "not-required")
        self.assertFalse(status.tracks_provenance)

    def test_managed_provenance_tool_without_metadata_is_usable_but_warned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = evaluate_tool_health(
                self.ffmpeg_spec,
                ManagedToolObservation(True, "managed", "ffmpeg version legacy", root),
            )
        self.assertEqual(status.state, "managed-untracked")
        self.assertEqual(status.health, "warning")
        self.assertTrue(status.ready)
        self.assertTrue(status.tracks_provenance)

    def test_valid_online_metadata_becomes_healthy_structured_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("managed_tool_registry.runtime_platform", return_value="windows"), patch(
                "managed_tool_registry.runtime_arch", return_value="x86-64"
            ):
                write_managed_tool_metadata(root, self.metadata())
                status = evaluate_tool_health(
                    self.ffmpeg_spec,
                    ManagedToolObservation(True, "managed", "ffmpeg version test", root),
                )
        self.assertEqual(status.state, "managed-online")
        self.assertEqual(status.health, "ok")
        self.assertEqual(status.provider_id, "btbn-ffmpeg-builds")
        self.assertEqual(status.release_tag, "autobuild-2026-09-01-13-13")
        payload = public_tool_health(status)
        self.assertTrue(payload["tracksProvenance"])
        self.assertNotIn("managed_root", payload)
        self.assertNotIn("path", " ".join(payload.keys()).lower())
        json.dumps(payload)

    def test_binary_drift_and_platform_mismatch_are_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("managed_tool_registry.runtime_platform", return_value="windows"), patch(
                "managed_tool_registry.runtime_arch", return_value="x86-64"
            ):
                write_managed_tool_metadata(root, self.metadata(binary_version="ffmpeg version recorded"))
                drift = evaluate_tool_health(
                    self.ffmpeg_spec,
                    ManagedToolObservation(True, "managed", "ffmpeg version changed", root),
                )
            self.assertEqual(drift.state, "binary-drift")
            self.assertEqual(drift.health, "warning")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("managed_tool_registry.runtime_platform", return_value="linux"), patch(
                "managed_tool_registry.runtime_arch", return_value="arm64"
            ):
                write_managed_tool_metadata(root, self.metadata())
                mismatch = evaluate_tool_health(
                    self.ffmpeg_spec,
                    ManagedToolObservation(True, "managed", "ffmpeg version test", root),
                )
            self.assertEqual(mismatch.state, "platform-mismatch")
            self.assertEqual(mismatch.health, "warning")

    def test_invalid_metadata_is_fail_visible_but_does_not_mark_binary_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".galaxy-tool.json").write_text("{not json", encoding="utf-8")
            status = evaluate_tool_health(
                self.ffmpeg_spec,
                ManagedToolObservation(True, "managed", "ffmpeg version test", root),
            )
        self.assertTrue(status.ready)
        self.assertEqual(status.state, "metadata-invalid")
        self.assertEqual(status.health, "warning")
        self.assertTrue(registry_summary((status,))["dependenciesReady"])

    def test_embedded_self_test(self) -> None:
        run_managed_tool_registry_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
