from __future__ import annotations

import math
import unittest
from pathlib import Path

from headless_music_player_http import HeadlessMusicPlayerHttpMixin
from music_player_navigation import (
    MAX_SEEK_SECONDS,
    MusicPlayerNavigationError,
    navigate,
    playback_order,
    run_music_player_navigation_self_test,
    seek,
)

MEDIA_A = "a" * 32
MEDIA_B = "b" * 32
MEDIA_C = "c" * 32


class FakeMusicApi:
    def __init__(self) -> None:
        self.player_state = {
            "currentMediaId": "",
            "repeatMode": "off",
            "shuffle": False,
            "volume": 1.0,
        }
        self.rows = [
            {"id": "1" * 32, "position": 1, "track": {"mediaId": MEDIA_A, "title": "A", "lastPosition": 0.0}},
            {"id": "2" * 32, "position": 2, "track": {"mediaId": MEDIA_B, "title": "B", "lastPosition": 2.0}},
            {"id": "3" * 32, "position": 3, "track": {"mediaId": MEDIA_C, "title": "C", "lastPosition": 3.0}},
        ]

    def queue(self):
        return {"queue": [{**row, "track": dict(row["track"])} for row in self.rows]}

    def player(self):
        return {"player": dict(self.player_state)}

    def update_player(self, payload):
        self.player_state.update(payload)
        return self.player()

    def update_song_state(self, media_id, payload):
        for row in self.rows:
            if row["track"]["mediaId"] == media_id:
                row["track"]["lastPosition"] = float(payload["lastPosition"])
                return {"song": dict(row["track"])}
        raise RuntimeError("missing track")


class _FallbackHandler:
    def __init__(self) -> None:
        self.path = "/"
        self.authorized = True
        self.music_api = FakeMusicApi()
        self.payload = {}
        self.response = None
        self.fallback_post = False

    def _authorized(self) -> bool:
        return self.authorized

    def _read_json(self):
        return self.payload

    def _json(self, status: int, payload: dict) -> None:
        self.response = (status, payload)

    def do_POST(self) -> None:  # noqa: N802
        self.fallback_post = True


class _Handler(HeadlessMusicPlayerHttpMixin, _FallbackHandler):
    pass


class MusicPlayerNavigationTests(unittest.TestCase):
    def test_sequential_navigation_and_repeat_all_boundary(self) -> None:
        api = FakeMusicApi()
        first = navigate(api, "next")
        self.assertEqual(first["song"]["mediaId"], MEDIA_A)
        self.assertTrue(first["moved"])
        self.assertFalse(first["boundary"])

        second = navigate(api, "next")
        self.assertEqual(second["song"]["mediaId"], MEDIA_B)
        previous = navigate(api, "previous")
        self.assertEqual(previous["song"]["mediaId"], MEDIA_A)

        api.player_state["currentMediaId"] = MEDIA_C
        stopped = navigate(api, "next")
        self.assertFalse(stopped["moved"])
        self.assertTrue(stopped["boundary"])
        self.assertEqual(stopped["player"]["currentMediaId"], MEDIA_C)

        api.player_state["repeatMode"] = "all"
        wrapped = navigate(api, "next")
        self.assertEqual(wrapped["song"]["mediaId"], MEDIA_A)
        self.assertTrue(wrapped["boundary"])

    def test_previous_without_current_selects_last(self) -> None:
        api = FakeMusicApi()
        result = navigate(api, "previous")
        self.assertEqual(result["song"]["mediaId"], MEDIA_C)

    def test_shuffle_order_is_stable_and_uses_queue_item_identity(self) -> None:
        api = FakeMusicApi()
        api.player_state["shuffle"] = True
        first = [row["id"] for row in playback_order(api)]
        second = [row["id"] for row in playback_order(api)]
        self.assertEqual(first, second)
        self.assertCountEqual(first, ["1" * 32, "2" * 32, "3" * 32])

    def test_seek_updates_only_current_track_position(self) -> None:
        api = FakeMusicApi()
        api.player_state["currentMediaId"] = MEDIA_B
        result = seek(api, 42.25)
        self.assertEqual(result["positionSeconds"], 42.25)
        self.assertEqual(result["song"]["mediaId"], MEDIA_B)
        self.assertEqual(result["song"]["lastPosition"], 42.25)
        self.assertEqual(api.rows[0]["track"]["lastPosition"], 0.0)

    def test_invalid_navigation_and_seek_are_rejected(self) -> None:
        api = FakeMusicApi()
        with self.assertRaises(MusicPlayerNavigationError):
            navigate(api, "sideways")
        with self.assertRaises(MusicPlayerNavigationError):
            seek(api, math.nan)
        with self.assertRaises(MusicPlayerNavigationError):
            seek(api, MAX_SEEK_SECONDS + 1)
        with self.assertRaises(MusicPlayerNavigationError):
            seek(api, 1)

    def test_empty_queue_is_explicit_conflict(self) -> None:
        api = FakeMusicApi()
        api.rows = []
        with self.assertRaises(MusicPlayerNavigationError) as caught:
            navigate(api, "next")
        self.assertEqual(caught.exception.code, "MUSIC_QUEUE_EMPTY")
        self.assertEqual(caught.exception.status, 409)


class HeadlessMusicPlayerHttpTests(unittest.TestCase):
    def test_requires_authorization_before_navigation(self) -> None:
        handler = _Handler()
        handler.authorized = False
        handler.path = "/v1/music/player/next"
        handler.do_POST()
        self.assertEqual(handler.response, (401, {"ok": False, "error": "unauthorized"}))
        self.assertEqual(handler.music_api.player_state["currentMediaId"], "")

    def test_next_and_previous_routes(self) -> None:
        handler = _Handler()
        handler.path = "/v1/music/player/next"
        handler.do_POST()
        self.assertEqual(handler.response[0], 200)
        self.assertEqual(handler.response[1]["song"]["mediaId"], MEDIA_A)

        handler.path = "/v1/music/player/previous"
        handler.do_POST()
        self.assertEqual(handler.response[0], 200)
        self.assertTrue(handler.response[1]["boundary"])

    def test_seek_route_requires_position_and_updates_state(self) -> None:
        handler = _Handler()
        handler.music_api.player_state["currentMediaId"] = MEDIA_A
        handler.path = "/v1/music/player/seek"
        handler.payload = {"positionSeconds": 9.5}
        handler.do_POST()
        self.assertEqual(handler.response[0], 200)
        self.assertEqual(handler.response[1]["positionSeconds"], 9.5)

        handler = _Handler()
        handler.path = "/v1/music/player/seek"
        handler.payload = {}
        handler.do_POST()
        self.assertEqual(handler.response[0], 400)
        self.assertEqual(handler.response[1]["code"], "MUSIC_SEEK_POSITION_REQUIRED")

    def test_unrelated_routes_fall_through(self) -> None:
        handler = _Handler()
        handler.path = "/v1/music/player"
        handler.do_POST()
        self.assertTrue(handler.fallback_post)

    def test_production_handler_composes_music_player_mixin(self) -> None:
        source = Path(__file__).with_name("headless_api.py").read_text(encoding="utf-8")
        self.assertIn("from headless_music_player_http import HeadlessMusicPlayerHttpMixin", source)
        class_start = source.index("class GalaxyApiRequestHandler(")
        class_end = source.index("):", class_start)
        self.assertIn("HeadlessMusicPlayerHttpMixin", source[class_start:class_end])


if __name__ == "__main__":
    run_music_player_navigation_self_test()
    unittest.main()
