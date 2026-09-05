from __future__ import annotations

import unittest
from unittest.mock import patch

from course_download_coordinator import CourseDownloadCoordinatorError
from headless_service import HeadlessServiceError
from managed_course_download import build_managed_course_plan, submit_managed_course_download


class _Job:
    job_id = "a" * 32

    def public_payload(self):
        return {"id": self.job_id, "state": "queued"}


class _LearningApi:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.removed: list[str] = []
        self.existing_id = "c" * 32
        self.existing_provider = "udemy"
        self.existing_source = "https://www.udemy.com/course/python-bootcamp/?couponCode=OLD"

    def create_course(self, payload):
        course = {
            "id": "b" * 32,
            "name": str(payload.get("name") or ""),
            "sourceUrl": str(payload.get("sourceUrl") or ""),
            "provider": str(payload.get("provider") or ""),
        }
        self.created.append(dict(course))
        return {"course": course}

    def course_detail(self, course_id, *, item_limit=500):
        if str(course_id) != self.existing_id:
            raise RuntimeError("course not found")
        return {
            "course": {
                "id": self.existing_id,
                "name": "Existing Course",
                "sourceUrl": self.existing_source,
                "provider": self.existing_provider,
            },
            "items": [],
            "itemLimit": item_limit,
        }

    def remove_course(self, course_id):
        self.removed.append(str(course_id))
        return {"courseId": str(course_id), "deleted": True}


class _Coordinator:
    def __init__(self) -> None:
        self.job = _Job()
        self.submissions: list[tuple[dict, str]] = []
        self.error: Exception | None = None

    def submit(self, plan, course_id):
        if self.error is not None:
            raise self.error
        self.submissions.append((dict(plan), str(course_id)))
        return self.job, {
            "jobId": self.job.job_id,
            "courseId": str(course_id),
            "provider": plan["provider"],
            "sourceUrl": plan["sourceUrl"],
            "syncState": "pending",
        }


class ManagedCourseDownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch(
            "course_providers.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _plan(self, **kwargs):
        return build_managed_course_plan(
            "https://www.udemy.com/course/python-bootcamp/?couponCode=PRIVATE#overview",
            **kwargs,
        )

    def test_safe_plan_uses_browser_source_without_raw_credentials(self) -> None:
        plan = self._plan(browser="chrome", include_subtitles=True)
        self.assertEqual(plan["provider"], "udemy")
        engine = plan["enginePayload"]
        self.assertEqual(engine["browser"], "chrome")
        self.assertTrue(engine["includeSubtitle"])
        self.assertNotIn("cookie", engine)
        self.assertNotIn("cookieFile", engine)
        self.assertNotIn("httpHeaders", engine)
        self.assertNotIn("Authorization", str(engine))

    def test_auto_creates_course_and_submits_same_safe_plan(self) -> None:
        learning = _LearningApi()
        coordinator = _Coordinator()
        plan = self._plan(browser="firefox")
        submitted = submit_managed_course_download(learning, coordinator, plan)
        self.assertEqual(submitted["provider"], "udemy")
        self.assertEqual(submitted["course"]["id"], "b" * 32)
        self.assertEqual(submitted["course"]["name"], "python bootcamp")
        self.assertEqual(submitted["job"].job_id, "a" * 32)
        self.assertEqual(coordinator.submissions[0][0], plan)
        self.assertEqual(coordinator.submissions[0][1], "b" * 32)

    def test_explicit_course_name_is_bounded_and_normalized(self) -> None:
        learning = _LearningApi()
        coordinator = _Coordinator()
        submit_managed_course_download(
            learning,
            coordinator,
            self._plan(),
            course_name="  My   Python   Course  ",
        )
        self.assertEqual(learning.created[0]["name"], "My Python Course")

    def test_existing_course_binding_ignores_query_and_fragment(self) -> None:
        learning = _LearningApi()
        coordinator = _Coordinator()
        submitted = submit_managed_course_download(
            learning,
            coordinator,
            self._plan(),
            course_id=learning.existing_id,
        )
        self.assertEqual(submitted["course"]["id"], learning.existing_id)
        self.assertEqual(learning.created, [])
        self.assertEqual(coordinator.submissions[0][1], learning.existing_id)

    def test_existing_course_rejects_provider_mismatch(self) -> None:
        learning = _LearningApi()
        learning.existing_provider = "generic"
        coordinator = _Coordinator()
        with self.assertRaisesRegex(CourseDownloadCoordinatorError, "provider does not match"):
            submit_managed_course_download(
                learning,
                coordinator,
                self._plan(),
                course_id=learning.existing_id,
            )
        self.assertEqual(coordinator.submissions, [])

    def test_existing_course_rejects_different_source(self) -> None:
        learning = _LearningApi()
        learning.existing_source = "https://www.udemy.com/course/another-course/"
        coordinator = _Coordinator()
        with self.assertRaisesRegex(CourseDownloadCoordinatorError, "source does not match"):
            submit_managed_course_download(
                learning,
                coordinator,
                self._plan(),
                course_id=learning.existing_id,
            )
        self.assertEqual(coordinator.submissions, [])

    def test_new_course_is_rolled_back_when_queue_submit_fails(self) -> None:
        learning = _LearningApi()
        coordinator = _Coordinator()
        coordinator.error = HeadlessServiceError("download queue is full")
        with self.assertRaisesRegex(HeadlessServiceError, "queue is full"):
            submit_managed_course_download(learning, coordinator, self._plan())
        self.assertEqual(learning.removed, ["b" * 32])


if __name__ == "__main__":
    unittest.main()
