from __future__ import annotations

import unittest

from desktop_learning import (
    build_course_tree_rows,
    managed_download_finished,
    managed_download_status_text,
)


class DesktopLearningModelTests(unittest.TestCase):
    def test_course_tree_groups_and_orders_sections_and_lectures(self) -> None:
        rows = build_course_tree_rows(
            [
                {"id": "section-b", "title": "第二章", "position": 2},
                {"id": "section-a", "title": "第一章", "position": 1},
            ],
            [
                {"id": "lecture-b2", "sectionId": "section-b", "title": "2.2", "providerPosition": 2},
                {"id": "lecture-a1", "sectionId": "section-a", "title": "1.1", "providerPosition": 1},
                {"id": "lecture-b1", "sectionId": "section-b", "title": "2.1", "providerPosition": 1},
            ],
        )
        self.assertEqual(
            [row["title"] for row in rows],
            ["第一章", "1.1", "第二章", "2.1", "2.2"],
        )
        self.assertEqual(rows[1]["parent"], rows[0]["key"])
        self.assertEqual(rows[3]["parent"], rows[2]["key"])

    def test_unstructured_and_unknown_section_items_remain_visible(self) -> None:
        rows = build_course_tree_rows(
            [],
            [
                {"id": "manual", "title": "手动媒体", "progressSeconds": 3},
                {"id": "orphan", "sectionId": "missing", "title": "孤立课时"},
            ],
        )
        self.assertEqual(rows[0]["title"], "未分组课时")
        self.assertEqual({row.get("itemId") for row in rows[1:]}, {"manual", "orphan"})
        self.assertTrue(all(row["parent"] == rows[0]["key"] for row in rows[1:]))

    def test_status_text_uses_only_public_state_fields(self) -> None:
        payload = {
            "job": {
                "state": "running",
                "progress": 42.4,
                "detail": "/private/path/lesson.mp4",
                "trackingId": "secret-tracking",
            },
            "session": {"syncState": "pending", "trackingId": "secret-session"},
        }
        rendered = managed_download_status_text(payload)
        self.assertEqual(rendered, "正在下载 · 42% · 等待课程同步")
        self.assertNotIn("private", rendered)
        self.assertNotIn("tracking", rendered)

    def test_completed_download_waits_for_course_sync_terminal_state(self) -> None:
        self.assertFalse(
            managed_download_finished(
                {"job": {"state": "completed"}, "session": {"syncState": "pending"}}
            )
        )
        self.assertTrue(
            managed_download_finished(
                {"job": {"state": "completed"}, "session": {"syncState": "synced"}}
            )
        )
        self.assertTrue(
            managed_download_finished(
                {"job": {"state": "failed"}, "session": {"syncState": "pending"}}
            )
        )


if __name__ == "__main__":
    unittest.main()
