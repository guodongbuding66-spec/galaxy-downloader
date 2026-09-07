from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from headless_music_media_http import (
    HeadlessMusicMediaHttpMixin,
    MusicPlaybackTicketRegistry,
    _MUSIC_PLAYBACK_TICKETS,
    _audio_source,
    _parse_single_range,
)

MEDIA_ID = "a" * 32


class FakeMusicApi:
    def __init__(self) -> None:
        self.context = object()


class _FallbackHandler:
    def __init__(self) -> None:
        self.path = "/"
        self.authorized = True
        self.host_allowed = True
        self.origin_allowed = True
        self.music_api = FakeMusicApi()
        self.headers = {}
        self.response = None
        self.status = None
        self.response_headers: dict[str, str] = {}
        self.wfile = io.BytesIO()
        self.fallback_get = False
        self.fallback_post = False

    def _authorized(self) -> bool:
        return self.authorized

    def _valid_host_header(self) -> bool:
        return self.host_allowed

    def _browser_origin_allowed(self) -> bool:
        return self.origin_allowed

    def _json(self, status: int, payload: dict) -> None:
        self.response = (status, payload)

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        self.response_headers[key] = value

    def end_headers(self) -> None:
        return None

    def do_GET(self) -> None:  # noqa: N802
        self.fallback_get = True

    def do_POST(self) -> None:  # noqa: N802
        self.fallback_post = True


class _Handler(HeadlessMusicMediaHttpMixin, _FallbackHandler):
    pass


class MusicPlaybackHelpersTests(unittest.TestCase):
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
        registry = MusicPlaybackTicketRegistry()
        token, ttl = registry.issue(MEDIA_ID, now=10.0)
        self.assertEqual(ttl, 300)
        self.assertTrue(registry.valid(token, MEDIA_ID, now=11.0))
        self.assertFalse(registry.valid(token, "b" * 32, now=11.0))
        self.assertFalse(registry.valid(token, MEDIA_ID, now=311.0))

    def test_audio_source_rejects_non_audio(self) -> None:
        api = FakeMusicApi()
        with patch("headless_music_media_http.resolve_media_item_path", return_value=Path("demo.mp4")):
            with self.assertRaises(Exception) as caught:
                _audio_source(api, MEDIA_ID)
        self.assertEqual(getattr(caught.exception, "status", None), 415)
        self.assertEqual(getattr(caught.exception, "code", None), "MUSIC_MEDIA_NOT_AUDIO")


class HeadlessMusicPlaybackHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        _MUSIC_PLAYBACK_TICKETS.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.audio = Path(self.temp.name) / "track.mp3"
        self.audio.write_bytes(b"0123456789")

    def tearDown(self) -> None:
        _MUSIC_PLAYBACK_TICKETS.clear()
        self.temp.cleanup()

    def _issue_ticket(self) -> str:
        handler = _Handler()
        handler.path = f"/v1/music/media/{MEDIA_ID}/playback-ticket"
        with patch("headless_music_media_http.resolve_media_item_path", return_value=self.audio):
            handler.do_POST()
        self.assertEqual(handler.response[0], 200)
        playback = handler.response[1]["playback"]
        self.assertEqual(playback["mediaId"], MEDIA_ID)
        self.assertEqual(playback["expiresInSeconds"], 300)
        self.assertTrue(playback["url"].startswith("/v1/music/playback/"))
        return playback["url"].split("/")[4]

    def test_ticket_requires_authorization(self) -> None:
        handler = _Handler()
        handler.authorized = False
        handler.path = f"/v1/music/media/{MEDIA_ID}/playback-ticket"
        handler.do_POST()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))

    def test_range_stream_uses_ticket_without_bearer_header(self) -> None:
        ticket = self._issue_ticket()
        handler = _Handler()
        handler.path = f"/v1/music/playback/{ticket}/{MEDIA_ID}"
        handler.headers = {"Range": "bytes=2-5"}
        with patch("headless_music_media_http.resolve_media_item_path", return_value=self.audio):
            handler.do_GET()
        self.assertEqual(handler.status, 206)
        self.assertEqual(handler.response_headers.get("Content-Range"), "bytes 2-5/10")
        self.assertEqual(handler.response_headers.get("Accept-Ranges"), "bytes")
        self.assertEqual(handler.response_headers.get("Cache-Control"), "no-store")
        self.assertEqual(handler.wfile.getvalue(), b"2345")

    def test_stream_rejects_invalid_ticket_and_cross_origin(self) -> None:
        handler = _Handler()
        handler.path = f"/v1/music/playback/not-a-ticket/{MEDIA_ID}"
        handler.do_GET()
        self.assertEqual(handler.response[0], 401)

        ticket = self._issue_ticket()
        handler = _Handler()
        handler.origin_allowed = False
        handler.path = f"/v1/music/playback/{ticket}/{MEDIA_ID}"
        handler.do_GET()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))

    def test_bad_range_returns_416_without_body(self) -> None:
        ticket = self._issue_ticket()
        handler = _Handler()
        handler.path = f"/v1/music/playback/{ticket}/{MEDIA_ID}"
        handler.headers = {"Range": "bytes=100-200"}
        with patch("headless_music_media_http.resolve_media_item_path", return_value=self.audio):
            handler.do_GET()
        self.assertEqual(handler.status, 416)
        self.assertEqual(handler.response_headers.get("Content-Range"), "bytes */10")
        self.assertEqual(handler.wfile.getvalue(), b"")

    def test_unrelated_routes_fall_through(self) -> None:
        handler = _Handler()
        handler.path = "/v1/music/songs"
        handler.do_GET()
        self.assertTrue(handler.fallback_get)
        handler = _Handler()
        handler.path = "/v1/music/player"
        handler.do_POST()
        self.assertTrue(handler.fallback_post)

    def test_production_handler_composes_music_media_mixin(self) -> None:
        source = Path(__file__).with_name("headless_api.py").read_text(encoding="utf-8")
        self.assertIn("from headless_music_media_http import HeadlessMusicMediaHttpMixin", source)
        class_start = source.index("class GalaxyApiRequestHandler(")
        class_end = source.index("):", class_start)
        self.assertIn("HeadlessMusicMediaHttpMixin", source[class_start:class_end])


if __name__ == "__main__":
    unittest.main()
