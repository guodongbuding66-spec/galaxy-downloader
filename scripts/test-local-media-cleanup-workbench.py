from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_hooks import registered_after_build_ui_hooks  # noqa: E402
from media_cleanup import CleanupRegion, MediaCleanupError, MediaProbe  # noqa: E402
from media_cleanup_workbench import (  # noqa: E402
    CleanupPreviewPlan,
    build_preview_command,
    build_preview_plan,
    cancel_active_media_cleanup,
    canvas_rect_to_region,
    fit_preview_size,
    install_media_cleanup_workbench,
    media_cleanup_active,
    run_media_cleanup_workbench_self_test,
)


class MediaCleanupWorkbenchTests(unittest.TestCase):
    def test_preview_size_never_upscales_and_respects_bounds(self) -> None:
        self.assertEqual(fit_preview_size(640, 480), (640, 480))
        width, height = fit_preview_size(3840, 2160)
        self.assertLessEqual(width, 900)
        self.assertLessEqual(height, 520)
        self.assertAlmostEqual(width / height, 3840 / 2160, delta=0.02)
        with self.assertRaises(MediaCleanupError):
            fit_preview_size(1, 1080)

    def test_preview_plan_uses_safe_video_seek(self) -> None:
        video = build_preview_plan(MediaProbe(1920, 1080, 30.0, "video"))
        self.assertEqual(video.seek_seconds, 1.0)
        short = build_preview_plan(MediaProbe(1920, 1080, 0.5, "video"))
        self.assertEqual(short.seek_seconds, 0.25)
        image = build_preview_plan(MediaProbe(1024, 768, 0.0, "image"))
        self.assertEqual(image.seek_seconds, 0.0)

    def test_canvas_rect_maps_back_to_source_pixels(self) -> None:
        plan = CleanupPreviewPlan("video", 1920, 1080, 900, 506, 1.0)
        self.assertEqual(
            canvas_rect_to_region(0, 0, 900, 506, plan),
            CleanupRegion(0, 0, 1920, 1080),
        )
        corner = canvas_rect_to_region(810, 455, 900, 506, plan)
        self.assertGreaterEqual(corner.x, 1728)
        self.assertGreaterEqual(corner.y, 971)
        self.assertLessEqual(corner.x + corner.width, 1920)
        self.assertLessEqual(corner.y + corner.height, 1080)
        with self.assertRaises(MediaCleanupError):
            canvas_rect_to_region(10, 10, 10.2, 10.2, plan)

    def test_preview_command_uses_png_frame_and_seek_only_for_video(self) -> None:
        video = CleanupPreviewPlan("video", 1920, 1080, 900, 506, 1.0)
        video_command = build_preview_command(
            Path("ffmpeg.exe"), Path("input.mp4"), Path("preview.png"), video
        )
        self.assertIn("-ss", video_command)
        self.assertIn("scale=900:506", video_command)
        self.assertIn("-frames:v", video_command)
        self.assertEqual(video_command[-1], "preview.png")

        image = CleanupPreviewPlan("image", 640, 480, 640, 480, 0.0)
        image_command = build_preview_command(
            Path("ffmpeg.exe"), Path("input.png"), Path("preview.png"), image
        )
        self.assertNotIn("-ss", image_command)

    def test_cancel_uses_event_capability_not_concrete_type(self) -> None:
        class EventLike:
            def __init__(self) -> None:
                self.called = False

            def set(self) -> None:
                self.called = True

        class Window:
            _galaxy_media_cleanup_running = True

        window = Window()
        event = EventLike()
        window._galaxy_media_cleanup_cancel_event = event
        self.assertTrue(media_cleanup_active(window))
        self.assertTrue(cancel_active_media_cleanup(window))
        self.assertTrue(event.called)
        window._galaxy_media_cleanup_cancel_event = object()
        self.assertFalse(cancel_active_media_cleanup(window))

    def test_install_registers_canonical_after_build_hook(self) -> None:
        class FakeWindow:
            pass

        class FakeEngine:
            EngineWindow = FakeWindow

        install_media_cleanup_workbench(FakeEngine)
        self.assertIn("media-cleanup-workbench", registered_after_build_ui_hooks(FakeWindow))
        self.assertTrue(FakeWindow._galaxy_media_cleanup_workbench_installed)

    def test_embedded_self_test(self) -> None:
        run_media_cleanup_workbench_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
