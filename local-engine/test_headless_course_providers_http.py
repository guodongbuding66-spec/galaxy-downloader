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
        self.existing_source = "https://www.udemy.com/course/python-bootcamp/?couponCode=OLD"
        self.existing_provider = "udemy"

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
        self.submissions: list[tuple[dict, str]] = []
        self.error: Exception | None = None
        self.sync_error: Exception | None = None
        self.job = _Job()

    def _session(self, *, state="pending") -> dict:
        return {
            "jobId": self.job.job_id,
            "courseId": "b" * 32,
            "provider": "udemy",
            "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
            "syncState": state,
            "outputCount": 2 if state == "synced" else 0,
            "syncedCount": 2 if state == "synced" else 0,
            "syncError": "",
            "createdAt": "2026-09-05T00:00:00Z",
            "updatedAt": "2026-09-05T00:00:00Z",
        }

    def submit(self, plan, course_id):
        if self.error is not None:
            raise self.error
        self.submissions.append((dict(plan), str(course_id)))
        session = self._session()
        session["courseId"] = str(course_id)
        return self.job, session

    def status(self, job_id):
        if str(job_id) != self.job.job_id:
            raise CourseDownloadCoordinatorError("course download session not found")
        return {"job": self.job.public_payload(), "session": self._session()}

    def sync_now(self, job_id):
        if self.sync_error is not None:
            raise self.sync_error
        if str(job_id) != self.job.job_id:
            raise CourseDownloadCoordinatorError("course download job not found")
        return {"job": self.job.public_payload(), "session": self._session(state="synced")}


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

    def test_get_catalog_marks_hotmart_discovery_only(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers"
        handler.do_GET()
        status, payload = handler.response
        self.assertEqual(status, 200)
        providers = {provider["id"]: provider for provider in payload["providers"]}
        self.assertTrue(providers["udemy"]["downloadAvailable"])
        self.assertFalse(providers["hotmart"]["downloadAvailable"])
        self.assertEqual(providers["hotmart"]["status"], "discovery")
        self.assertFalse(providers["hotmart"]["supportsBrowserCookies"])
        self.assertFalse(providers["hotmart"]["drmBypassSupported"])

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

    def test_post_resolves_udemy_provider_without_building_download_plan(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/resolve"
        handler.payload = {
            "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
            "browser": "chrome",
            "includeSubtitles": True,
            "cookie": "must-not-pass-through",
        }
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 200)
        resolution = payload["resolution"]
        self.assertEqual(resolution["provider"], "udemy")
        self.assertTrue(resolution["downloadAvailable"])
        self.assertTrue(resolution["supportsBrowserCookies"])
        self.assertNotIn("plan", payload)
        self.assertNotIn("enginePayload", resolution)
        self.assertNotIn("browser", resolution)
        self.assertEqual(handler.coordinator.submissions, [])
        self.assertEqual(handler.learning_api.created, [])

    def test_post_hotmart_resolve_returns_discovery_metadata(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/resolve"
        handler.payload = {
            "sourceUrl": "https://my-course.club.hotmart.com/lesson/abc/start",
            "provider": "auto",
            "browser": "chrome",
            "cookieFile": "../../cookies.txt",
        }
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 200)
        resolution = payload["resolution"]
        self.assertEqual(resolution["provider"], "hotmart")
        self.assertEqual(resolution["status"], "discovery")
        self.assertFalse(resolution["downloadAvailable"])
        self.assertFalse(resolution["supportsBrowserCookies"])
        self.assertIn("Hotmart", resolution["downloadUnavailableReason"])
        self.assertIn("授权下载适配器尚未实现", resolution["downloadUnavailableReason"])
        self.assertNotIn("plan", payload)
        self.assertNotIn("enginePayload", resolution)
        self.assertNotIn("browser", resolution)
        self.assertEqual(handler.learning_api.created, [])
        self.assertEqual(handler.coordinator.submissions, [])

    def test_post_hotmart_download_cannot_create_course_or_submit(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/download"
        handler.payload = {
            "sourceUrl": "https://my-course.club.hotmart.com/",
            "provider": "hotmart",
            "browser": "chrome",
        }
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "LEARNING_COURSE_PROVIDER_INVALID")
        self.assertEqual(handler.learning_api.created, [])
        self.assertEqual(handler.coordinator.submissions, [])

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

    def test_post_download_can_bind_same_existing_course_ignoring_query(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/download"
        handler.payload = {
            "sourceUrl": "https://www.udemy.com/course/python-bootcamp/?couponCode=NEW#overview",
            "courseId": handler.learning_api.existing_id,
        }
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 202)
        self.assertEqual(payload["course"]["id"], handler.learning_api.existing_id)
        self.assertEqual(handler.learning_api.created, [])
        self.assertEqual(handler.coordinator.submissions[0][1], handler.learning_api.existing_id)

    def test_post_download_rejects_existing_course_from_different_source(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/download"
        handler.learning_api.existing_source = "https://www.udemy.com/course/another-course/"
        handler.payload = {
            "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
            "courseId": handler.learning_api.existing_id,
        }
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "LEARNING_COURSE_DOWNLOAD_REJECTED")
        self.assertIn("source does not match", payload["error"])
        self.assertEqual(handler.coordinator.submissions, [])

    def test_post_download_rejects_existing_course_from_different_provider(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/download"
        handler.learning_api.existing_provider = "generic"
        handler.payload = {
            "sourceUrl": "https://www.udemy.com/course/python-bootcamp/",
            "courseId": handler.learning_api.existing_id,
        }
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "LEARNING_COURSE_DOWNLOAD_REJECTED")
        self.assertIn("provider does not match", payload["error"])
        self.assertEqual(handler.coordinator.submissions, [])

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

    def test_post_sync_recovers_completed_course_indexing(self) -> None:
        handler = _Handler()
        handler.path = f"/v1/learning/providers/downloads/{handler.coordinator.job.job_id}/sync"
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 200)
        self.assertEqual(payload["session"]["syncState"], "synced")
        self.assertEqual(payload["session"]["syncedCount"], 2)

    def test_post_sync_maps_non_completed_job_to_409(self) -> None:
        handler = _Handler()
        handler.path = f"/v1/learning/providers/downloads/{handler.coordinator.job.job_id}/sync"
        handler.coordinator.sync_error = CourseDownloadCoordinatorError("course download cannot sync from state queued")
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "LEARNING_COURSE_SYNC_REJECTED")

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
