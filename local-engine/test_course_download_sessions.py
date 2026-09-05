from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import headless_service
from course_download_sessions import (
    CourseDownloadSessionError,
    course_download_session,
    register_course_download_session,
    remove_course_download_session,
    sync_course_download_outputs,
)
from course_workspace import create_course, list_course_items
from headless_browser_cookies import install_headless_browser_cookie_support
from headless_output_tracking import (
    install_headless_output_tracking,
    new_output_tracking_id,
    tracked_output_paths,
)
from media_library import list_media_items


class CourseDownloadSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_headless_browser_cookie_support()
        install_headless_output_tracking()

    def _engine(self, root: Path):
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        downloads.mkdir()
        state.mkdir()
        data.mkdir()

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

    def _record_outputs(self, downloads: Path, tracking_id: str, *outputs: Path) -> None:
        options = headless_service._download_options(
            {"browser": "chrome", "_outputTrackingId": tracking_id},
            downloads,
            lambda _event: None,
        )
        self.assertEqual(options.get("cookiesfrombrowser"), ("chrome", None, None, None))
        hooks = options.get("post_hooks") or []
        self.assertEqual(len(hooks), 1)
        for output in outputs:
            hooks[0](str(output))

    def test_register_public_payload_hides_internal_tracking_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, _downloads = self._engine(root)
            course_id = self._course(engine)
            job_id = uuid.uuid4().hex
            tracking_id = new_output_tracking_id()
            self.addCleanup(remove_course_download_session, job_id)
            session = register_course_download_session(
                job_id=job_id,
                tracking_id=tracking_id,
                course_id=course_id,
                provider="udemy",
                source_url="https://www.udemy.com/course/python-bootcamp/?couponCode=SECRET#tracking",
            )
            self.assertEqual(session["jobId"], job_id)
            self.assertEqual(session["courseId"], course_id)
            self.assertEqual(session["syncState"], "pending")
            self.assertEqual(session["sourceUrl"], "https://www.udemy.com/course/python-bootcamp/")
            self.assertNotIn("SECRET", str(session))
            self.assertNotIn("trackingId", session)
            self.assertNotIn("outputPaths", session)

    def test_registration_is_idempotent_for_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, _downloads = self._engine(root)
            course_id = self._course(engine)
            job_id = uuid.uuid4().hex
            tracking_id = new_output_tracking_id()
            self.addCleanup(remove_course_download_session, job_id)
            first = register_course_download_session(
                job_id=job_id,
                tracking_id=tracking_id,
                course_id=course_id,
                provider="udemy",
                source_url="https://www.udemy.com/course/python-bootcamp/?couponCode=ONE",
            )
            second = register_course_download_session(
                job_id=job_id,
                tracking_id=tracking_id,
                course_id=course_id,
                provider="udemy",
                source_url="https://www.udemy.com/course/python-bootcamp/?couponCode=TWO#fragment",
            )
            self.assertEqual(first["jobId"], second["jobId"])
            self.assertEqual(first["sourceUrl"], second["sourceUrl"])
            with self.assertRaises(CourseDownloadSessionError):
                register_course_download_session(
                    job_id=job_id,
                    tracking_id=uuid.uuid4().hex,
                    course_id=course_id,
                    provider="udemy",
                    source_url="https://www.udemy.com/course/python-bootcamp/",
                )

    def test_sync_indexes_outputs_and_preserves_course_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            course_id = self._course(engine)
            first = downloads / "01 Introduction.mp4"
            second = downloads / "02 Variables.mkv"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            job_id = uuid.uuid4().hex
            tracking_id = new_output_tracking_id()
            self.addCleanup(remove_course_download_session, job_id)
            register_course_download_session(
                job_id=job_id,
                tracking_id=tracking_id,
                course_id=course_id,
                provider="udemy",
                source_url="https://www.udemy.com/course/python-bootcamp/?couponCode=SECRET",
            )
            self._record_outputs(downloads, tracking_id, first, second)

            synced = sync_course_download_outputs(engine, job_id)
            self.assertEqual(synced["syncState"], "synced")
            self.assertEqual(synced["outputCount"], 2)
            self.assertEqual(synced["syncedCount"], 2)
            self.assertEqual(tracked_output_paths(tracking_id), [])

            media = list_media_items(engine, limit=10)
            self.assertEqual(len(media), 2)
            self.assertTrue(all(item["sourceHost"] == "www.udemy.com" for item in media))
            self.assertTrue(all("SECRET" not in item["sourceUrl"] for item in media))
            items = list_course_items(engine, course_id)
            self.assertEqual([item["title"] for item in items], ["01 Introduction", "02 Variables"])

            repeated = sync_course_download_outputs(engine, job_id)
            self.assertEqual(repeated["syncedCount"], 2)
            self.assertEqual(len(list_course_items(engine, course_id)), 2)

    def test_sync_without_outputs_is_retryable_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, _downloads = self._engine(root)
            course_id = self._course(engine)
            job_id = uuid.uuid4().hex
            tracking_id = new_output_tracking_id()
            self.addCleanup(remove_course_download_session, job_id)
            register_course_download_session(
                job_id=job_id,
                tracking_id=tracking_id,
                course_id=course_id,
                provider="udemy",
                source_url="https://www.udemy.com/course/python-bootcamp/",
            )
            with self.assertRaisesRegex(CourseDownloadSessionError, "no final course output"):
                sync_course_download_outputs(engine, job_id)
            session = course_download_session(job_id)
            self.assertIsNotNone(session)
            self.assertEqual(session["syncState"], "failed")
            self.assertIn("no final course output", session["syncError"])

    def test_remove_session_clears_tracked_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, downloads = self._engine(root)
            course_id = self._course(engine)
            output = downloads / "lesson.mp4"
            output.write_bytes(b"lesson")
            job_id = uuid.uuid4().hex
            tracking_id = new_output_tracking_id()
            register_course_download_session(
                job_id=job_id,
                tracking_id=tracking_id,
                course_id=course_id,
                provider="udemy",
                source_url="https://www.udemy.com/course/python-bootcamp/",
            )
            self._record_outputs(downloads, tracking_id, output)
            self.assertEqual(len(tracked_output_paths(tracking_id)), 1)
            self.assertTrue(remove_course_download_session(job_id))
            self.assertEqual(tracked_output_paths(tracking_id), [])
            self.assertIsNone(course_download_session(job_id))


if __name__ == "__main__":
    unittest.main()
