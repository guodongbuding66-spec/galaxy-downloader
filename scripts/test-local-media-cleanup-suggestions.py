from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from media_cleanup import MediaCleanupError, MediaProbe  # noqa: E402
from media_cleanup_suggestions import (  # noqa: E402
    GrayFrame,
    build_gray_frame_command,
    extract_gray_frame,
    normalize_suggestion_profile,
    run_media_cleanup_suggestions_self_test,
    suggest_visible_overlay_for_media,
    suggest_visible_overlay_regions,
)


class MediaCleanupSuggestionTests(unittest.TestCase):
    def test_profile_aliases_are_normalized(self) -> None:
        self.assertEqual(normalize_suggestion_profile("豆包"), "bottom-right-compact")
        self.assertEqual(normalize_suggestion_profile("Gemini"), "bottom-right-wide")
        self.assertEqual(normalize_suggestion_profile("unknown"), "auto")

    def test_invalid_gray_buffer_fails_closed(self) -> None:
        with self.assertRaises(MediaCleanupError):
            GrayFrame(320, 180, b"short").validate()

    def test_clean_auto_frame_has_no_suggestion(self) -> None:
        frame = GrayFrame(320, 180, bytes([40] * (320 * 180)))
        self.assertEqual(suggest_visible_overlay_regions(frame), ())

    def test_provider_hint_can_return_low_confidence_review_region(self) -> None:
        frame = GrayFrame(320, 180, bytes([40] * (320 * 180)))
        suggestion = suggest_visible_overlay_regions(frame, provider_hint="doubao")[0]
        self.assertEqual(suggestion.source, "profile")
        self.assertEqual(suggestion.profile, "bottom-right-compact")
        self.assertLess(suggestion.confidence, 0.5)
        self.assertGreaterEqual(suggestion.region.x, 160)
        self.assertGreaterEqual(suggestion.region.y, 90)

    def test_bottom_right_edge_pattern_is_detected(self) -> None:
        width, height = 320, 180
        pixels = bytearray([25] * (width * height))
        for y in range(138, 166):
            for x in range(228, 306):
                pixels[y * width + x] = 245 if (x + y) % 6 < 3 else 25
        suggestions = suggest_visible_overlay_regions(GrayFrame(width, height, bytes(pixels)))
        self.assertEqual(len(suggestions), 1)
        suggestion = suggestions[0]
        self.assertEqual(suggestion.source, "edge-analysis")
        self.assertGreaterEqual(suggestion.confidence, 0.3)
        self.assertGreaterEqual(suggestion.region.x, width // 2)
        self.assertGreaterEqual(suggestion.region.y, height // 2)
        self.assertLessEqual(suggestion.region.x + suggestion.region.width, width)
        self.assertLessEqual(suggestion.region.y + suggestion.region.height, height)

    def test_ffmpeg_gray_frame_command_uses_safe_single_frame_pipe(self) -> None:
        probe = MediaProbe(width=1920, height=1080, duration_seconds=12.0, media_kind="video")
        command = build_gray_frame_command(Path("ffmpeg.exe"), Path("input.mp4"), probe)
        self.assertIn("-ss", command)
        self.assertIn("format=gray", command)
        self.assertIn("rawvideo", command)
        self.assertEqual(command[-1], "pipe:1")
        self.assertNotIn("-y", command)

    def test_extract_gray_frame_requires_exact_pixel_buffer(self) -> None:
        probe = MediaProbe(width=16, height=8, duration_seconds=0.0, media_kind="image")
        good = subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=0,
            stdout=bytes(range(128)),
            stderr=b"",
        )
        with patch("media_cleanup_suggestions.subprocess.run", return_value=good):
            frame = extract_gray_frame(Path("ffmpeg"), Path("input.png"), probe)
        self.assertEqual(frame.width, 16)
        self.assertEqual(frame.height, 8)
        self.assertEqual(len(frame.pixels), 128)

        short = subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=0,
            stdout=b"short",
            stderr=b"",
        )
        with patch("media_cleanup_suggestions.subprocess.run", return_value=short):
            with self.assertRaises(MediaCleanupError):
                extract_gray_frame(Path("ffmpeg"), Path("input.png"), probe)

    def test_media_suggestion_pipeline_uses_rendered_frame_and_provider_hint(self) -> None:
        width, height = 320, 180
        probe = MediaProbe(width=width, height=height, duration_seconds=0.0, media_kind="image")
        frame = GrayFrame(width, height, bytes([30] * (width * height)))
        with patch("media_cleanup_suggestions.extract_gray_frame", return_value=frame) as render:
            suggestions = suggest_visible_overlay_for_media(
                Path("ffmpeg"),
                Path("input.png"),
                probe,
                provider_hint="Gemini",
            )
        render.assert_called_once()
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].profile, "bottom-right-wide")
        self.assertEqual(suggestions[0].source, "profile")

    def test_embedded_self_test(self) -> None:
        run_media_cleanup_suggestions_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
