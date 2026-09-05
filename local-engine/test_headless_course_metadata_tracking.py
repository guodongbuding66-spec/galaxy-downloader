from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import headless_service
from headless_course_metadata_tracking import (
    clear_course_metadata_tracking,
    install_headless_course_metadata_tracking,
    tracked_course_metadata,
)
from headless_output_tracking import install_headless_output_tracking, new_output_tracking_id


class HeadlessCourseMetadataTrackingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_headless_output_tracking()
        install_headless_course_metadata_tracking()

    def _options(self, root: Path, tracking_id: str):
        return headless_service._download_options(
            {"_outputTrackingId": tracking_id},
            root,
            lambda _event: None,
        )

    def test_movefiles_finished_captures_only_safe_udemy_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "lesson.mp4"
            output.write_bytes(b"lesson")
            tracking_id = new_output_tracking_id()
            self.addCleanup(clear_course_metadata_tracking, tracking_id)
            options = self._options(root, tracking_id)
            hooks = options.get("postprocessor_hooks") or []
            self.assertEqual(len(hooks), 1)

            hooks[0](
                {
                    "status": "finished",
                    "postprocessor": "MoveFiles",
                    "info_dict": {
                        "filepath": str(output),
                        "extractor_key": "Udemy",
                        "id": "9001",
                        "title": "Variables and Types",
                        "chapter": "Python Basics",
                        "chapter_number": 2,
                        "playlist_index": 7,
                        "url": "https://cdn.example/video.mp4?token=SECRET",
                        "webpage_url": "https://www.udemy.com/course/test/?couponCode=SECRET",
                        "http_headers": {"Authorization": "Bearer SECRET"},
                        "cookie": "session=SECRET",
                        "subtitles": {"en": [{"url": "https://cdn.example/sub.vtt?sig=SECRET"}]},
                        "description": "SECRET should never be retained",
                    },
                }
            )

            tracked = tracked_course_metadata(tracking_id)
            self.assertEqual(
                tracked,
                {
                    output.resolve(): {
                        "provider": "udemy",
                        "providerItemId": "udemy:asset:9001",
                        "providerTitle": "Variables and Types",
                        "providerPosition": 7,
                        "sectionTitle": "Python Basics",
                        "sectionPosition": 2,
                    }
                },
            )
            self.assertNotIn("SECRET", str(tracked))
            self.assertNotIn("url", str(tracked).lower())
            self.assertNotIn("cookie", str(tracked).lower())
            self.assertNotIn("authorization", str(tracked).lower())

    def test_ignores_non_final_non_udemy_and_outside_root_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_directory:
            root = Path(directory)
            output = root / "lesson.mp4"
            output.write_bytes(b"lesson")
            outside = Path(outside_directory) / "outside.mp4"
            outside.write_bytes(b"outside")
            tracking_id = new_output_tracking_id()
            self.addCleanup(clear_course_metadata_tracking, tracking_id)
            hook = (self._options(root, tracking_id).get("postprocessor_hooks") or [])[0]

            base = {
                "extractor_key": "Udemy",
                "id": "101",
                "title": "Lesson",
                "chapter": "Intro",
                "chapter_number": 1,
                "playlist_index": 1,
            }
            hook({"status": "started", "postprocessor": "MoveFiles", "info_dict": {**base, "filepath": str(output)}})
            hook({"status": "finished", "postprocessor": "FFmpegVideoConvertor", "info_dict": {**base, "filepath": str(output)}})
            hook(
                {
                    "status": "finished",
                    "postprocessor": "MoveFiles",
                    "info_dict": {**base, "filepath": str(output), "extractor_key": "Youtube"},
                }
            )
            hook({"status": "finished", "postprocessor": "MoveFiles", "info_dict": {**base, "filepath": str(outside)}})
            self.assertEqual(tracked_course_metadata(tracking_id), {})

    def test_missing_chapter_is_kept_as_unsectioned_safe_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "lesson.mp4"
            output.write_bytes(b"lesson")
            tracking_id = new_output_tracking_id()
            self.addCleanup(clear_course_metadata_tracking, tracking_id)
            hook = (self._options(root, tracking_id).get("postprocessor_hooks") or [])[0]
            hook(
                {
                    "status": "finished",
                    "postprocessor": "MoveFiles",
                    "info_dict": {
                        "filepath": str(output),
                        "extractor": "udemy",
                        "id": "202",
                        "title": "Standalone Lesson",
                        "playlist_index": 3,
                    },
                }
            )
            metadata = tracked_course_metadata(tracking_id)[output.resolve()]
            self.assertEqual(metadata["providerItemId"], "udemy:asset:202")
            self.assertEqual(metadata["providerTitle"], "Standalone Lesson")
            self.assertEqual(metadata["providerPosition"], 3)
            self.assertEqual(metadata["sectionTitle"], "")
            self.assertEqual(metadata["sectionPosition"], 0)


if __name__ == "__main__":
    unittest.main()
