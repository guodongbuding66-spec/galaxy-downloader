from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from course_attachments import replace_course_item_attachments
from course_structure import CourseStructureError, set_course_item_metadata, upsert_course_section
from course_subtitles import set_course_item_subtitle_tracks
from course_workspace import add_media_to_course, create_course
from headless_learning_api import HeadlessLearningApi, HeadlessLearningApiError, HeadlessLearningContext
from headless_learning_structure import install_headless_learning_structure
from media_library import list_media_items, sync_media_library


class HeadlessLearningStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_headless_learning_structure()

    def _context(self, root: Path) -> HeadlessLearningContext:
        program = root / "program"
        data = root / "data"
        state = root / "state"
        downloads = root / "downloads"
        for target in (program, data, state, downloads):
            target.mkdir()
        return HeadlessLearningContext(program, data, state, downloads)

    def _course(self, context: HeadlessLearningContext, slug: str = "python-bootcamp") -> str:
        with patch(
            "course_workspace.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        ):
            return create_course(
                context,
                "Python Bootcamp",
                f"https://www.udemy.com/course/{slug}/",
                provider="udemy",
            )["id"]

    def _item(self, context: HeadlessLearningContext, course_id: str, filename: str) -> str:
        output = context.downloads_path / filename
        output.write_bytes(b"lesson")
        sync_media_library(
            context,
            [
                {
                    "state": "completed",
                    "finishedAt": "2026-09-05T00:00:00Z",
                    "label": output.stem,
                    "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
                    "filePath": str(output),
                    "fileName": output.name,
                    "collectionMode": "course",
                }
            ],
        )
        media_id = next(
            item["id"]
            for item in list_media_items(context, limit=100)
            if item["fileName"] == output.name
        )
        return add_media_to_course(context, course_id, media_id)

    def test_course_detail_and_items_include_structure_subtitles_attachments_and_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self._context(root)
            api = HeadlessLearningApi(context.downloads_path, context=context)
            course_id = self._course(context)
            first_item = self._item(context, course_id, "opaque-a.mp4")
            second_item = self._item(context, course_id, "opaque-b.mkv")

            intro = upsert_course_section(
                context,
                course_id,
                provider_section_id="udemy:chapter:1",
                title="Getting Started",
                position=1,
            )
            basics = upsert_course_section(
                context,
                course_id,
                provider_section_id="udemy:chapter:2",
                title="Python Basics",
                position=2,
            )
            set_course_item_metadata(
                context,
                first_item,
                section_id=intro["id"],
                provider_item_id="udemy:asset:501",
                provider_title="Welcome to the Course",
                provider_position=1,
            )
            set_course_item_metadata(
                context,
                second_item,
                section_id=basics["id"],
                provider_item_id="udemy:asset:502",
                provider_title="Variables and Types",
                provider_position=2,
            )
            set_course_item_subtitle_tracks(
                context,
                first_item,
                [
                    {"language": "en", "kind": "manual"},
                    {"language": "zh-CN", "kind": "automatic"},
                ],
            )
            replace_course_item_attachments(
                context,
                first_item,
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

            detail = api.course_detail(course_id)
            self.assertEqual(detail["course"]["id"], course_id)
            self.assertEqual([section["title"] for section in detail["sections"]], ["Getting Started", "Python Basics"])
            self.assertEqual([item["title"] for item in detail["items"]], ["Welcome to the Course", "Variables and Types"])
            self.assertEqual(detail["items"][0]["sectionTitle"], "Getting Started")
            self.assertEqual(detail["items"][0]["providerItemId"], "udemy:asset:501")
            self.assertEqual(detail["items"][1]["providerPosition"], 2)
            self.assertEqual(
                detail["items"][0]["subtitleTracks"],
                [
                    {"language": "en", "kind": "manual"},
                    {"language": "zh-CN", "kind": "automatic"},
                ],
            )
            self.assertEqual(len(detail["items"][0]["attachments"]), 1)
            attachment = detail["items"][0]["attachments"][0]
            self.assertEqual(attachment["providerAttachmentId"], "udemy:asset:7001")
            self.assertEqual(attachment["fileName"], "starter.zip")
            self.assertNotIn("providerCourseId", attachment)
            self.assertNotIn("providerLectureId", attachment)
            self.assertNotIn("url", str(attachment).lower())
            self.assertNotIn("attachments", detail["items"][1])
            self.assertEqual(detail["items"][0]["previousItemId"], "")
            self.assertEqual(detail["items"][0]["nextItemId"], second_item)
            self.assertEqual(detail["items"][1]["previousItemId"], first_item)
            self.assertEqual(detail["items"][1]["nextItemId"], "")
            self.assertEqual(detail["items"][0]["sectionItemIndex"], 1)
            self.assertEqual(detail["items"][0]["sectionItemCount"], 1)
            self.assertEqual(detail["sections"][0]["itemCount"], 1)
            self.assertEqual(detail["sections"][0]["previousSectionId"], "")
            self.assertEqual(detail["sections"][0]["nextSectionId"], basics["id"])
            self.assertEqual(detail["sections"][1]["previousSectionId"], intro["id"])
            self.assertEqual(detail["sections"][1]["nextSectionId"], "")

            items = api.items(course_id)
            self.assertEqual(items["courseId"], course_id)
            self.assertEqual([section["position"] for section in items["sections"]], [1, 2])
            self.assertEqual(items["items"][1]["sectionTitle"], "Python Basics")
            self.assertEqual(items["items"][1]["providerTitle"], "Variables and Types")
            self.assertEqual(items["items"][0]["nextItemId"], second_item)
            self.assertEqual(items["items"][0]["attachments"][0]["title"], "Starter Files")
            self.assertNotIn("providerCourseId", str(items))
            self.assertNotIn("providerLectureId", str(items))

    def test_unstructured_course_remains_backward_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self._context(root)
            api = HeadlessLearningApi(context.downloads_path, context=context)
            course_id = self._course(context, "plain-course")
            self._item(context, course_id, "plain.mp4")

            detail = api.course_detail(course_id)
            self.assertEqual(detail["sections"], [])
            self.assertEqual(len(detail["items"]), 1)
            self.assertEqual(detail["items"][0]["title"], "plain")
            self.assertNotIn("sectionTitle", detail["items"][0])
            self.assertNotIn("subtitleTracks", detail["items"][0])
            self.assertNotIn("attachments", detail["items"][0])
            self.assertNotIn("previousItemId", detail["items"][0])
            self.assertNotIn("nextItemId", detail["items"][0])

    def test_structure_lookup_failure_uses_typed_learning_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self._context(root)
            api = HeadlessLearningApi(context.downloads_path, context=context)
            course_id = self._course(context)
            with patch(
                "headless_learning_structure.list_course_sections",
                side_effect=CourseStructureError("structure database unavailable"),
            ):
                with self.assertRaises(HeadlessLearningApiError) as caught:
                    api.course_detail(course_id)
            self.assertEqual(caught.exception.code, "LEARNING_COURSE_STRUCTURE_ERROR")
            self.assertIn("structure database unavailable", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
