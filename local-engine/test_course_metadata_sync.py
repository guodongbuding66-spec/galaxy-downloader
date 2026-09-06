from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import headless_service
from course_attachments import attachment_download_context, enrich_course_item_attachments
from course_download_sessions import (
    CourseDownloadSessionError,
    discard_course_download_outputs,
    register_course_download_session,
    remove_course_download_session,
    sync_course_download_outputs,
)
from course_structure import enrich_course_items, list_course_sections
from course_subtitles import enrich_course_item_subtitles
from course_workspace import create_course, list_course_items
from headless_course_metadata_tracking import (
    install_headless_course_metadata_tracking,
    tracked_course_metadata,
)
from headless_output_tracking import (
    install_headless_output_tracking,
    new_output_tracking_id,
    tracked_output_paths,
)


class CourseMetadataSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_headless_output_tracking()
        install_headless_course_metadata_tracking()

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

    def _course(self, engine) -> str:
        with patch(
            "course_workspace.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        ):
            return create_course(
                engine,
                "Python Bootcamp",
                "https://www.udemy.com/course/python-bootcamp/",
                provider="udemy",
            )["id"]

    def _session(self, course_id: str) -> tuple[str, str]:
        job_id = uuid.uuid4().hex
        tracking_id = new_output_tracking_id()
        register_course_download_session(
            job_id=job_id,
            tracking_id=tracking_id,
            course_id=course_id,
            provider="udemy",
            source_url="https://www.udemy.com/course/python-bootcamp/?couponCode=PRIVATE",
        )
        self.addCleanup(remove_course_download_session, job_id)
        return job_id, tracking_id

    def _record_lesson(
        self,
        downloads: Path,
        tracking_id: str,
        output: Path,
        *,
        asset_id: str,
        title: str,
        chapter: str = "",
        chapter_number: int = 0,
        playlist_index: int = 0,
        lecture_id: str = "",
        attachments: list[dict[str, str]] | None = None,
    ) -> None:
        options = headless_service._download_options(
            {"_outputTrackingId": tracking_id},
            downloads,
            lambda _event: None,
        )
        metadata_hooks = options.get("postprocessor_hooks") or []
        output_hooks = options.get("post_hooks") or []
        self.assertEqual(len(metadata_hooks), 1)
        self.assertEqual(len(output_hooks), 1)
        info = {
            "filepath": str(output),
            "extractor_key": "Udemy",
            "id": asset_id,
            "title": title,
            "chapter": chapter,
            "chapter_number": chapter_number,
            "playlist_index": playlist_index,
            "url": "https://cdn.example/media?sig=PRIVATE",
            "http_headers": {"Authorization": "PRIVATE"},
            "subtitles": {"en": [{"url": "https://cdn.example/sub.vtt?sig=PRIVATE"}]},
            "automatic_captions": {
                "zh-CN": [{"url": "https://cdn.example/auto.vtt?sig=PRIVATE"}]
            },
        }
        if lecture_id:
            info["_galaxyCourseAttachmentInventory"] = {
                "provider": "udemy",
                "providerCourseId": "udemy:course:456",
                "providerLectureId": f"udemy:lecture:{lecture_id}",
                "attachments": list(attachments or []),
            }
        metadata_hooks[0](
            {
                "status": "finished",
                "postprocessor": "MoveFiles",
                "info_dict": info,
            }
        )
        output_hooks[0](str(output))

    def test_two_lessons_sync_into_real_sections_subtitles_and_attachment_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            course_id = self._course(engine)
            job_id, tracking_id = self._session(course_id)

            first = downloads / "opaque-file-a.mp4"
            second = downloads / "opaque-file-b.mkv"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            self._record_lesson(
                downloads,
                tracking_id,
                first,
                asset_id="501",
                title="Welcome to the Course",
                chapter="Getting Started",
                chapter_number=1,
                playlist_index=1,
                lecture_id="1001",
                attachments=[{
                    "providerAttachmentId": "udemy:asset:7001",
                    "title": "Starter Files",
                    "fileName": "starter.zip",
                    "assetType": "File",
                    "downloadUrl": "https://cdn.example/starter.zip?sig=PRIVATE",
                }],
            )
            self._record_lesson(
                downloads,
                tracking_id,
                second,
                asset_id="502",
                title="Variables and Types",
                chapter="Python Basics",
                chapter_number=2,
                playlist_index=2,
                lecture_id="1002",
                attachments=[],
            )

            result = sync_course_download_outputs(engine, job_id)
            self.assertEqual(result["syncState"], "synced")
            self.assertEqual(result["syncedCount"], 2)

            sections = list_course_sections(engine, course_id)
            self.assertEqual([section["title"] for section in sections], ["Getting Started", "Python Basics"])
            self.assertEqual([section["position"] for section in sections], [1, 2])
            items = enrich_course_items(engine, list_course_items(engine, course_id))
            items = enrich_course_item_subtitles(engine, items)
            items = enrich_course_item_attachments(engine, items)
            self.assertEqual([item["title"] for item in items], ["Welcome to the Course", "Variables and Types"])
            self.assertEqual(items[0]["providerItemId"], "udemy:asset:501")
            self.assertEqual(items[0]["sectionTitle"], "Getting Started")
            self.assertEqual(items[1]["providerItemId"], "udemy:asset:502")
            self.assertEqual(items[1]["sectionTitle"], "Python Basics")
            self.assertEqual(
                items[0]["subtitleTracks"],
                [
                    {"language": "en", "kind": "manual"},
                    {"language": "zh-CN", "kind": "automatic"},
                ],
            )
            self.assertEqual(len(items[0]["attachments"]), 1)
            attachment = items[0]["attachments"][0]
            self.assertEqual(attachment["providerAttachmentId"], "udemy:asset:7001")
            self.assertEqual(attachment["fileName"], "starter.zip")
            internal = attachment_download_context(engine, attachment["id"])
            self.assertEqual(internal["providerCourseId"], "udemy:course:456")
            self.assertEqual(internal["providerLectureId"], "udemy:lecture:1001")
            self.assertNotIn("attachments", items[1])
            self.assertNotIn("PRIVATE", str(items))
            self.assertNotIn("url", str(items).lower())
            self.assertNotIn("providerCourseId", str(items))
            self.assertNotIn("providerLectureId", str(items))
            self.assertEqual(tracked_output_paths(tracking_id), [])
            self.assertEqual(tracked_course_metadata(tracking_id), {})

            repeated = sync_course_download_outputs(engine, job_id)
            self.assertEqual(repeated["syncedCount"], 2)
            self.assertEqual(len(list_course_items(engine, course_id)), 2)
            self.assertEqual(len(list_course_sections(engine, course_id)), 2)

    def test_sync_failure_retains_metadata_for_retry_then_clears_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            course_id = self._course(engine)
            job_id, tracking_id = self._session(course_id)
            output = downloads / "recoverable.mp4"
            output.write_bytes(b"lesson")
            self._record_lesson(
                downloads,
                tracking_id,
                output,
                asset_id="601",
                title="Recoverable Lesson",
                chapter="Recovery",
                chapter_number=3,
                playlist_index=5,
                lecture_id="2001",
                attachments=[{
                    "providerAttachmentId": "udemy:asset:8001",
                    "title": "Recovery Notes",
                    "fileName": "recovery.pdf",
                    "assetType": "File",
                }],
            )

            with patch("course_download_sessions.sync_media_library", side_effect=RuntimeError("temporary media index failure")):
                with self.assertRaisesRegex(CourseDownloadSessionError, "temporary media index failure"):
                    sync_course_download_outputs(engine, job_id)

            self.assertEqual(tracked_output_paths(tracking_id), [output.resolve()])
            retained = tracked_course_metadata(tracking_id)[output.resolve()]
            self.assertEqual(retained["providerItemId"], "udemy:asset:601")
            self.assertEqual(retained["subtitleTracks"][0], {"language": "en", "kind": "manual"})
            self.assertEqual(retained["attachmentInventory"]["providerCourseId"], "udemy:course:456")
            self.assertEqual(
                retained["attachmentInventory"]["attachments"][0]["providerAttachmentId"],
                "udemy:asset:8001",
            )
            self.assertNotIn("PRIVATE", str(retained))

            recovered = sync_course_download_outputs(engine, job_id)
            self.assertEqual(recovered["syncState"], "synced")
            items = enrich_course_items(engine, list_course_items(engine, course_id))
            items = enrich_course_item_subtitles(engine, items)
            items = enrich_course_item_attachments(engine, items)
            self.assertEqual(items[0]["title"], "Recoverable Lesson")
            self.assertEqual(items[0]["sectionTitle"], "Recovery")
            self.assertEqual(items[0]["subtitleTracks"][1], {"language": "zh-CN", "kind": "automatic"})
            self.assertEqual(items[0]["attachments"][0]["title"], "Recovery Notes")
            self.assertEqual(tracked_output_paths(tracking_id), [])
            self.assertEqual(tracked_course_metadata(tracking_id), {})

    def test_failed_download_discard_clears_file_and_metadata_trackers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            course_id = self._course(engine)
            job_id, tracking_id = self._session(course_id)
            output = downloads / "partial.mp4"
            output.write_bytes(b"partial")
            self._record_lesson(
                downloads,
                tracking_id,
                output,
                asset_id="701",
                title="Partial Lesson",
                chapter="Partial",
                chapter_number=1,
                playlist_index=1,
                lecture_id="3001",
                attachments=[],
            )
            self.assertTrue(tracked_output_paths(tracking_id))
            self.assertTrue(tracked_course_metadata(tracking_id))

            self.assertEqual(discard_course_download_outputs(job_id), 1)
            self.assertEqual(tracked_output_paths(tracking_id), [])
            self.assertEqual(tracked_course_metadata(tracking_id), {})


if __name__ == "__main__":
    unittest.main()
