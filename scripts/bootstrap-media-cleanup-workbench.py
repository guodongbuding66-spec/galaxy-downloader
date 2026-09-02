from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = ROOT / "local-engine" / "media_cleanup_workbench.py"
ENTRYPOINT = ROOT / "local-engine" / "entrypoint.py"
TEST = ROOT / "scripts" / "test-local-media-cleanup-workbench.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


workbench = WORKBENCH.read_text(encoding="utf-8")
workbench = replace_once(
    workbench,
    '''def cancel_active_media_cleanup(window: Any) -> bool:\n    event = getattr(window, "_galaxy_media_cleanup_cancel_event", None)\n    if not isinstance(event, threading.Event):\n        return False\n    event.set()\n    return True\n''',
    '''def cancel_active_media_cleanup(window: Any) -> bool:\n    event = getattr(window, "_galaxy_media_cleanup_cancel_event", None)\n    setter = getattr(event, "set", None)\n    if not callable(setter):\n        return False\n    setter()\n    return True\n''',
    "cancel event capability check",
)
WORKBENCH.write_text(workbench, encoding="utf-8")

entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
entrypoint = replace_once(
    entrypoint,
    'from media_cleanup import run_media_cleanup_self_test\n',
    '''from media_cleanup import run_media_cleanup_self_test\nfrom media_cleanup_workbench import (\n    cancel_active_media_cleanup,\n    install_media_cleanup_workbench,\n    media_cleanup_active,\n    run_media_cleanup_workbench_self_test,\n)\n''',
    "workbench import",
)
entrypoint = replace_once(
    entrypoint,
    '''install_desktop_manager(engine)\ninstall_desktop_runtime(engine)\ninstall_recovery_display(engine)\n''',
    '''install_desktop_manager(engine)\ninstall_desktop_runtime(engine)\ninstall_media_cleanup_workbench(engine)\ninstall_recovery_display(engine)\n''',
    "workbench install",
)
entrypoint = replace_once(
    entrypoint,
    '''    media_active = bool(window.running)\n    image_active = _IMAGE_JOB_LOCK.locked()\n    if not media_active and not image_active:\n        _original_close_app(window)\n        return\n''',
    '''    media_active = bool(window.running)\n    image_active = _IMAGE_JOB_LOCK.locked()\n    cleanup_active = media_cleanup_active(window)\n    if not media_active and not image_active and not cleanup_active:\n        _original_close_app(window)\n        return\n''',
    "cleanup close detection",
)
entrypoint = replace_once(
    entrypoint,
    '''    if image_active:\n        cancel_image_download_job()\n    if pausing_for_exit:\n''',
    '''    if image_active:\n        cancel_image_download_job()\n    if cleanup_active:\n        cancel_active_media_cleanup(window)\n    if pausing_for_exit:\n''',
    "cleanup close cancellation",
)
entrypoint = replace_once(
    entrypoint,
    '''    def finish_when_idle() -> None:\n        if window.running or _IMAGE_JOB_LOCK.locked():\n            window.after(100, finish_when_idle)\n            return\n''',
    '''    def finish_when_idle() -> None:\n        if window.running or _IMAGE_JOB_LOCK.locked() or media_cleanup_active(window):\n            window.after(100, finish_when_idle)\n            return\n''',
    "cleanup close wait",
)
entrypoint = replace_once(
    entrypoint,
    '''    assert getattr(engine.EngineWindow, "_galaxy_desktop_runtime_installed", False) is True\n    assert getattr(engine.EngineWindow, "_galaxy_recovery_display_installed", False) is True\n''',
    '''    assert getattr(engine.EngineWindow, "_galaxy_desktop_runtime_installed", False) is True\n    assert getattr(engine.EngineWindow, "_galaxy_media_cleanup_workbench_installed", False) is True\n    assert getattr(engine.EngineWindow, "_galaxy_recovery_display_installed", False) is True\n''',
    "workbench install assertion",
)
entrypoint = replace_once(
    entrypoint,
    '''    run_media_cleanup_self_test()\n    run_batch_input_self_test()\n''',
    '''    run_media_cleanup_self_test()\n    run_media_cleanup_workbench_self_test()\n    run_batch_input_self_test()\n''',
    "workbench self-test",
)
ENTRYPOINT.write_text(entrypoint, encoding="utf-8")

TEST.write_text(
    '''from __future__ import annotations\n\nimport sys\nimport unittest\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\nLOCAL_ENGINE = ROOT / "local-engine"\nsys.path.insert(0, str(LOCAL_ENGINE))\n\nfrom desktop_hooks import registered_after_build_ui_hooks  # noqa: E402\nfrom media_cleanup import CleanupRegion, MediaCleanupError, MediaProbe  # noqa: E402\nfrom media_cleanup_workbench import (  # noqa: E402\n    CleanupPreviewPlan,\n    build_preview_command,\n    build_preview_plan,\n    cancel_active_media_cleanup,\n    canvas_rect_to_region,\n    fit_preview_size,\n    install_media_cleanup_workbench,\n    media_cleanup_active,\n    run_media_cleanup_workbench_self_test,\n)\n\n\nclass MediaCleanupWorkbenchTests(unittest.TestCase):\n    def test_preview_size_never_upscales_and_respects_bounds(self) -> None:\n        self.assertEqual(fit_preview_size(640, 480), (640, 480))\n        width, height = fit_preview_size(3840, 2160)\n        self.assertLessEqual(width, 900)\n        self.assertLessEqual(height, 520)\n        self.assertAlmostEqual(width / height, 3840 / 2160, delta=0.02)\n        with self.assertRaises(MediaCleanupError):\n            fit_preview_size(1, 1080)\n\n    def test_preview_plan_uses_safe_video_seek(self) -> None:\n        video = build_preview_plan(MediaProbe(1920, 1080, 30.0, "video"))\n        self.assertEqual(video.seek_seconds, 1.0)\n        short = build_preview_plan(MediaProbe(1920, 1080, 0.5, "video"))\n        self.assertEqual(short.seek_seconds, 0.25)\n        image = build_preview_plan(MediaProbe(1024, 768, 0.0, "image"))\n        self.assertEqual(image.seek_seconds, 0.0)\n\n    def test_canvas_rect_maps_back_to_source_pixels(self) -> None:\n        plan = CleanupPreviewPlan("video", 1920, 1080, 900, 506, 1.0)\n        self.assertEqual(\n            canvas_rect_to_region(0, 0, 900, 506, plan),\n            CleanupRegion(0, 0, 1920, 1080),\n        )\n        corner = canvas_rect_to_region(810, 455, 900, 506, plan)\n        self.assertGreaterEqual(corner.x, 1728)\n        self.assertGreaterEqual(corner.y, 971)\n        self.assertLessEqual(corner.x + corner.width, 1920)\n        self.assertLessEqual(corner.y + corner.height, 1080)\n        with self.assertRaises(MediaCleanupError):\n            canvas_rect_to_region(10, 10, 10.2, 10.2, plan)\n\n    def test_preview_command_uses_png_frame_and_seek_only_for_video(self) -> None:\n        video = CleanupPreviewPlan("video", 1920, 1080, 900, 506, 1.0)\n        video_command = build_preview_command(\n            Path("ffmpeg.exe"), Path("input.mp4"), Path("preview.png"), video\n        )\n        self.assertIn("-ss", video_command)\n        self.assertIn("scale=900:506", video_command)\n        self.assertIn("-frames:v", video_command)\n        self.assertEqual(video_command[-1], "preview.png")\n\n        image = CleanupPreviewPlan("image", 640, 480, 640, 480, 0.0)\n        image_command = build_preview_command(\n            Path("ffmpeg.exe"), Path("input.png"), Path("preview.png"), image\n        )\n        self.assertNotIn("-ss", image_command)\n\n    def test_cancel_uses_event_capability_not_concrete_type(self) -> None:\n        class EventLike:\n            def __init__(self) -> None:\n                self.called = False\n\n            def set(self) -> None:\n                self.called = True\n\n        class Window:\n            _galaxy_media_cleanup_running = True\n\n        window = Window()\n        event = EventLike()\n        window._galaxy_media_cleanup_cancel_event = event\n        self.assertTrue(media_cleanup_active(window))\n        self.assertTrue(cancel_active_media_cleanup(window))\n        self.assertTrue(event.called)\n        window._galaxy_media_cleanup_cancel_event = object()\n        self.assertFalse(cancel_active_media_cleanup(window))\n\n    def test_install_registers_canonical_after_build_hook(self) -> None:\n        class FakeWindow:\n            pass\n\n        class FakeEngine:\n            EngineWindow = FakeWindow\n\n        install_media_cleanup_workbench(FakeEngine)\n        self.assertIn("media-cleanup-workbench", registered_after_build_ui_hooks(FakeWindow))\n        self.assertTrue(FakeWindow._galaxy_media_cleanup_workbench_installed)\n\n    def test_embedded_self_test(self) -> None:\n        run_media_cleanup_workbench_self_test()\n\n\nif __name__ == "__main__":\n    unittest.main(verbosity=2)\n''',
    encoding="utf-8",
)

print("media cleanup workbench integration transform complete")
