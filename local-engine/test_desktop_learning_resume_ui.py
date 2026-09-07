from __future__ import annotations

import json
import unittest

from desktop_learning_navigation import resume_action_text


class DesktopLearningResumeUiTests(unittest.TestCase):
    def test_resume_opened_reports_saved_position(self) -> None:
        result = {
            "opened": True,
            "resume": {
                "state": "resume",
                "progressSeconds": 72.4,
                "item": {"title": "第二课", "mediaId": "c" * 32},
            },
        }
        self.assertEqual(resume_action_text(result), "已从 72s 继续：第二课")

    def test_start_opened_reports_course_start(self) -> None:
        result = {
            "opened": True,
            "resume": {
                "state": "start",
                "progressSeconds": 0,
                "item": {"title": "第一课", "mediaId": "c" * 32},
            },
        }
        self.assertEqual(resume_action_text(result), "已开始：第一课")

    def test_completed_and_empty_are_explicit(self) -> None:
        self.assertEqual(
            resume_action_text({"opened": False, "resume": {"state": "completed", "item": None}}),
            "课程已完成",
        )
        self.assertEqual(
            resume_action_text({"opened": False, "resume": {"state": "empty", "item": None}}),
            "没有可播放的本地课时",
        )

    def test_failed_launch_is_explicit(self) -> None:
        result = {
            "opened": False,
            "resume": {
                "state": "resume",
                "progressSeconds": 12,
                "item": {"title": "第三课", "mediaId": "c" * 32},
            },
        }
        self.assertEqual(resume_action_text(result), "未能打开课程播放器")

    def test_status_never_surfaces_filesystem_paths(self) -> None:
        result = {
            "opened": True,
            "resume": {
                "state": "resume",
                "progressSeconds": 10,
                "localPath": "C:/Users/private/lesson.mp4",
                "filePath": "/home/private/lesson.mp4",
                "item": {
                    "title": "安全课时",
                    "mediaId": "c" * 32,
                    "localPath": "C:/secret",
                    "filePath": "/secret",
                },
            },
        }
        rendered = resume_action_text(result)
        serialized = json.dumps(rendered, ensure_ascii=False)
        self.assertNotIn("C:/Users", serialized)
        self.assertNotIn("/home/private", serialized)
        self.assertNotIn("/secret", serialized)
        self.assertEqual(rendered, "已从 10s 继续：安全课时")


if __name__ == "__main__":
    unittest.main()