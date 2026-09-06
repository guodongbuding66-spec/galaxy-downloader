from __future__ import annotations

import unittest

from desktop_learning_attachments import (
    attachment_job_status_text,
    build_attachment_rows,
    format_attachment_size,
)


class DesktopLearningAttachmentModelTests(unittest.TestCase):
    def test_attachment_rows_keep_only_public_display_fields(self) -> None:
        rows = build_attachment_rows(
            [
                {
                    "id": "item-1",
                    "title": "Variables",
                    "attachments": [
                        {
                            "id": "a" * 32,
                            "title": "Starter Files",
                            "fileName": "starter.zip",
                            "assetType": "File",
                            "downloaded": True,
                            "sizeBytes": 1536,
                            "providerCourseId": "udemy:course:SECRET",
                            "providerLectureId": "udemy:lecture:SECRET",
                            "relativePath": "private/path.zip",
                            "url": "https://cdn.example/?sig=SECRET",
                        }
                    ],
                }
            ]
        )
        self.assertEqual(
            rows,
            [
                {
                    "id": "a" * 32,
                    "lecture": "Variables",
                    "title": "Starter Files",
                    "fileName": "starter.zip",
                    "assetType": "File",
                    "downloaded": True,
                    "sizeBytes": 1536,
                }
            ],
        )
        rendered = str(rows)
        self.assertNotIn("providerCourseId", rendered)
        self.assertNotIn("providerLectureId", rendered)
        self.assertNotIn("relativePath", rendered)
        self.assertNotIn("https://", rendered)
        self.assertNotIn("SECRET", rendered)

    def test_invalid_attachment_ids_are_ignored(self) -> None:
        rows = build_attachment_rows(
            [{"title": "Lesson", "attachments": [{"id": "not-an-id", "title": "Bad"}]}]
        )
        self.assertEqual(rows, [])

    def test_status_text_uses_public_job_fields_only(self) -> None:
        rendered = attachment_job_status_text(
            {
                "state": "running",
                "progress": 50,
                "downloadedBytes": 1024,
                "sizeBytes": 2048,
                "fileName": "starter.zip",
                "providerCourseId": "udemy:course:SECRET",
                "path": "/private/starter.zip",
                "url": "https://cdn.example/?sig=SECRET",
            }
        )
        self.assertEqual(rendered, "正在下载附件 · 50% · 1.0 KB / 2.0 KB")
        self.assertNotIn("SECRET", rendered)
        self.assertNotIn("private", rendered)
        self.assertNotIn("https://", rendered)

    def test_failed_status_never_surfaces_backend_error_detail(self) -> None:
        rendered = attachment_job_status_text(
            {
                "state": "failed",
                "progress": 40,
                "error": "https://cdn.example/private?token=SECRET C:/Users/private/file.zip",
            }
        )
        self.assertEqual(rendered, "附件下载失败")
        self.assertNotIn("SECRET", rendered)
        self.assertNotIn("private", rendered.lower())
        self.assertNotIn("https://", rendered)

    def test_size_format_is_bounded_and_readable(self) -> None:
        self.assertEqual(format_attachment_size(0), "—")
        self.assertEqual(format_attachment_size(512), "512 B")
        self.assertEqual(format_attachment_size(1536), "1.5 KB")
        self.assertEqual(format_attachment_size(2 * 1024 * 1024), "2.0 MB")


if __name__ == "__main__":
    unittest.main()
