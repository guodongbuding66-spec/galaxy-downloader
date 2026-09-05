from __future__ import annotations

import unittest
from unittest.mock import patch

from course_download_coordinator import CourseDownloadCoordinatorError
from headless_course_providers_http import HeadlessCourseProvidersHttpMixin
from headless_learning_api import HeadlessLearningNotFoundError
from headless_service import HeadlessServiceError


class _Job:
    job_id = "a" * 32

    def public_payload(self):
        return {
            "id": self.job_id,
            "sourceHost": "www.udemy.com",
            "state": "queued",
            "progress": 0.0,
            "detail": "",
            "fileName": "",
            "attempt": 1,
            "createdAt": "2026-09-05T00:00:00Z",
            "updatedAt": "2026-09-05T00:00:00Z",
        }


class _LearningApi:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.removed: list[str] = []
        self.existing_id = "c" * 32

    def create_course(self, payload):
        course = {
            "id": "b" * 32,
            "name": str(payload.get("name") or ""),
            "sourceUrl": str(payload.get("sourceUrl") or ""),
            "provider": str(payload.get("provider") or "generic"),
        }
        self.created.append(course)
        return {"course": course}

    def course_detail(self, course_id, *, item_limit=500):
        if course_id != self.existing_id:
            raise HeadlessLearningNotFoundError("course not found", code="LEARNING_COURSE_NOT_FOUND")
        return {
            "course": {
                "id": self.existing_id,
                "name": "Existing Course",
                "sourceUrl": "https://www.udemy.com/course/existing-course/",
                "provider": "udemy",
            },
            "items": [],
            "itemLimit": item_limit,
        }

    def remove_course(self, course_id):
        self.removed.append(str(course_id))
        return {"courseId": str(course_id), "deleted": True}


class _Coordinator:
    def __init__(self) -> None:
        self.submissions: list[tuple[dict, str]] = []
        self.error: Exception | None = None
        self.job = _Job()

    def submit(self, plan, course_id):
        if self.error is not None:
            raise self.error
        self.submissions.append((dict(plan), str(course_id)))
        return self.job, {
            "jobId": self.job.job_id,
            "courseId": str(course_id),
            "provider": str(plan.get("provider") or ""),
            "sourceUrl": str(plan.get("sourceUrl") or ""),
            "syncState": "pending",
            "outputCount": 0,
            "syncedCount": 0,
            "syncError": "",
            "createdAt": "2026-09-05T00:00:00Z",
            "updatedAt": "2026-09-05T00:00:00Z",
        }

    def status(self, job_id):
        if str(job_id) != self.job.job_id:
            raise CourseDownloadCoordinatorError("course download session not found")
        return {
            "job": self.job.public_payload(),
            "session": {
                "jobId": self.job.job_id,
                "courseId": "b" * 32,
                "provider": "udemy",
                "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
                "syncState": "pending",
                "outputCount": 0,
                "syncedCount": 0,
                "syncError": "",
                "createdAt": "2026-09-05T00:00:00Z",
                "updatedAt": "2026-09-05T00:00:00Z",
            },
        }


class _Server:
    def __init__(self, coordinator) -> None:
        self.course_download_coordinator = coordinator


class _FallbackHandler:
    def __init__(self) -> None:
        self.path = "/"
        self.authorized = True
        self.payload = {}
        self.response = None
        self.fallback_get = False
        self.fallback_post = False
        self.learning_api = _LearningApi()
        self.coordinator = _Coordinator()
        self.server = _Server(self.coordinator)

    def _authorized(self) -> bool:
        return self.authorized

    def _read_json(self):
        return self.payload

    def _json(self, status, payload) -> None:
        self.response = (status, payload)

    def do_GET(self) -> None:  # noqa: N802
        self.fallback_get = True

    def do_POST(self) -> None:  # noqa: N802
        self.fallback_post = True


class _Handler(HeadlessCourseProvidersHttpMixin, _FallbackHandler):
    pass


class HeadlessCourseProviderHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch(
            "course_providers.validated_public_http_url",
            side_effect=lambda value: str(value or "").strip(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_catalog(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers"
        handler.do_GET()
        self.assertEqual(handler.response[0], 200)
        self.assertEqual(handler.response[1]["providers"][0]["id"], "udemy")

    def test_get_download_status(self) -> None:
        handler = _Handler()
        handler.path = f"/v1/learning/providers/downloads/{handler.coordinator.job.job_id}"
        handler.do_GET()
        status, payload = handler.response
        self.assertEqual(status, 200)
        self.assertEqual(payload["session"]["syncState"], "pending")
        self.assertEqual(payload["job"]["state"], "queued")

    def test_get_download_status_maps_missing_session_to_404(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/downloads/" + "d" * 32
        handler.do_GET()
        status, payload = handler.response
        self.assertEqual(status, 404)
        self.assertEqual(payload["code"], "LEARNING_COURSE_DOWNLOAD_NOT_FOUND")

    def test_get_requires_authorization(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers"
        handler.authorized = False
        handler.do_GET()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))

    def test_post_resolves_udemy_plan_without_submitting(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/resolve"
        handler.payload = {
            "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
            "browser": "chrome",
            "includeSubtitles": True,
        }
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 200)
        self.assertEqual(payload["plan"]["provider"], "udemy")
        self.assertEqual(payload["plan"]["enginePayload"]["browser"], "chrome")
        self.assertEqual(handler.coordinator.submissions, [])
        self.assertEqual(handler.learning_api.created, [])

    def test_post_download_auto_creates_course_and_submits_safe_plan(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/download"
        handler.payload = {
            "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
            "browser": "chrome",
            "includeSubtitles": True,
            "cookie": "must-not-pass-through",
            "cookieFile": "../../cookies.txt",
            "httpHeaders": {"Authorization": "must-not-pass-through"},
        }
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 202)
        self.assertEqual(payload["provider"], "udemy")
        self.assertEqual(payload["course"]["id"], "b" * 32)
        self.assertEqual(payload["course"]["name"], "python bootcamp")
        self.assertEqual(payload["session"]["courseId"], "b" * 32)
        self.assertEqual(payload["job"]["state"], "queued")
        self.assertEqual(len(handler.coordinator.submissions), 1)
        plan, submitted_course_id = handler.coordinator.submissions[0]
        self.assertEqual(submitted_course_id, "b" * 32)
        engine_payload = plan["enginePayload"]
        self.assertEqual(engine_payload["browser"], "chrome")
        self.assertEqual(engine_payload["collectionMode"], "all")
        self.assertTrue(engine_payload["includeSubtitle"])
        self.assertNotIn("cookie", engine_payload)
        self.assertNotIn("cookieFile", engine_payload)
        self.assertNotIn("httpHeaders", engine_payload)
        self.assertNotIn("enginePayload", payload)

    def test_post_download_accepts_explicit_course_name(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/download"
        handler.payload = {
            "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
            "courseName": "My Python Course",
        }
        handler.do_POST()
        self.assertEqual(handler.response[0], 202)
        self.assertEqual(handler.learning_api.created[0]["name"], "My Python Course")

    def test_post_download_can_bind_existing_course(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/download"
        handler.payload = {
            "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
            "courseId": handler.learning_api.existing_id,
        }
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 202)
        self.assertEqual(payload["course"]["id"], handler.learning_api.existing_id)
        self.assertEqual(handler.learning_api.created, [])
        self.assertEqual(handler.coordinator.submissions[0][1], handler.learning_api.existing_id)

    def test_post_download_requires_authorization_before_course_creation(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/download"
        handler.authorized = False
        handler.payload = {"sourceUrl": "https://www.udemy.com/course/python-bootcamp/"}
        handler.do_POST()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))
        self.assertEqual(handler.learning_api.created, [])
        self.assertEqual(handler.coordinator.submissions, [])

    def test_post_download_maps_queue_full_to_429_and_rolls_back_course(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/download"
        handler.payload = {"sourceUrl": "https://www.udemy.com/course/python-bootcamp/"}
        handler.coordinator.error = HeadlessServiceError("download queue is full")
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 429)
        self.assertEqual(payload["code"], "LEARNING_COURSE_DOWNLOAD_QUEUE_FULL")
        self.assertEqual(handler.learning_api.removed, ["b" * 32])

    def test_post_download_maps_missing_existing_course(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/download"
        handler.payload = {
            "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
            "courseId": "d" * 32,
        }
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 404)
        self.assertEqual(payload["code"], "LEARNING_COURSE_NOT_FOUND")
        self.assertEqual(handler.coordinator.submissions, [])

    def test_post_returns_typed_validation_error(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/resolve"
        handler.payload = {"sourceUrl": "https://example.com/course/test/"}
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "LEARNING_COURSE_PROVIDER_INVALID")

    def test_unrelated_routes_fall_through(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/courses"
        handler.do_GET()
        handler.do_POST()
        self.assertTrue(handler.fallback_get)
        self.assertTrue(handler.fallback_post)


if __name__ == "__main__":
    unittest.main()
