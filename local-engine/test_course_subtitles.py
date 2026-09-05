from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from course_subtitles import (
    CourseSubtitleError,
    course_item_subtitle_tracks,
    enrich_course_item_subtitles,
    ensure_course_subtitles,
    set_course_item_subtitle_tracks,
)
from course_workspace import add_media_to_course, create_course, delete_course
from media_library import list_media_items, sync_media_library


class CourseSubtitleTests(unittest.TestCase):
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

    def _item(self, engine, downloads: Path, course_id: str) -> str:
        output = downloads / "lesson.mp4"
        output.write_bytes(b"lesson")
        sync_media_library(
            engine,
            [
                {
                    "state": "completed",
                    "finishedAt": "2026-09-06T00:00:00Z",
                    "label": "lesson",
                    "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
                    "filePath": str(output),
                    "fileName": output.name,
                    "collectionMode": "course",
                }
            ],
        )
        media_id = next(
            item["id"]
            for item in list_media_items(engine, limit=100)
            if item["fileName"] == output.name
        )
        return add_media_to_course(engine, course_id, media_id)

    def test_tracks_are_bounded_structured_metadata_without_urls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            course_id = self._course(engine)
            item_id = self._item(engine, downloads, course_id)

            result = set_course_item_subtitle_tracks(
                engine,
                item_id,
                [
                    {"language": "en", "kind": "manual"},
                    {"language": "zh-CN", "kind": "automatic"},
                    {"language": "en", "kind": "manual"},
                ],
            )
            self.assertEqual(
                result["subtitleTracks"],
                [
                    {"language": "en", "kind": "manual"},
                    {"language": "zh-CN", "kind": "automatic"},
                ],
            )
            stored = course_item_subtitle_tracks(engine, [item_id])
            self.assertEqual(stored[item_id], result["subtitleTracks"])
            enriched = enrich_course_item_subtitles(engine, [{"id": item_id, "title": "Lesson"}])
            self.assertEqual(enriched[0]["subtitleTracks"], result["subtitleTracks"])
            self.assertNotIn("url", str(enriched).lower())
            self.assertNotIn("token", str(enriched).lower())

    def test_invalid_language_and_kind_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            course_id = self._course(engine)
            item_id = self._item(engine, downloads, course_id)

            with self.assertRaisesRegex(CourseSubtitleError, "invalid subtitle language"):
                set_course_item_subtitle_tracks(
                    engine,
                    item_id,
                    [{"language": "https://cdn.example/sub.vtt?sig=SECRET", "kind": "manual"}],
                )
            with self.assertRaisesRegex(CourseSubtitleError, "invalid subtitle kind"):
                set_course_item_subtitle_tracks(
                    engine,
                    item_id,
                    [{"language": "en", "kind": "signed-url"}],
                )

    def test_course_deletion_cascades_subtitle_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            course_id = self._course(engine)
            item_id = self._item(engine, downloads, course_id)
            set_course_item_subtitle_tracks(
                engine,
                item_id,
                [{"language": "en", "kind": "manual"}],
            )
            self.assertEqual(ensure_course_subtitles(engine)["tracks"], 1)
            self.assertTrue(delete_course(engine, course_id))
            self.assertEqual(ensure_course_subtitles(engine)["tracks"], 0)
            self.assertEqual(course_item_subtitle_tracks(engine, [item_id]), {})


if __name__ == "__main__":
    unittest.main()
