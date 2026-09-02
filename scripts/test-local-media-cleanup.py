from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from media_cleanup import (  # noqa: E402
    MAX_CLEANUP_REGIONS,
    CleanupRegion,
    MediaCleanupCancelled,
    MediaCleanupError,
    MediaProbe,
    _default_output_path,
    _manifest_path,
    _normalize_regions,
    _parse_progress_seconds,
    _validate_output,
    _validate_regions_within_frame,
    _write_manifest,
    build_cleanup_command,
    build_delogo_filter,
    run_media_cleanup_self_test,
)


class MediaCleanupPolicyTests(unittest.TestCase):
    def test_region_validation_and_limit(self) -> None:
        self.assertEqual(CleanupRegion(0, 0, 2, 2).validate().width, 2)
        with self.assertRaises(MediaCleanupError):
            CleanupRegion(-1, 0, 10, 10).validate()
        with self.assertRaises(MediaCleanupError):
            CleanupRegion(0, 0, 1, 10).validate()
        with self.assertRaises(MediaCleanupError):
            _normalize_regions(CleanupRegion(i, 0, 2, 2) for i in range(MAX_CLEANUP_REGIONS + 1))

    def test_regions_must_fit_frame(self) -> None:
        probe = MediaProbe(width=1920, height=1080, duration_seconds=5.0, media_kind="video")
        _validate_regions_within_frame((CleanupRegion(1800, 1000, 120, 80),), probe)
        with self.assertRaises(MediaCleanupError):
            _validate_regions_within_frame((CleanupRegion(1801, 1000, 120, 80),), probe)

    def test_default_output_is_collision_free_and_explicit_output_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "photo.png"
            source.write_bytes(b"source")
            first = _default_output_path(source, "image")
            self.assertEqual(first.name, "photo.cleaned.png")
            first.write_bytes(b"old-result")
            second = _default_output_path(source, "image")
            self.assertEqual(second.name, "photo.cleaned-2.png")
            _manifest_path(second).write_text("{}", encoding="utf-8")
            third = _default_output_path(source, "image")
            self.assertEqual(third.name, "photo.cleaned-3.png")
            with self.assertRaises(MediaCleanupError):
                _validate_output(source, first, "image")
            with self.assertRaises(MediaCleanupError):
                _validate_output(source, source, "image")

    def test_ffmpeg_command_never_overwrites_and_preserves_audio(self) -> None:
        regions = (CleanupRegion(10, 20, 100, 40),)
        command = build_cleanup_command(
            Path("ffmpeg"),
            Path("input.mp4"),
            Path("output.mp4"),
            regions,
            "video",
        )
        self.assertIn("-n", command)
        self.assertNotIn("-y", command)
        self.assertEqual(command[command.index("-loglevel") + 1], "error")
        self.assertIn("0:a?", command)
        self.assertIn("-progress", command)
        self.assertEqual(command[-1], "output.mp4")
        self.assertEqual(build_delogo_filter(regions), "delogo=x=10:y=20:w=100:h=40:show=0")

    def test_progress_parser_is_bounded_input_only(self) -> None:
        self.assertEqual(_parse_progress_seconds("out_time_us=2500000"), 2.5)
        self.assertEqual(_parse_progress_seconds("out_time_ms=1000000"), 1.0)
        self.assertIsNone(_parse_progress_seconds("progress=continue"))
        self.assertIsNone(_parse_progress_seconds("out_time_us=oops"))

    def test_manifest_records_edit_without_source_path_or_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "private" / "input.png"
            source.parent.mkdir()
            source.write_bytes(b"source")
            output = root / "output.png"
            output.write_bytes(b"output")
            manifest = _write_manifest(
                source,
                output,
                (CleanupRegion(1, 2, 10, 12),),
                "image",
                "a" * 64,
                "b" * 64,
            )
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["operation"], "visible-overlay-cleanup")
            self.assertEqual(payload["method"], "ffmpeg-delogo")
            self.assertEqual(payload["sourceFile"], "input.png")
            self.assertNotIn(str(source.parent), manifest.read_text(encoding="utf-8"))
            self.assertIn("does not target invisible provenance", payload["note"])

    def test_embedded_self_test(self) -> None:
        run_media_cleanup_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
