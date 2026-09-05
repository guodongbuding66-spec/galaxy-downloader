from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from course_structure import (
    CourseStructureError,
    course_item_metadata,
    enrich_course_items,
    ensure_course_structure,
    list_course_sections,
    set_course_item_metadata,
    upsert_course_section,
)
from course_workspace import (
    SCHEMA_VERSION,
    add_media_to_course,
    course_database_path,
    create_course,
    delete_course,
    list_course_items,
)
from media_library import list_media_items, sync_media_library


class CourseStructureTests(unittest.TestCase):
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

    def _course(self, engine, name: str, slug: str) -> str:
        with patch(
            "course_workspace.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        ):
            return create_course(
                engine,
                name,
                f"https://www.udemy.com/course/{slug}/",
                provider="udemy",
            )["id"]

    def _course_item(self, engine, downloads: Path, course_id: str, name: str) -> str:
        media = downloads / name
        media.write_bytes(b"lesson")
        sync_media_library(
            engine,
            [
                {
                    "state": "completed",
                    "finishedAt": "2026-09-05T00:00:00Z",
                    "label": media.stem,
                    "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
                    "filePath": str(media),
                    "fileName": media.name,
                    "collectionMode": "course",
                }
            ],
        )
        media_id = next(
            item["id"]
            for item in list_media_items(engine, limit=100)
            if item["fileName"] == media.name
        )
        return add_media_to_course(engine, course_id, media_id)

    def test_structure_extension_does_not_change_base_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, _downloads = self._engine(root)
            summary = ensure_course_structure(engine)
            self.assertEqual(summary["schemaVersion"], 1)
            with sqlite3.connect(course_database_path(engine)) as connection:
                base = connection.execute(
                    "SELECT value FROM learning_meta WHERE key='schema_version'"
                ).fetchone()[0]
                extension = connection.execute(
                    "SELECT value FROM learning_structure_meta WHERE key='schema_version'"
                ).fetchone()[0]
            self.assertEqual(int(base), SCHEMA_VERSION)
            self.assertEqual(int(extension), 1)

    def test_sections_and_provider_metadata_enrich_existing_course_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            course_id = self._course(engine, "Python Bootcamp", "python-bootcamp")
            first_item = self._course_item(engine, downloads, course_id, "01-file-name.mp4")
            second_item = self._course_item(engine, downloads, course_id, "02-file-name.mp4")

            intro = upsert_course_section(
                engine,
                course_id,
                provider_section_id="chapter:1",
                title="Getting Started",
                position=1,
            )
            basics = upsert_course_section(
                engine,
                course_id,
                provider_section_id="chapter:2",
                title="Python Basics",
                position=2,
            )
            set_course_item_metadata(
                engine,
                first_item,
                section_id=intro["id"],
                provider_item_id="lecture:101",
                provider_title="Welcome to the Course",
                provider_position=1,
            )
            set_course_item_metadata(
                engine,
                second_item,
                section_id=basics["id"],
                provider_item_id="lecture:102",
                provider_title="Variables and Types",
                provider_position=2,
            )

            sections = list_course_sections(engine, course_id)
            self.assertEqual([section["title"] for section in sections], ["Getting Started", "Python Basics"])
            items = enrich_course_items(engine, list_course_items(engine, course_id))
            self.assertEqual([item["title"] for item in items], ["Welcome to the Course", "Variables and Types"])
            self.assertEqual(items[0]["sectionTitle"], "Getting Started")
            self.assertEqual(items[0]["providerItemId"], "lecture:101")
            self.assertEqual(items[1]["sectionPosition"], 2)

    def test_section_upsert_is_idempotent_by_provider_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, _downloads = self._engine(root)
            course_id = self._course(engine, "Python Bootcamp", "python-bootcamp")
            first = upsert_course_section(
                engine,
                course_id,
                provider_section_id="chapter:1",
                title="Old title",
                position=1,
            )
            second = upsert_course_section(
                engine,
                course_id,
                provider_section_id="chapter:1",
                title="Updated title",
                position=2,
            )
            self.assertEqual(first["id"], second["id"])
            sections = list_course_sections(engine, course_id)
            self.assertEqual(len(sections), 1)
            self.assertEqual(sections[0]["title"], "Updated title")
            self.assertEqual(sections[0]["position"], 2)

    def test_item_cannot_reference_section_from_another_course(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            first_course = self._course(engine, "First", "first")
            second_course = self._course(engine, "Second", "second")
            item_id = self._course_item(engine, downloads, first_course, "lesson.mp4")
            other_section = upsert_course_section(
                engine,
                second_course,
                provider_section_id="chapter:1",
                title="Other",
                position=1,
            )
            with self.assertRaisesRegex(CourseStructureError, "different course"):
                set_course_item_metadata(
                    engine,
                    item_id,
                    section_id=other_section["id"],
                    provider_item_id="lecture:1",
                    provider_title="Wrong binding",
                    provider_position=1,
                )

    def test_course_deletion_cascades_structure_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            course_id = self._course(engine, "Python Bootcamp", "python-bootcamp")
            item_id = self._course_item(engine, downloads, course_id, "lesson.mp4")
            section = upsert_course_section(
                engine,
                course_id,
                provider_section_id="chapter:1",
                title="Intro",
                position=1,
            )
            set_course_item_metadata(
                engine,
                item_id,
                section_id=section["id"],
                provider_item_id="lecture:1",
                provider_title="Intro lesson",
                provider_position=1,
            )
            self.assertTrue(course_item_metadata(engine, [item_id]))
            self.assertTrue(delete_course(engine, course_id))
            self.assertEqual(ensure_course_structure(engine)["sections"], 0)
            self.assertEqual(course_item_metadata(engine, [item_id]), {})

    def test_provider_identifiers_are_bounded_and_not_free_form(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, _downloads = self._engine(root)
            course_id = self._course(engine, "Python Bootcamp", "python-bootcamp")
            with self.assertRaisesRegex(CourseStructureError, "invalid provider section id"):
                upsert_course_section(
                    engine,
                    course_id,
                    provider_section_id="../../chapter?token=secret",
                    title="Unsafe",
                    position=1,
                )


if __name__ == "__main__":
    unittest.main()
