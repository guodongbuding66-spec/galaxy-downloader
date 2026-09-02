from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from managed_tool_metadata import (  # noqa: E402
    MANAGED_TOOL_METADATA_FILENAME,
    MANAGED_TOOL_METADATA_SCHEMA,
    MAX_MANAGED_TOOL_METADATA_BYTES,
    ManagedToolMetadata,
    ManagedToolMetadataError,
    read_managed_tool_metadata,
    run_managed_tool_metadata_self_test,
    validate_managed_tool_metadata,
    write_managed_tool_metadata,
)


class ManagedToolMetadataTests(unittest.TestCase):
    def metadata(self, **overrides) -> ManagedToolMetadata:
        values = {
            "schemaVersion": MANAGED_TOOL_METADATA_SCHEMA,
            "tool": "ffmpeg",
            "source": "online",
            "platform": "windows",
            "arch": "x86-64",
            "binaryVersion": "ffmpeg version N-126313-g1ae4048218",
            "installedAt": "2026-09-02T11:00:00Z",
            "providerId": "btbn-ffmpeg-builds",
            "artifactVersion": "N-126313-g1ae4048218",
            "releaseTag": "autobuild-2026-09-01-13-13",
            "publishedAt": "2026-09-01T13:36:08Z",
            "sha256": "a" * 64,
            "assetName": "ffmpeg-N-126313-g1ae4048218-win64-gpl.zip",
            "releaseUrl": "https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-09-01-13-13",
            "provenanceUrl": "https://ffmpeg.org/download.html",
        }
        values.update(overrides)
        return ManagedToolMetadata(**values)

    def test_round_trip_preserves_release_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.metadata()
            path = write_managed_tool_metadata(root, metadata)
            self.assertEqual(path.name, MANAGED_TOOL_METADATA_FILENAME)
            loaded = read_managed_tool_metadata(root, expected_tool="ffmpeg")
            self.assertEqual(loaded, metadata)

    def test_missing_metadata_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(read_managed_tool_metadata(Path(directory), expected_tool="ffmpeg"))

    def test_online_metadata_requires_complete_release_identity(self) -> None:
        for field, value in (
            ("providerId", None),
            ("releaseTag", None),
            ("sha256", "bad"),
            ("assetName", "../ffmpeg.zip"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ManagedToolMetadataError):
                    validate_managed_tool_metadata(self.metadata(**{field: value}), expected_tool="ffmpeg")

    def test_writer_rejects_provider_supplied_metadata_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / MANAGED_TOOL_METADATA_FILENAME).write_text("{}", encoding="utf-8")
            with self.assertRaises(ManagedToolMetadataError):
                write_managed_tool_metadata(root, self.metadata())
            self.assertEqual((root / MANAGED_TOOL_METADATA_FILENAME).read_text(encoding="utf-8"), "{}")

    def test_reader_rejects_wrong_tool_corrupt_and_oversized_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_managed_tool_metadata(root, self.metadata())
            with self.assertRaises(ManagedToolMetadataError):
                read_managed_tool_metadata(root, expected_tool="yt-dlp")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / MANAGED_TOOL_METADATA_FILENAME).write_text("{not-json", encoding="utf-8")
            with self.assertRaises(ManagedToolMetadataError):
                read_managed_tool_metadata(root, expected_tool="ffmpeg")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / MANAGED_TOOL_METADATA_FILENAME).write_bytes(b"x" * (MAX_MANAGED_TOOL_METADATA_BYTES + 1))
            with self.assertRaises(ManagedToolMetadataError):
                read_managed_tool_metadata(root, expected_tool="ffmpeg")

    def test_reader_rejects_forged_schema_even_when_json_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = self.metadata().__dict__.copy()
            payload["schemaVersion"] = 999
            (root / MANAGED_TOOL_METADATA_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ManagedToolMetadataError):
                read_managed_tool_metadata(root, expected_tool="ffmpeg")

    def test_embedded_self_test(self) -> None:
        run_managed_tool_metadata_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
