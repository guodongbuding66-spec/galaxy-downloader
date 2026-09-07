from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from headless_learning_media_http import (
    HeadlessLearningMediaHttpMixin,
    PlaybackTicketRegistry,
    _PLAYBACK_TICKETS,
)

MEDIA_ID = "c" * 32
OTHER_MEDIA_ID = "d" * 32


class _FallbackHandler:
    def __init__(self) -> None:
        self.path = "/"
        self.headers: dict[str, str] = {}
        self.learning_api = SimpleNamespace(context=object())
        self.authorized = True
        self.host_valid = True
        self.origin_allowed = True
        self.response = None
        self.status = None
        self.response_headers: dict[str, str] = {}
        self.wfile = io.BytesIO()
        self.fallback_get = False
        self.fallback_post = False

    def _authorized(self) -> bool:
        return self.authorized

    def _valid_host_header(self) -> bool:
        return self.host_valid

    def _browser_origin_allowed(self) -> bool:
        return self.origin_allowed

    def _json(self, status: int, payload: dict) -> None:
        self.response = (status, payload)

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.response_headers[name] = value

    def end_headers(self) -> None:
        return None

    def do_GET(self) -> None:  # noqa: N802
        self.fallback_get = True

    def do_POST(self) -> None:  # noqa: N802
        self.fallback_post = True


class _Handler(HeadlessLearningMediaHttpMixin, _FallbackHandler):
    pass


class HeadlessLearningMediaHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        _PLAYBACK_TICKETS.clear()
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "lesson.mp4"
        self.source.write_bytes(b"0123456789")

    def tearDown(self) -> None:
        _PLAYBACK_TICKETS.clear()
        self.tempdir.cleanup()

    def test_ticket_issue_requires_bearer_authorization(self) -> None:
        handler = _Handler()
        handler.authorized = False
        handler.path = f"/v1/learning/media/{MEDIA_ID}/playback-ticket"
        with patch("headless_learning_media_http.resolve_media_item_path") as resolver:
            handler.do_POST()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))
        resolver.assert_not_called()

    def test_ticket_issue_returns_only_opaque_playback_url(self) -> None:
        handler = _Handler()
        handler.path = f"/v1/learning/media/{MEDIA_ID}/playback-ticket"
        with patch("headless_learning_media_http.resolve_media_item_path", return_value=self.source):
            handler.do_POST()
        status, payload = handler.response
        self.assertEqual(status, 200)
        playback = payload["playback"]
        self.assertEqual(playback["mediaId"], MEDIA_ID)
        self.assertEqual(playback["expiresInSeconds"], 300)
        self.assertTrue(playback["url"].startswith("/v1/learning/playback/"))
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("filePath", serialized)
        self.assertNotIn("localPath", serialized)

    def test_ticket_issue_rejects_invalid_and_nonplayable_media(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/media/not-an-id/playback-ticket"
        handler.do_POST()
        self.assertEqual(handler.response[0], 400)
        self.assertEqual(handler.response[1]["code"], "LEARNING_INVALID_MEDIA_ID")

        image = self.root / "cover.png"
        image.write_bytes(b"png")
        handler = _Handler()
        handler.path = f"/v1/learning/media/{MEDIA_ID}/playback-ticket"
        with patch("headless_learning_media_http.resolve_media_item_path", return_value=image):
            handler.do_POST()
        self.assertEqual(handler.response[0], 415)
        self.assertEqual(handler.response[1]["code"], "LEARNING_MEDIA_NOT_PLAYABLE")

    def test_full_stream_uses_media_scoped_ticket(self) -> None:
        ticket, _ttl = _PLAYBACK_TICKETS.issue(MEDIA_ID)
        handler = _Handler()
        handler.path = f"/v1/learning/playback/{ticket}/{MEDIA_ID}"
        with patch("headless_learning_media_http.resolve_media_item_path", return_value=self.source):
            handler.do_GET()
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.response_headers["Content-Length"], "10")
        self.assertEqual(handler.response_headers["Accept-Ranges"], "bytes")
        self.assertEqual(handler.response_headers["Cache-Control"], "no-store")
        self.assertEqual(handler.wfile.getvalue(), b"0123456789")

    def test_range_stream_returns_206_and_exact_slice(self) -> None:
        ticket, _ttl = _PLAYBACK_TICKETS.issue(MEDIA_ID)
        handler = _Handler()
        handler.headers["Range"] = "bytes=2-5"
        handler.path = f"/v1/learning/playback/{ticket}/{MEDIA_ID}"
        with patch("headless_learning_media_http.resolve_media_item_path", return_value=self.source):
            handler.do_GET()
        self.assertEqual(handler.status, 206)
        self.assertEqual(handler.response_headers["Content-Range"], "bytes 2-5/10")
        self.assertEqual(handler.response_headers["Content-Length"], "4")
        self.assertEqual(handler.wfile.getvalue(), b"2345")

    def test_suffix_range_is_supported(self) -> None:
        ticket, _ttl = _PLAYBACK_TICKETS.issue(MEDIA_ID)
        handler = _Handler()
        handler.headers["Range"] = "bytes=-3"
        handler.path = f"/v1/learning/playback/{ticket}/{MEDIA_ID}"
        with patch("headless_learning_media_http.resolve_media_item_path", return_value=self.source):
            handler.do_GET()
        self.assertEqual(handler.status, 206)
        self.assertEqual(handler.response_headers["Content-Range"], "bytes 7-9/10")
        self.assertEqual(handler.wfile.getvalue(), b"789")

    def test_invalid_range_returns_416(self) -> None:
        ticket, _ttl = _PLAYBACK_TICKETS.issue(MEDIA_ID)
        handler = _Handler()
        handler.headers["Range"] = "bytes=99-120"
        handler.path = f"/v1/learning/playback/{ticket}/{MEDIA_ID}"
        with patch("headless_learning_media_http.resolve_media_item_path", return_value=self.source):
            handler.do_GET()
        self.assertEqual(handler.status, 416)
        self.assertEqual(handler.response_headers["Content-Range"], "bytes */10")
        self.assertEqual(handler.wfile.getvalue(), b"")

    def test_ticket_cannot_authorize_another_media_id(self) -> None:
        ticket, _ttl = _PLAYBACK_TICKETS.issue(MEDIA_ID)
        handler = _Handler()
        handler.path = f"/v1/learning/playback/{ticket}/{OTHER_MEDIA_ID}"
        with patch("headless_learning_media_http.resolve_media_item_path") as resolver:
            handler.do_GET()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "invalid or expired playback ticket"}))
        resolver.assert_not_called()

    def test_stream_rejects_invalid_host_or_origin_before_media_access(self) -> None:
        ticket, _ttl = _PLAYBACK_TICKETS.issue(MEDIA_ID)
        handler = _Handler()
        handler.host_valid = False
        handler.path = f"/v1/learning/playback/{ticket}/{MEDIA_ID}"
        with patch("headless_learning_media_http.resolve_media_item_path") as resolver:
            handler.do_GET()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))
        resolver.assert_not_called()

    def test_ticket_registry_expires_entries(self) -> None:
        registry = PlaybackTicketRegistry()
        ticket, ttl = registry.issue(MEDIA_ID, now=10.0)
        self.assertTrue(registry.valid(ticket, MEDIA_ID, now=10.0 + ttl - 0.1))
        self.assertFalse(registry.valid(ticket, MEDIA_ID, now=10.0 + ttl))

    def test_unrelated_routes_fall_through(self) -> None:
        handler = _Handler()
        handler.path = "/v1/learning/courses"
        handler.do_GET()
        self.assertTrue(handler.fallback_get)
        handler = _Handler()
        handler.path = "/v1/learning/courses"
        handler.do_POST()
        self.assertTrue(handler.fallback_post)

    def test_production_handler_composes_playback_mixin(self) -> None:
        source = Path(__file__).with_name("headless_api.py").read_text(encoding="utf-8")
        self.assertIn("from headless_learning_media_http import HeadlessLearningMediaHttpMixin", source)
        class_start = source.index("class GalaxyApiRequestHandler(")
        class_end = source.index("):", class_start)
        self.assertIn("HeadlessLearningMediaHttpMixin", source[class_start:class_end])


if __name__ == "__main__":
    unittest.main()
