from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from course_workspace import CourseWorkspaceError
from headless_learning_resume_http import HeadlessLearningResumeHttpMixin


class _LearningApi:
    context = object()


class _FallbackHandler:
    def __init__(self) -> None:
        self.path = "/"
        self.authorized = True
        self.learning_api = _LearningApi()
        self.response = None
        self.fallback_get = False

    def _authorized(self) -> bool:
        return self.authorized

    def _json(self, status, payload) -> None:
        self.response = (status, payload)

    def do_GET(self) -> None:  # noqa: N802
        self.fallback_get = True


class _Handler(HeadlessLearningResumeHttpMixin, _FallbackHandler):
    pass


class HeadlessLearningResumeHttpTests(unittest.TestCase):
    def test_get_returns_safe_resume_envelope(self) -> None:
        handler = _Handler()
        course_id = "a" * 32
        item_id = "b" * 32
        media_id = "c" * 32
        handler.path = f"/v1/learning/courses/{course_id}/resume?ignored=1"
        resolved = {
            "courseId": course_id,
            "state": "resume",
            "item": {
                "id": item_id,
                "mediaId": media_id,
                "position": 2,
                "title": "Lesson 2",
                "mediaType": "video",
                "durationSeconds": 300.0,
                "available": True,
                "localPath": "C:/Users/example/secret/video.mp4",
                "filePath": "/private/media/video.mp4",
            },
            "progressSeconds": 15.0,
            "completed": False,
            "reason": "most recently updated unfinished playable item",
            "localPath": "C:/Users/example/secret",
        }
        with patch("headless_learning_resume.resolve_course_resume", return_value=resolved):
            handler.do_GET()

        status, payload = handler.response
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        resume = payload["resume"]
        self.assertEqual(resume["courseId"], course_id)
        self.assertEqual(resume["state"], "resume")
        self.assertEqual(resume["progressSeconds"], 15.0)
        self.assertEqual(resume["item"]["id"], item_id)
        self.assertEqual(resume["item"]["mediaId"], media_id)
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("localPath", serialized)
        self.assertNotIn("filePath", serialized)
        self.assertNotIn("C:/Users", serialized)
        self.assertNotIn("/private/media", serialized)

    def test_get_maps_malformed_course_id_to_400(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/courses/not-a-course-id/resume"
        handler.do_GET()
        status, payload = handler.response
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "LEARNING_INVALID_COURSE_ID")
        self.assertEqual(payload["error"], "invalid course id")

    def test_get_maps_missing_course_to_404(self) -> None:
        handler = _Handler()
        course_id = "d" * 32
        handler.path = f"/v1/learning/courses/{course_id}/resume"
        with patch(
            "headless_learning_resume.resolve_course_resume",
            side_effect=CourseWorkspaceError("课程不存在"),
        ):
            handler.do_GET()
        status, payload = handler.response
        self.assertEqual(status, 404)
        self.assertEqual(payload["code"], "LEARNING_COURSE_NOT_FOUND")
        self.assertEqual(payload["error"], "course not found")

    def test_get_requires_authorization_before_resolution(self) -> None:
        handler = _Handler()
        handler.path = f"/v1/learning/courses/{'e' * 32}/resume"
        handler.authorized = False
        with patch("headless_learning_resume_http.resolve_headless_course_resume") as resolver:
            handler.do_GET()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))
        resolver.assert_not_called()

    def test_get_returns_503_when_learning_api_is_unavailable(self) -> None:
        handler = _Handler()
        handler.path = f"/v1/learning/courses/{'f' * 32}/resume"
        handler.learning_api = None
        handler.do_GET()
        self.assertEqual(
            handler.response,
            (503, {"ok": False, "error": "learning api is unavailable"}),
        )

    def test_unrelated_learning_route_falls_through(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/courses"
        handler.do_GET()
        self.assertTrue(handler.fallback_get)
        self.assertIsNone(handler.response)

    def test_production_handler_composes_resume_mixin(self) -> None:
        source = Path(__file__).with_name("headless_api.py").read_text(encoding="utf-8")
        self.assertIn(
            "from headless_learning_resume_http import HeadlessLearningResumeHttpMixin",
            source,
        )
        class_start = source.index("class GalaxyApiRequestHandler(")
        class_end = source.index("):", class_start)
        self.assertIn("HeadlessLearningResumeHttpMixin", source[class_start:class_end])


if __name__ == "__main__":
    unittest.main()
