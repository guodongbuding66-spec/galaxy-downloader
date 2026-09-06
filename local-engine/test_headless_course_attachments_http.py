from __future__ import annotations

import unittest

from course_attachment_download_service import CourseAttachmentDownloadServiceError
from headless_course_attachments_http import HeadlessCourseAttachmentsHttpMixin


class _Service:
    def __init__(self) -> None:
        self.submissions: list[tuple[object, object]] = []
        self.statuses: list[str] = []
        self.cancellations: list[str] = []
        self.error: Exception | None = None
        self.job_id = "a" * 32

    def _job(self, state="queued"):
        return {
            "id": self.job_id,
            "attachmentId": "b" * 32,
            "state": state,
            "progress": 0.0,
            "downloadedBytes": 0,
            "sizeBytes": 0,
            "fileName": "",
            "error": "",
            "createdAt": "2026-09-06T00:00:00Z",
            "updatedAt": "2026-09-06T00:00:00Z",
        }

    def submit(self, attachment_id, *, browser="none"):
        if self.error is not None:
            raise self.error
        self.submissions.append((attachment_id, browser))
        return self._job()

    def status(self, job_id):
        if self.error is not None:
            raise self.error
        self.statuses.append(str(job_id))
        if str(job_id) != self.job_id:
            raise CourseAttachmentDownloadServiceError("attachment download job not found")
        return self._job("running")

    def cancel(self, job_id):
        if self.error is not None:
            raise self.error
        self.cancellations.append(str(job_id))
        if str(job_id) != self.job_id:
            raise CourseAttachmentDownloadServiceError("attachment download job not found")
        return self._job("cancelling")


class _Server:
    def __init__(self, service) -> None:
        self.course_attachment_download_service = service


class _Fallback:
    def __init__(self) -> None:
        self.path = "/"
        self.authorized = True
        self.payload = {}
        self.response = None
        self.read_count = 0
        self.fallback_get = False
        self.fallback_post = False
        self.service = _Service()
        self.server = _Server(self.service)

    def _authorized(self):
        return self.authorized

    def _read_json(self):
        self.read_count += 1
        return dict(self.payload)

    def _json(self, status, payload):
        self.response = (status, payload)

    def do_GET(self):  # noqa: N802
        self.fallback_get = True

    def do_POST(self):  # noqa: N802
        self.fallback_post = True


class _Handler(HeadlessCourseAttachmentsHttpMixin, _Fallback):
    pass


class HeadlessCourseAttachmentHttpTests(unittest.TestCase):
    def test_submit_accepts_only_public_attachment_id_and_browser(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/attachments/download"
        handler.payload = {
            "attachmentId": "b" * 32,
            "browser": "chrome",
            "cookie": "PRIVATE",
            "cookieFile": "../../cookies.txt",
            "httpHeaders": {"Authorization": "Bearer PRIVATE"},
            "outputPath": "C:/PRIVATE",
            "downloadUrl": "https://cdn.example/file?sig=PRIVATE",
            "providerCourseId": "udemy:course:PRIVATE",
        }
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 202)
        self.assertEqual(handler.service.submissions, [("b" * 32, "chrome")])
        self.assertEqual(payload["job"]["state"], "queued")
        self.assertNotIn("PRIVATE", str(payload))
        self.assertNotIn("cookie", str(payload).lower())
        self.assertNotIn("url", str(payload).lower())
        self.assertNotIn("path", str(payload).lower())

    def test_submit_requires_authorization_before_reading_body(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/attachments/download"
        handler.authorized = False
        handler.payload = {"attachmentId": "b" * 32}
        handler.do_POST()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))
        self.assertEqual(handler.read_count, 0)
        self.assertEqual(handler.service.submissions, [])

    def test_status_and_cancel_are_public_safe(self) -> None:
        handler = _Handler()
        job_id = handler.service.job_id
        handler.path = f"/v1/learning/attachments/downloads/{job_id}"
        handler.do_GET()
        self.assertEqual(handler.response[0], 200)
        self.assertEqual(handler.response[1]["job"]["state"], "running")
        self.assertEqual(handler.service.statuses, [job_id])

        handler.path = f"/v1/learning/attachments/downloads/{job_id}/cancel"
        handler.do_POST()
        self.assertEqual(handler.response[0], 200)
        self.assertEqual(handler.response[1]["job"]["state"], "cancelling")
        self.assertEqual(handler.service.cancellations, [job_id])

    def test_missing_job_maps_to_404_and_queue_full_maps_to_429(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/attachments/downloads/" + "d" * 32
        handler.do_GET()
        self.assertEqual(handler.response[0], 404)
        self.assertEqual(handler.response[1]["code"], "LEARNING_ATTACHMENT_DOWNLOAD_NOT_FOUND")

        handler = _Handler()
        handler.path = "/v1/learning/attachments/download"
        handler.payload = {"attachmentId": "b" * 32}
        handler.service.error = CourseAttachmentDownloadServiceError("attachment download queue is full")
        handler.do_POST()
        self.assertEqual(handler.response[0], 429)
        self.assertEqual(handler.response[1]["code"], "LEARNING_ATTACHMENT_DOWNLOAD_QUEUE_FULL")

    def test_unavailable_service_and_unrelated_routes_fall_through(self) -> None:
        handler = _Handler()
        handler.server.course_attachment_download_service = None
        handler.path = "/v1/learning/attachments/download"
        handler.do_POST()
        self.assertEqual(handler.response[0], 503)
        self.assertEqual(handler.response[1]["code"], "LEARNING_ATTACHMENT_DOWNLOAD_UNAVAILABLE")

        handler = _Handler()
        handler.path = "/v1/learning/courses"
        handler.do_GET()
        handler.do_POST()
        self.assertTrue(handler.fallback_get)
        self.assertTrue(handler.fallback_post)


if __name__ == "__main__":
    unittest.main()
