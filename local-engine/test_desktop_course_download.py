from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop_course_download as desktop_module
from desktop_course_download import DesktopCourseDownloadError, DesktopCourseDownloadService


class _Job:
    def __init__(self) -> None:
        self.job_id = "a" * 32
        self.state = "queued"

    def public_payload(self):
        return {
            "id": self.job_id,
            "sourceHost": "www.udemy.com",
            "state": self.state,
            "progress": 0.0,
            "detail": self.state,
            "fileName": "",
            "attempt": 1,
            "createdAt": "2026-09-05T00:00:00Z",
            "updatedAt": "2026-09-05T00:00:00Z",
        }


class _Runtime:
    def __init__(self) -> None:
        self.job = _Job()
        self.cancelled: list[str] = []
        self.stop_calls = 0

    def cancel(self, job_id):
        self.cancelled.append(str(job_id))
        self.job.state = "cancelled"
        return self.job

    def stop(self):
        self.stop_calls += 1


class _LearningApi:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create_course(self, payload):
        course = {
            "id": "b" * 32,
            "name": str(payload.get("name") or ""),
            "sourceUrl": str(payload.get("sourceUrl") or ""),
            "provider": str(payload.get("provider") or ""),
        }
        self.created.append(course)
        return {"course": course}

    def course_detail(self, course_id, *, item_limit=500):
        return {
            "course": {
                "id": str(course_id),
                "name": "Existing",
                "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
                "provider": "udemy",
            },
            "items": [],
            "itemLimit": item_limit,
        }

    def remove_course(self, course_id):
        return {"courseId": str(course_id), "deleted": True}


class _Coordinator:
    def __init__(self, runtime: _Runtime) -> None:
        self.runtime = runtime
        self.submissions: list[tuple[dict, str]] = []
        self.close_calls = 0

    def _session(self, course_id="b" * 32):
        return {
            "jobId": self.runtime.job.job_id,
            "courseId": course_id,
            "provider": "udemy",
            "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
            "syncState": "pending",
            "outputCount": 0,
            "syncedCount": 0,
            "syncError": "",
            "createdAt": "2026-09-05T00:00:00Z",
            "updatedAt": "2026-09-05T00:00:00Z",
        }

    def submit(self, plan, course_id):
        self.submissions.append((dict(plan), str(course_id)))
        return self.runtime.job, self._session(str(course_id))

    def status(self, job_id):
        if str(job_id) != self.runtime.job.job_id:
            raise RuntimeError("not found")
        return {"job": self.runtime.job.public_payload(), "session": self._session()}

    def sync_now(self, job_id):
        result = self.status(job_id)
        result["session"] = dict(result["session"], syncState="synced")
        return result

    def close(self):
        self.close_calls += 1


class DesktopCourseDownloadServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch(
            "course_providers.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_submit_returns_public_job_and_safe_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _Runtime()
            learning = _LearningApi()
            coordinator = _Coordinator(runtime)
            service = DesktopCourseDownloadService(
                Path(directory),
                runtime=runtime,
                learning_api=learning,
                coordinator=coordinator,
            )
            self.addCleanup(service.close)
            submitted = service.submit(
                "https://www.udemy.com/course/python-bootcamp/?couponCode=PRIVATE",
                browser="chrome",
                course_name="Python Desktop",
            )
            self.assertEqual(submitted["provider"], "udemy")
            self.assertEqual(submitted["course"]["name"], "Python Desktop")
            self.assertEqual(submitted["job"]["state"], "queued")
            self.assertEqual(submitted["session"]["syncState"], "pending")
            self.assertNotIn("enginePayload", submitted)
            self.assertNotIn("trackingId", str(submitted))
            self.assertNotIn("PRIVATE", str(submitted))
            plan = coordinator.submissions[0][0]
            self.assertEqual(plan["enginePayload"]["browser"], "chrome")
            self.assertNotIn("cookie", plan["enginePayload"])
            self.assertNotIn("httpHeaders", plan["enginePayload"])

    def test_status_cancel_and_sync_use_shared_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _Runtime()
            learning = _LearningApi()
            coordinator = _Coordinator(runtime)
            service = DesktopCourseDownloadService(
                Path(directory),
                runtime=runtime,
                learning_api=learning,
                coordinator=coordinator,
            )
            self.addCleanup(service.close)
            submitted = service.submit("https://www.udemy.com/course/python-bootcamp/")
            job_id = submitted["job"]["id"]
            self.assertEqual(service.status(job_id)["job"]["state"], "queued")
            cancelled = service.cancel(job_id)
            self.assertEqual(cancelled["job"]["state"], "cancelled")
            self.assertEqual(runtime.cancelled, [job_id])
            synced = service.sync_now(job_id)
            self.assertEqual(synced["session"]["syncState"], "synced")

    def test_injected_dependencies_are_not_owned_and_closed_service_rejects_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _Runtime()
            coordinator = _Coordinator(runtime)
            service = DesktopCourseDownloadService(
                Path(directory),
                runtime=runtime,
                learning_api=_LearningApi(),
                coordinator=coordinator,
            )
            service.close()
            service.close()
            self.assertEqual(runtime.stop_calls, 0)
            self.assertEqual(coordinator.close_calls, 0)
            with self.assertRaisesRegex(DesktopCourseDownloadError, "service is closed"):
                service.submit("https://www.udemy.com/course/python-bootcamp/")

    def test_owned_dependencies_close_coordinator_before_runtime_once(self) -> None:
        events: list[str] = []

        class OwnedRuntime:
            def __init__(self, root):
                self.root = root

            def stop(self):
                events.append("runtime.stop")

        class OwnedLearning:
            def __init__(self, root):
                self.root = root

        class OwnedCoordinator:
            def __init__(self, runtime, learning):
                self.runtime = runtime
                self.learning = learning

            def close(self):
                events.append("coordinator.close")

        with tempfile.TemporaryDirectory() as directory, patch.object(
            desktop_module, "HeadlessRuntime", OwnedRuntime
        ), patch.object(
            desktop_module, "HeadlessLearningApi", OwnedLearning
        ), patch.object(
            desktop_module, "CourseDownloadCoordinator", OwnedCoordinator
        ):
            service = DesktopCourseDownloadService(Path(directory))
            service.close()
            service.close()
        self.assertEqual(events, ["coordinator.close", "runtime.stop"])

    def test_owned_runtime_stops_if_learning_initialization_fails(self) -> None:
        events: list[str] = []

        class OwnedRuntime:
            def __init__(self, root):
                self.root = root

            def stop(self):
                events.append("runtime.stop")

        class BrokenLearning:
            def __init__(self, root):
                raise RuntimeError("learning init failed")

        with tempfile.TemporaryDirectory() as directory, patch.object(
            desktop_module, "HeadlessRuntime", OwnedRuntime
        ), patch.object(
            desktop_module, "HeadlessLearningApi", BrokenLearning
        ):
            with self.assertRaisesRegex(RuntimeError, "learning init failed"):
                DesktopCourseDownloadService(Path(directory))
        self.assertEqual(events, ["runtime.stop"])


if __name__ == "__main__":
    unittest.main()
