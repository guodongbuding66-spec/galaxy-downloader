from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from media_cleanup import MediaCleanupError, MediaProbe  # noqa: E402
from media_cleanup_suggestions import (  # noqa: E402
    AnalysisPlan,
    MIN_CONFIDENCE,
    _fit_analysis_size,
    _synthetic_frame,
    build_analysis_command,
    build_analysis_plan,
    parse_ppm,
    run_media_cleanup_suggestion_self_test,
    suggest_from_rgb,
)


class MediaCleanupSuggestionTests(unittest.TestCase):
    def test_analysis_size_is_bounded_without_upscale(self) -> None:
        self.assertEqual(_fit_analysis_size(320, 180), (320, 180))
        width, height = _fit_analysis_size(3840, 2160)
        self.assertLessEqual(width, 480)
        self.assertLessEqual(height, 320)
        self.assertAlmostEqual(width / height, 3840 / 2160, delta=0.02)
        with self.assertRaises(MediaCleanupError):
            _fit_analysis_size(1, 1080)

    def test_video_analysis_uses_bounded_seek(self) -> None:
        long_video = build_analysis_plan(MediaProbe(1920, 1080, 60.0, "video"))
        self.assertEqual(long_video.seek_seconds, 1.0)
        short_video = build_analysis_plan(MediaProbe(1920, 1080, 0.4, "video"))
        self.assertEqual(short_video.seek_seconds, 0.2)
        image = build_analysis_plan(MediaProbe(1200, 800, 0.0, "image"))
        self.assertEqual(image.seek_seconds, 0.0)

    def test_binary_ppm_parser_supports_comments_and_rejects_truncation(self) -> None:
        payload = b"P6\n# generated\n2 2\n255\n" + bytes(range(12))
        width, height, pixels = parse_ppm(payload)
        self.assertEqual((width, height), (2, 2))
        self.assertEqual(pixels, bytes(range(12)))
        with self.assertRaises(MediaCleanupError):
            parse_ppm(payload[:-1])
        with self.assertRaises(MediaCleanupError):
            parse_ppm(b"P3\n2 2\n255\n0 0 0")

    def test_synthetic_bottom_right_overlay_is_suggested_without_auto_action(self) -> None:
        plan = AnalysisPlan("image", 1280, 720, 320, 180, 0.0)
        suggestions = suggest_from_rgb(
            _synthetic_frame(plan.analysis_width, plan.analysis_height),
            plan.analysis_width,
            plan.analysis_height,
            plan,
        )
        self.assertTrue(suggestions)
        best = suggestions[0]
        self.assertIn(best.position, {"右下角", "底部中间"})
        self.assertGreaterEqual(best.confidence, MIN_CONFIDENCE)
        self.assertGreaterEqual(best.region.x, 1280 // 2)
        self.assertGreaterEqual(best.region.y, 720 // 2)
        self.assertLessEqual(best.region.x + best.region.width, 1280)
        self.assertLessEqual(best.region.y + best.region.height, 720)

    def test_uniform_frame_returns_no_suggestions(self) -> None:
        plan = AnalysisPlan("image", 1280, 720, 320, 180, 0.0)
        pixels = bytes([110, 110, 110] * (plan.analysis_width * plan.analysis_height))
        self.assertEqual(
            suggest_from_rgb(pixels, plan.analysis_width, plan.analysis_height, plan),
            (),
        )

    def test_analysis_command_outputs_ppm_and_never_downloads_or_modifies_source(self) -> None:
        plan = AnalysisPlan("video", 1920, 1080, 480, 270, 1.0)
        command = build_analysis_command(
            Path("ffmpeg.exe"), Path("input.mp4"), Path("analysis.ppm"), plan
        )
        self.assertIn("-ss", command)
        self.assertIn("scale=480:270", command)
        self.assertEqual(command[command.index("-vcodec") + 1], "ppm")
        self.assertEqual(command[-1], "analysis.ppm")

    def test_bad_frame_shape_and_suggestion_limit_fail_closed(self) -> None:
        plan = AnalysisPlan("image", 1280, 720, 320, 180, 0.0)
        pixels = _synthetic_frame(320, 180)
        with self.assertRaises(MediaCleanupError):
            suggest_from_rgb(pixels, 319, 180, plan)
        with self.assertRaises(MediaCleanupError):
            suggest_from_rgb(pixels, 320, 180, plan, max_suggestions=0)

    def test_embedded_self_test(self) -> None:
        run_media_cleanup_suggestion_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
