from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from headless_media_playback_http import (
    HeadlessMediaPlaybackHttpMixin,
    MediaPlaybackTicketRegistry,
    _MEDIA_PLAYBACK_TICKETS,
    _parse_single_range,
    _playable_source,
)

MEDIA_ID = "a" * 32
OTHER_MEDIA_ID = "b" * 32


class _FallbackHandler:
    def __init__(self) -> None:
        self.path = "/"
        self.headers: dict[str, str] = {}
        self.media_api = SimpleNamespace(context=object())
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


class _Handler(HeadlessMediaPlaybackHttpMixin, _FallbackHandler):
    pass


class MediaPlaybackHelpersTests(unittest.TestCase):
    def test_single_range_parser(self) -> None:
        self.assertIsNone(_parse_single_range("", 10))
        self.assertEqual(_parse_single_range("bytes=2-5", 10), (2, 5))
        self.assertEqual(_parse_single_range("bytes=7-", 10), (7, 9))
        self.assertEqual(_parse_single_range("bytes=-3", 10), (7, 9))
        with self.assertRaises(ValueError):
            _parse_single_range("bytes=10-11", 10)
        with self.assertRaises(ValueError):
            _parse_single_range("bytes=0-1,3-4", 10)

    def test_ticket_registry_is_media_scoped_and_expires(self) -> None:
        registry = MediaPlaybackTicketRegistry()
        token, ttl = registry.issue(MEDIA_ID, now=10.0)
        self.assertEqual(ttl, 300)
        self.assertTrue(registry.valid(token, MEDIA_ID, now=11.0))
        self.assertFalse(registry.valid(token, OTHER_MEDIA_ID, now=11.0))
        self.assertFalse(registry.valid(token, MEDIA_ID, now=311.0))

    def test_playable_source_rejects_non_media(self) -> None:
        api = SimpleNamespace(context=object())
        with patch("headless_media_playback_http.resolve_media_item_path", return_value=Path("cover.png")):
            with self.assertRaises(Exception) as caught:
                _playable_source(api, MEDIA_ID)
        self.assertEqual(getattr(caught.exception, "status", None), 415)
        self.assertEqual(getattr(caught.exception, "code", None), "MEDIA_PLAYBACK_UNSUPPORTED")


class HeadlessMediaPlaybackHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        _MEDIA_PLAYBACK_TICKETS.clear()
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.video = self.root / "clip.mp4"
        self.video.write_bytes(b"0123456789")

    def tearDown(self) -> None:
        _MEDIA_PLAYBACK_TICKETS.clear()
        self.tempdir.cleanup()

    def _issue_ticket(self) -> dict:
        handler = _Handler()
        handler.path = f"/v1/media/{MEDIA_ID}/playback-ticket"
        with patch("headless_media_playback_http.resolve_media_item_path", return_value=self.video):
            handler.do_POST()
        self.assertEqual(handler.response[0], 200)
        return handler.response[1]["playback"]

    def test_ticket_issue_requires_bearer_authorization(self) -> None:
        handler = _Handler()
        handler.authorized = False
        handler.path = f"/v1/media/{MEDIA_ID}/playback-ticket"
        with patch("headless_media_playback_http.resolve_media_item_path") as resolver:
            handler.do_POST()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))
        resolver.assert_not_called()

    def test_ticket_is_opaque_and_does_not_expose_local_path(self) -> None:
        playback = self._issue_ticket()
        self.assertEqual(playback["mediaId"], MEDIA_ID)
        self.assertEqual(playback["mediaType"], "video")
        self.assertEqual(playback["expiresInSeconds"], 300)
        self.assertTrue(playback["url"].startswith("/v1/media/playback/"))
        serialized = json.dumps(playback, ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("filePath", serialized)
        self.assertNotIn("localPath", serialized)
        self.assertNotIn("?token=", serialized)

    def test_range_stream_returns_206_and_exact_slice(self) -> None:
        playback = self._issue_ticket()
        ticket = playback["url"].split("/")[4]
        handler = _Handler()
        handler.headers["Range"] = "bytes=2-5"
        handler.path = f"/v1/media/playback/{ticket}/{MEDIA_ID}"
        with patch("headless_media_playback_http.resolve_media_item_path", return_value=self.video):
            handler.do_GET()
        self.assertEqual(handler.status, 206)
        self.assertEqual(handler.response_headers["Content-Range"], "bytes 2-5/10")
        self.assertEqual(handler.response_headers["Content-Length"], "4")
        self.assertEqual(handler.response_headers["Accept-Ranges"], "bytes")
        self.assertEqual(handler.response_headers["Cache-Control"], "no-store")
        self.assertEqual(handler.wfile.getvalue(), b"2345")

    def test_ticket_cannot_authorize_another_media_id(self) -> None:
        playback = self._issue_ticket()
        ticket = playback["url"].split("/")[4]
        handler = _Handler()
        handler.path = f"/v1/media/playback/{ticket}/{OTHER_MEDIA_ID}"
        with patch("headless_media_playback_http.resolve_media_item_path") as resolver:
            handler.do_GET()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "invalid or expired playback ticket"}))
        resolver.assert_not_called()

    def test_stream_rejects_invalid_host_or_origin_before_file_access(self) -> None:
        playback = self._issue_ticket()
        ticket = playback["url"].split("/")[4]
        handler = _Handler()
        handler.origin_allowed = False
        handler.path = f"/v1/media/playback/{ticket}/{MEDIA_ID}"
        with patch("headless_media_playback_http.resolve_media_item_path") as resolver:
            handler.do_GET()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))
        resolver.assert_not_called()

    def test_invalid_range_returns_416(self) -> None:
        playback = self._issue_ticket()
        ticket = playback["url"].split("/")[4]
        handler = _Handler()
        handler.headers["Range"] = "bytes=99-120"
        handler.path = f"/v1/media/playback/{ticket}/{MEDIA_ID}"
        with patch("headless_media_playback_http.resolve_media_item_path", return_value=self.video):
            handler.do_GET()
        self.assertEqual(handler.status, 416)
        self.assertEqual(handler.response_headers["Content-Range"], "bytes */10")
        self.assertEqual(handler.wfile.getvalue(), b"")

    def test_unrelated_media_routes_fall_through(self) -> None:
        handler = _Handler()
        handler.path = "/v1/media"
        handler.do_GET()
        self.assertTrue(handler.fallback_get)
        handler = _Handler()
        handler.path = "/v1/media/sync"
        handler.do_POST()
        self.assertTrue(handler.fallback_post)

    def test_production_handler_composes_media_playback_mixin(self) -> None:
        source = Path(__file__).with_name("headless_api.py").read_text(encoding="utf-8")
        self.assertIn("from headless_media_playback_http import HeadlessMediaPlaybackHttpMixin", source)
        class_start = source.index("class GalaxyApiRequestHandler(")
        class_end = source.index("):", class_start)
        self.assertIn("HeadlessMediaPlaybackHttpMixin", source[class_start:class_end])


if __name__ == "__main__":
    unittest.main()
