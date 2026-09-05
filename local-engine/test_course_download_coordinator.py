from __future__ import annotations

import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import headless_service
from course_download_coordinator import CourseDownloadCoordinator, CourseDownloadCoordinatorError
from course_workspace import create_course, list_course_items
from headless_learning_api import HeadlessLearningApi, HeadlessLearningContext
from headless_output_tracking import install_headless_output_tracking
from headless_service import EventBroker
from media_library import list_media_items


class _Job:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.state = "queued"
        self.detail = ""

    def public_payload(self) -> dict:
        return {
            "id": self.job_id,
            "sourceHost": "www.udemy.com",
            "state": self.state,
            "progress": 100.0 if self.state == "completed" else 0.0,
            "detail": self.detail,
            "fileName": "",
            "attempt": 1,
            "createdAt": "2026-09-05T00:00:00Z",
            "updatedAt": "2026-09-05T00:00:00Z",
        }


class _Runtime:
    def __init__(self, download_root: Path) -> None:
        self.download_root = download_root
        self.events = EventBroker()
        self.jobs: dict[str, _Job] = {}
        self.submissions: list[dict] = []
        self.submit_error: Exception | None = None

    def submit(self, payload: dict):
        if self.submit_error is not None:
            raise self.submit_error
        job = _Job(uuid.uuid4().hex)
        self.jobs[job.job_id] = job
        self.submissions.append(dict(payload))
        self.events.publish({"event": "job.queued", "job": job.public_payload()})
        return job

    def get(self, job_id: object):
        return self.jobs.get(str(job_id or "").strip().lower())

    def cancel(self, job_id: object):
        job = self.get(job_id)
        if job is None:
            raise RuntimeError("job not found")
        job.state = "cancelled"
        job.detail = "cancelled"
        self.events.publish({"event": "job.updated", "job": job.public_payload()})
        return job

    def terminal(self, job_id: str, state: str, detail: str = "") -> None:
        job = self.jobs[job_id]
        job.state = state
        job.detail = detail or state
        self.events.publish({"event": "job.updated", "job": job.public_payload()})


class CourseDownloadCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_headless_output_tracking()

    def _learning(self, root: Path):
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        program = root / "program"
        for target in (downloads, state, data, program):
            target.mkdir()
        context = HeadlessLearningContext(program, data, state, downloads)
        api = HeadlessLearningApi(downloads, context=context)
        with patch(
            "course_workspace.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        ):
            course_id = create_course(
                context,
                "Python Bootcamp",
                "https://www.udemy.com/course/python-bootcamp/",
                provider="udemy",
            )["id"]
        return api, course_id, downloads

    def _plan(self) -> dict:
        return {
            "provider": "udemy",
            "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
            "enginePayload": {
                "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
                "browser": "chrome",
                "collectionMode": "all",
                "includeAudio": True,
            },
        }

    def _wait_state(self, coordinator: CourseDownloadCoordinator, job_id: str, state: str) -> dict:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            value = coordinator.status(job_id)
            session = value.get("session") or {}
            if session.get("syncState") == state:
                return value
            time.sleep(0.02)
        self.fail(f"course download session did not reach {state}")

    def _record_outputs(self, runtime: _Runtime, *outputs: Path) -> None:
        payload = runtime.submissions[-1]
        options = headless_service._download_options(
            payload,
            runtime.download_root,
            lambda _event: None,
        )
        hooks = options.get("post_hooks") or []
        self.assertEqual(len(hooks), 1)
        for output in outputs:
            hooks[0](str(output))

    def test_completed_job_auto_syncs_outputs_to_course(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            learning_api, course_id, downloads = self._learning(root)
            runtime = _Runtime(downloads)
            coordinator = CourseDownloadCoordinator(runtime, learning_api)
            self.addCleanup(coordinator.close)

            job, session = coordinator.submit(self._plan(), course_id)
            self.assertEqual(session["syncState"], "pending")
            self.assertNotIn("trackingId", session)
            self.assertTrue(runtime.submissions[-1].get("_outputTrackingId"))

            first = downloads / "01 Introduction.mp4"
            second = downloads / "02 Variables.mkv"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            self._record_outputs(runtime, first, second)
            runtime.terminal(job.job_id, "completed")

            final = self._wait_state(coordinator, job.job_id, "synced")
            self.assertEqual(final["session"]["outputCount"], 2)
            self.assertEqual(final["session"]["syncedCount"], 2)
            self.assertEqual(len(list_media_items(learning_api.context, limit=10)), 2)
            items = list_course_items(learning_api.context, course_id)
            self.assertEqual([item["title"] for item in items], ["01 Introduction", "02 Variables"])

    def test_failed_job_marks_session_failed_without_course_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            learning_api, course_id, downloads = self._learning(root)
            runtime = _Runtime(downloads)
            coordinator = CourseDownloadCoordinator(runtime, learning_api)
            self.addCleanup(coordinator.close)

            job, _session = coordinator.submit(self._plan(), course_id)
            runtime.terminal(job.job_id, "failed", "authorized course request failed")
            final = self._wait_state(coordinator, job.job_id, "failed")
            self.assertIn("authorized course request failed", final["session"]["syncError"])
            self.assertEqual(list_course_items(learning_api.context, course_id), [])

    def test_cancelled_job_marks_session_failed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            learning_api, course_id, downloads = self._learning(root)
            runtime = _Runtime(downloads)
            coordinator = CourseDownloadCoordinator(runtime, learning_api)
            self.addCleanup(coordinator.close)

            job, _session = coordinator.submit(self._plan(), course_id)
            runtime.cancel(job.job_id)
            final = self._wait_state(coordinator, job.job_id, "failed")
            self.assertEqual(final["job"]["state"], "cancelled")

    def test_manual_sync_rejects_non_completed_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            learning_api, course_id, downloads = self._learning(root)
            runtime = _Runtime(downloads)
            coordinator = CourseDownloadCoordinator(runtime, learning_api)
            self.addCleanup(coordinator.close)
            job, _session = coordinator.submit(self._plan(), course_id)
            with self.assertRaisesRegex(CourseDownloadCoordinatorError, "cannot sync from state queued"):
                coordinator.sync_now(job.job_id)


if __name__ == "__main__":
    unittest.main()
