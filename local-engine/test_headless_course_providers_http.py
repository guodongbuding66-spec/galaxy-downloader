from __future__ import annotations

import unittest
from unittest.mock import patch

from headless_course_providers_http import HeadlessCourseProvidersHttpMixin


class _FallbackHandler:
    def __init__(self) -> None:
        self.path = "/"
        self.authorized = True
        self.payload = {}
        self.response = None
        self.fallback_get = False
        self.fallback_post = False

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
