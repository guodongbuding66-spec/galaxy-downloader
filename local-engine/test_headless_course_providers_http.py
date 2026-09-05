from __future__ import annotations

import unittest
from unittest.mock import patch

from headless_course_providers_http import HeadlessCourseProvidersHttpMixin
from headless_service import HeadlessServiceError


class _Job:
    def public_payload(self):
        return {
            "id": "a" * 32,
            "sourceHost": "www.udemy.com",
            "state": "queued",
            "progress": 0.0,
            "detail": "",
            "fileName": "",
            "attempt": 1,
            "createdAt": "2026-09-05T00:00:00Z",
            "updatedAt": "2026-09-05T00:00:00Z",
        }


class _Runtime:
    def __init__(self) -> None:
        self.submissions = []
        self.error = None

    def submit(self, payload):
        if self.error is not None:
            raise self.error
        self.submissions.append(dict(payload))
        return _Job()


class _FallbackHandler:
    def __init__(self) -> None:
        self.path = "/"
        self.authorized = True
        self.payload = {}
        self.response = None
        self.fallback_get = False
        self.fallback_post = False
        self.runtime = _Runtime()

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

    def test_get_requires_authorization(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers"
        handler.authorized = False
        handler.do_GET()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))

    def test_post_resolves_udemy_plan(self) -> None:
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
        self.assertEqual(handler.runtime.submissions, [])

    def test_post_download_submits_only_provider_engine_payload(self) -> None:
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
        self.assertEqual(payload["job"]["state"], "queued")
        self.assertEqual(len(handler.runtime.submissions), 1)
        submitted = handler.runtime.submissions[0]
        self.assertEqual(submitted["browser"], "chrome")
        self.assertEqual(submitted["collectionMode"], "all")
        self.assertTrue(submitted["includeSubtitle"])
        self.assertNotIn("cookie", submitted)
        self.assertNotIn("cookieFile", submitted)
        self.assertNotIn("httpHeaders", submitted)
        self.assertNotIn("enginePayload", payload)

    def test_post_download_requires_authorization_before_submit(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/download"
        handler.authorized = False
        handler.payload = {"sourceUrl": "https://www.udemy.com/course/python-bootcamp/"}
        handler.do_POST()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))
        self.assertEqual(handler.runtime.submissions, [])

    def test_post_download_maps_queue_full_to_429(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/providers/download"
        handler.payload = {"sourceUrl": "https://www.udemy.com/course/python-bootcamp/"}
        handler.runtime.error = HeadlessServiceError("download queue is full")
        handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 429)
        self.assertEqual(payload["code"], "LEARNING_COURSE_DOWNLOAD_QUEUE_FULL")

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
