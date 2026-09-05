from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from course_attachments import (
    CourseAttachmentError,
    attachment_download_context,
    ensure_course_attachments,
    enrich_course_item_attachments,
    list_course_item_attachments,
    replace_course_item_attachments,
)
from course_workspace import add_media_to_course, create_course, delete_course
from media_library import list_media_items, sync_media_library


class CourseAttachmentTests(unittest.TestCase):
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

    def _course_and_item(self, engine, downloads: Path) -> tuple[str, str]:
        with patch(
            "course_workspace.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        ):
            course_id = create_course(
                engine,
                "Python Bootcamp",
                "https://www.udemy.com/course/python-bootcamp/",
                provider="udemy",
            )["id"]
        output = downloads / "lesson.mp4"
        output.write_bytes(b"lesson")
        sync_media_library(
            engine,
            [{
                "state": "completed",
                "finishedAt": "2026-09-06T00:00:00Z",
                "label": "lesson",
                "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
                "filePath": str(output),
                "fileName": output.name,
                "collectionMode": "course",
            }],
        )
        media_id = next(
            item["id"] for item in list_media_items(engine, limit=100)
            if item["fileName"] == output.name
        )
        return course_id, add_media_to_course(engine, course_id, media_id)

    def test_inventory_is_safe_stable_and_download_context_is_internal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            _course_id, item_id = self._course_and_item(engine, downloads)

            first = replace_course_item_attachments(
                engine,
                item_id,
                provider="udemy",
                provider_lecture_id="udemy:lecture:12345",
                attachments=[
                    {
                        "providerAttachmentId": "udemy:asset:501",
                        "title": "Starter Files",
                        "fileName": "../../starter.zip",
                        "assetType": "File",
                    },
                    {
                        "providerAttachmentId": "udemy:asset:502",
                        "title": "Cheat Sheet",
                        "fileName": r"folder\\cheat-sheet.pdf",
                        "assetType": "E-Book",
                    },
                ],
            )
            self.assertEqual([item["fileName"] for item in first["attachments"]], ["starter.zip", "cheat-sheet.pdf"])
            first_id = first["attachments"][0]["id"]

            second = replace_course_item_attachments(
                engine,
                item_id,
                provider="udemy",
                provider_lecture_id="udemy:lecture:12345",
                attachments=[{
                    "providerAttachmentId": "udemy:asset:501",
                    "title": "Starter Files v2",
                    "fileName": "starter-v2.zip",
                    "assetType": "File",
                }],
            )
            self.assertEqual(second["attachments"][0]["id"], first_id)
            public = list_course_item_attachments(engine, [item_id])[item_id]
            self.assertEqual(len(public), 1)
            self.assertEqual(public[0]["title"], "Starter Files v2")
            self.assertNotIn("providerLectureId", public[0])
            self.assertNotIn("url", str(public).lower())

            context = attachment_download_context(engine, first_id)
            self.assertEqual(context["providerLectureId"], "udemy:lecture:12345")
            self.assertEqual(context["providerAttachmentId"], "udemy:asset:501")
            self.assertEqual(context["provider"], "udemy")

            enriched = enrich_course_item_attachments(engine, [{"id": item_id, "title": "Lesson"}])
            self.assertEqual(enriched[0]["attachments"], public)

    def test_empty_inventory_clears_stale_rows_but_keeps_authorized_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            _course_id, item_id = self._course_and_item(engine, downloads)
            created = replace_course_item_attachments(
                engine,
                item_id,
                provider="udemy",
                provider_lecture_id="udemy:lecture:99",
                attachments=[{
                    "providerAttachmentId": "udemy:asset:100",
                    "title": "Notes",
                    "fileName": "notes.pdf",
                    "assetType": "File",
                }],
            )
            attachment_id = created["attachments"][0]["id"]
            cleared = replace_course_item_attachments(
                engine,
                item_id,
                provider="udemy",
                provider_lecture_id="udemy:lecture:99",
                attachments=[],
            )
            self.assertEqual(cleared["attachments"], [])
            self.assertEqual(list_course_item_attachments(engine, [item_id]), {})
            with self.assertRaisesRegex(CourseAttachmentError, "not found"):
                attachment_download_context(engine, attachment_id)

    def test_course_delete_cascades_context_and_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            course_id, item_id = self._course_and_item(engine, downloads)
            replace_course_item_attachments(
                engine,
                item_id,
                provider="udemy",
                provider_lecture_id="udemy:lecture:88",
                attachments=[{
                    "providerAttachmentId": "udemy:asset:200",
                    "title": "Workbook",
                    "fileName": "workbook.pdf",
                    "assetType": "File",
                }],
            )
            self.assertEqual(ensure_course_attachments(engine)["attachments"], 1)
            self.assertTrue(delete_course(engine, course_id))
            status = ensure_course_attachments(engine)
            self.assertEqual(status["attachments"], 0)
            self.assertEqual(status["contexts"], 0)

    def test_invalid_provider_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            _course_id, item_id = self._course_and_item(engine, downloads)
            with self.assertRaises(CourseAttachmentError):
                replace_course_item_attachments(
                    engine,
                    item_id,
                    provider="udemy",
                    provider_lecture_id="https://udemy.com/lecture/12?token=SECRET",
                    attachments=[],
                )


if __name__ == "__main__":
    unittest.main()
