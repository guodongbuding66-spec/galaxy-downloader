from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from desktop_course_resume import launch_desktop_course_resume


COURSE_ID = "a" * 32
ITEM_ID = "b" * 32
MEDIA_ID = "c" * 32


def _core_result(state: str, *, progress: float = 0.0, item: bool = True) -> dict:
    payload = {
        "courseId": COURSE_ID,
        "state": state,
        "item": None,
        "progressSeconds": progress,
        "completed": state == "completed",
        "reason": state,
        "localPath": "C:/Users/example/secret",
    }
    if item:
        payload["item"] = {
            "id": ITEM_ID,
            "mediaId": MEDIA_ID,
            "position": 1,
            "title": "Lesson",
            "mediaType": "video",
            "durationSeconds": 120.0,
            "available": True,
            "localPath": "/private/lesson.mp4",
            "filePath": "C:/private/lesson.mp4",
        }
    return payload


class DesktopCourseResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.learning_api = SimpleNamespace(context=object())

    def test_resume_launches_existing_player_at_saved_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            player = Path(directory) / "player.html"
            opener = Mock(return_value=True)
            with patch("headless_learning_resume.resolve_course_resume", return_value=_core_result("resume", progress=42.5)), patch(
                "desktop_course_resume.create_local_player", return_value=player
            ) as create_player:
                result = launch_desktop_course_resume(self.learning_api, COURSE_ID, opener=opener)

        create_player.assert_called_once_with(self.learning_api.context, MEDIA_ID, start_seconds=42.5)
        opener.assert_called_once()
        self.assertTrue(opener.call_args.args[0].startswith("file:"))
        self.assertTrue(result["opened"])
        self.assertEqual(result["resume"]["state"], "resume")
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("localPath", serialized)
        self.assertNotIn("filePath", serialized)
        self.assertNotIn("C:/Users", serialized)
        self.assertNotIn("/private/lesson.mp4", serialized)

    def test_start_launches_at_zero_even_if_progress_is_nonzero(self) -> None:
        opener = Mock(return_value=True)
        with patch("headless_learning_resume.resolve_course_resume", return_value=_core_result("start", progress=99.0)), patch(
            "desktop_course_resume.create_local_player", return_value=Path("player.html")
        ) as create_player:
            result = launch_desktop_course_resume(self.learning_api, COURSE_ID, opener=opener)

        create_player.assert_called_once_with(self.learning_api.context, MEDIA_ID, start_seconds=0.0)
        self.assertTrue(result["opened"])

    def test_completed_course_does_not_open_player(self) -> None:
        opener = Mock(return_value=True)
        with patch("headless_learning_resume.resolve_course_resume", return_value=_core_result("completed", item=False)), patch(
            "desktop_course_resume.create_local_player"
        ) as create_player:
            result = launch_desktop_course_resume(self.learning_api, COURSE_ID, opener=opener)

        self.assertFalse(result["opened"])
        create_player.assert_not_called()
        opener.assert_not_called()

    def test_empty_course_does_not_open_player(self) -> None:
        opener = Mock(return_value=True)
        with patch("headless_learning_resume.resolve_course_resume", return_value=_core_result("empty", item=False)), patch(
            "desktop_course_resume.create_local_player"
        ) as create_player:
            result = launch_desktop_course_resume(self.learning_api, COURSE_ID, opener=opener)

        self.assertFalse(result["opened"])
        create_player.assert_not_called()
        opener.assert_not_called()

    def test_browser_rejection_is_reported_without_exposing_player_path(self) -> None:
        opener = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as directory:
            player = Path(directory) / "player.html"
            with patch("headless_learning_resume.resolve_course_resume", return_value=_core_result("resume", progress=5.0)), patch(
                "desktop_course_resume.create_local_player", return_value=player
            ):
                result = launch_desktop_course_resume(self.learning_api, COURSE_ID, opener=opener)

        self.assertFalse(result["opened"])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(str(player), serialized)


if __name__ == "__main__":
    unittest.main()
