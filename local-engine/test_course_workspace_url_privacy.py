from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from course_workspace import SCHEMA_VERSION, course_database_path, create_course, list_courses


class CourseWorkspaceUrlPrivacyTests(unittest.TestCase):
    def _engine(self, root: Path):
        state = root / "state"
        data = root / "data"
        downloads = root / "downloads"
        for target in (state, data, downloads):
            target.mkdir()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return state

            @staticmethod
            def data_dir() -> Path:
                return data

            @staticmethod
            def default_download_dir() -> Path:
                return downloads

        return Engine

    def test_create_course_strips_query_and_fragment_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = self._engine(Path(directory))
            source = "https://www.udemy.com/course/python/?couponCode=PRIVATE&token=SECRET#intro"
            expected = "https://www.udemy.com/course/python/"
            with patch("course_workspace.validated_public_http_url", side_effect=lambda value: str(value)):
                created = create_course(engine, "Python", source, provider="udemy")
                listed = list_courses(engine, limit=10)

            self.assertEqual(created["sourceUrl"], expected)
            self.assertEqual(listed[0]["sourceUrl"], expected)
            self.assertNotIn("PRIVATE", repr(listed))
            self.assertNotIn("SECRET", repr(listed))

            with sqlite3.connect(course_database_path(engine)) as connection:
                stored_source = connection.execute(
                    "SELECT source_url FROM courses WHERE id=?", (created["id"],)
                ).fetchone()[0]
                schema_version = connection.execute(
                    "SELECT value FROM learning_meta WHERE key='schema_version'"
                ).fetchone()[0]
            self.assertEqual(stored_source, expected)
            self.assertEqual(int(schema_version), SCHEMA_VERSION)

    def test_validation_still_runs_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = self._engine(Path(directory))
            with patch(
                "course_workspace.validated_public_http_url",
                side_effect=RuntimeError("blocked URL"),
            ) as validator:
                with self.assertRaisesRegex(RuntimeError, "blocked URL"):
                    create_course(engine, "Blocked", "http://127.0.0.1/private")
            validator.assert_called_once_with("http://127.0.0.1/private")
            self.assertEqual(list_courses(engine, limit=10), [])

    def test_empty_source_remains_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = self._engine(Path(directory))
            with patch("course_workspace.validated_public_http_url") as validator:
                created = create_course(engine, "Offline Course", "")
            validator.assert_not_called()
            self.assertEqual(created["sourceUrl"], "")


if __name__ == "__main__":
    unittest.main()
