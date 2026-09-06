from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from course_attachment_files import (
    CourseAttachmentFileError,
    attachment_file_record,
    attachment_file_status,
    enrich_course_attachment_files,
    record_course_attachment_file,
)
from course_attachments import list_course_item_attachments, replace_course_item_attachments
from course_workspace import add_media_to_course, create_course
from media_library import list_media_items, sync_media_library


class CourseAttachmentFileTests(unittest.TestCase):
    def _engine(self, root: Path):
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        for target in (downloads, state, data):
            target.mkdir()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def data_dir() -> Path:
                return data

            @staticmethod
            def state_dir() -> Path:
                return state

            @staticmethod
            def default_download_dir() -> Path:
                return downloads

        return Engine, downloads

    def _attachment(self, engine, downloads: Path) -> tuple[str, str]:
        with patch(
            "course_workspace.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        ):
            course_id = create_course(
                engine,
                "Python Bootcamp",
                "https://www.udemy.com/course/python-bootcamp/?couponCode=PRIVATE",
                provider="udemy",
            )["id"]
        media = downloads / "lesson.mp4"
        media.write_bytes(b"lesson")
        sync_media_library(
            engine,
            [{
                "state": "completed",
                "finishedAt": "2026-09-06T00:00:00Z",
                "label": "lesson",
                "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
                "filePath": str(media),
                "fileName": media.name,
                "collectionMode": "course",
            }],
        )
        media_id = next(
            row["id"] for row in list_media_items(engine, limit=100)
            if row["fileName"] == media.name
        )
        item_id = add_media_to_course(engine, course_id, media_id)
        result = replace_course_item_attachments(
            engine,
            item_id,
            provider="udemy",
            provider_course_id="udemy:course:456",
            provider_lecture_id="udemy:lecture:1001",
            attachments=[{
                "providerAttachmentId": "udemy:asset:7001",
                "title": "Starter Files",
                "fileName": "starter.zip",
                "assetType": "File",
            }],
        )
        return item_id, result["attachments"][0]["id"]

    def test_file_status_is_public_safe_and_requires_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            _item_id, attachment_id = self._attachment(engine, downloads)
            relative = Path("Course Attachments") / "x" / attachment_id / "starter.zip"
            output = downloads / relative
            output.parent.mkdir(parents=True)
            output.write_bytes(b"archive")

            record = record_course_attachment_file(
                engine,
                attachment_id,
                relative_path=relative.as_posix(),
                size_bytes=7,
            )
            self.assertEqual(record["sizeBytes"], 7)
            status = attachment_file_status(engine, attachment_id)
            self.assertEqual(
                status,
                {
                    "attachmentId": attachment_id,
                    "downloaded": True,
                    "sizeBytes": 7,
                    "fileName": "starter.zip",
                },
            )
            self.assertNotIn("relativePath", status)
            self.assertNotIn(str(downloads), str(status))

            output.unlink()
            missing = attachment_file_status(engine, attachment_id)
            self.assertFalse(missing["downloaded"])
            self.assertEqual(missing["sizeBytes"], 0)
            self.assertEqual(missing["fileName"], "")

    def test_inventory_refresh_preserves_file_record_for_same_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            item_id, attachment_id = self._attachment(engine, downloads)
            relative = Path("Course Attachments") / item_id / attachment_id / "starter.zip"
            output = downloads / relative
            output.parent.mkdir(parents=True)
            output.write_bytes(b"archive")
            record_course_attachment_file(
                engine,
                attachment_id,
                relative_path=relative.as_posix(),
                size_bytes=7,
            )

            refreshed = replace_course_item_attachments(
                engine,
                item_id,
                provider="udemy",
                provider_course_id="udemy:course:456",
                provider_lecture_id="udemy:lecture:1001",
                attachments=[{
                    "providerAttachmentId": "udemy:asset:7001",
                    "title": "Starter Files Updated",
                    "fileName": "starter.zip",
                    "assetType": "File",
                }],
            )
            self.assertEqual(refreshed["attachments"][0]["id"], attachment_id)
            self.assertIsNotNone(attachment_file_record(engine, attachment_id))
            self.assertTrue(attachment_file_status(engine, attachment_id)["downloaded"])

            public_items = enrich_course_attachment_files(
                engine,
                [{"id": item_id, "attachments": list_course_item_attachments(engine, [item_id])[item_id]}],
            )
            attachment = public_items[0]["attachments"][0]
            self.assertTrue(attachment["downloaded"])
            self.assertEqual(attachment["sizeBytes"], 7)
            self.assertNotIn("relativePath", attachment)

    def test_stale_inventory_deletion_cascades_file_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            item_id, attachment_id = self._attachment(engine, downloads)
            relative = Path("Course Attachments") / item_id / attachment_id / "starter.zip"
            output = downloads / relative
            output.parent.mkdir(parents=True)
            output.write_bytes(b"archive")
            record_course_attachment_file(
                engine,
                attachment_id,
                relative_path=relative.as_posix(),
                size_bytes=7,
            )

            replace_course_item_attachments(
                engine,
                item_id,
                provider="udemy",
                provider_course_id="udemy:course:456",
                provider_lecture_id="udemy:lecture:1001",
                attachments=[],
            )
            self.assertIsNone(attachment_file_record(engine, attachment_id))

    def test_relative_path_rejects_traversal_and_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            _item_id, attachment_id = self._attachment(engine, downloads)
            for unsafe in ("../secret.txt", "/tmp/secret.txt", "Course Attachments/../secret.txt"):
                with self.subTest(unsafe=unsafe):
                    with self.assertRaises(CourseAttachmentFileError):
                        record_course_attachment_file(
                            engine,
                            attachment_id,
                            relative_path=unsafe,
                            size_bytes=1,
                        )


if __name__ == "__main__":
    unittest.main()
