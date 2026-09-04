from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiServer  # noqa: E402
from headless_media_api import HeadlessMediaApi, HeadlessMediaContext  # noqa: E402
from headless_music_api import (  # noqa: E402
    HeadlessMusicApi,
    HeadlessMusicContext,
    run_headless_music_api_self_test,
)
from headless_service import HeadlessRuntime  # noqa: E402
from media_library import list_media_items, sync_media_library  # noqa: E402


def _request_json(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, method=method, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=4) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _http_error_json(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    try:
        _request_json(url, method=method, payload=payload)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    raise AssertionError(f"expected HTTP error for {method} {url}")


def _assert_no_paths(payload: dict, *roots: Path) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "coverPath" not in serialized
    assert "filePath" not in serialized
    assert "managedPath" not in serialized
    for root in roots:
        assert str(root) not in serialized


def run() -> None:
    run_headless_music_api_self_test()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        program = root / "program"
        for target in (downloads, state, data, program):
            target.mkdir()

        audio = downloads / "HTTP Artist - HTTP Song.mp3"
        audio.write_bytes(b"music")
        music_context = HeadlessMusicContext(program, data, state, downloads)
        history = [
            {
                "state": "completed",
                "filePath": str(audio),
                "fileName": audio.name,
                "label": "HTTP Artist - HTTP Song",
                "durationSeconds": 210,
                "sourceUrl": "https://example.com/music/http-song",
                "finishedAt": "2026-09-04T00:00:00Z",
            }
        ]
        assert sync_media_library(music_context, history) == 1
        media_id = list_media_items(music_context, media_type="audio", limit=1)[0]["id"]
        music_api = HeadlessMusicApi(downloads, context=music_context)

        media_context = HeadlessMediaContext(program, state, downloads)
        media_api = HeadlessMediaApi(downloads, context=media_context)
        runtime = HeadlessRuntime(downloads, max_queue_size=2)
        server = GalaxyApiServer(
            ("127.0.0.1", 0),
            runtime,
            "",
            "127.0.0.1",
            media_api,
            music_api=music_api,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            code, status = _request_json(base + "/v1/status")
            assert code == 200 and status["ok"] is True and status["protocol"] == 2

            code, synced = _request_json(base + "/v1/music/sync", method="POST")
            assert code == 200 and synced["synced"] == 1

            code, listed = _request_json(base + "/v1/music/songs?limit=10")
            assert code == 200 and listed["songs"][0]["mediaId"] == media_id
            _assert_no_paths(listed, downloads, state, data)

            code, detail = _request_json(base + f"/v1/music/songs/{media_id}")
            assert code == 200 and detail["song"]["mediaId"] == media_id
            _assert_no_paths(detail, downloads, state, data)

            code, metadata = _request_json(
                base + f"/v1/music/songs/{media_id}/metadata",
                method="POST",
                payload={
                    "album": "HTTP Album",
                    "genre": "Test",
                    "year": 2026,
                    "coverPath": str(root / "must-not-be-accepted.jpg"),
                },
            )
            assert code == 200 and metadata["song"]["album"] == "HTTP Album"
            _assert_no_paths(metadata, downloads, state, data, root)

            code, song_state = _request_json(
                base + f"/v1/music/songs/{media_id}/state",
                method="POST",
                payload={"favorite": True, "lastPosition": 25.25, "incrementPlay": True},
            )
            assert code == 200 and song_state["song"]["favorite"] is True
            assert song_state["song"]["playCount"] == 1
            _assert_no_paths(song_state, downloads, state, data)

            code, favorites = _request_json(base + "/v1/music/songs?favoritesOnly=true")
            assert code == 200 and favorites["favoritesOnly"] is True
            assert favorites["songs"][0]["mediaId"] == media_id

            code, albums = _request_json(base + "/v1/music/albums")
            assert code == 200 and albums["albums"][0]["album"] == "HTTP Album"
            code, artists = _request_json(base + "/v1/music/artists")
            assert code == 200 and artists["artists"][0]["artist"] == "HTTP Artist"
            code, recent = _request_json(base + "/v1/music/recent")
            assert code == 200 and recent["songs"][0]["mediaId"] == media_id
            code, most_played = _request_json(base + "/v1/music/most-played")
            assert code == 200 and most_played["songs"][0]["playCount"] == 1

            code, lyric_payload = _request_json(base + f"/v1/music/songs/{media_id}/lyrics")
            assert code == 200 and lyric_payload["lyrics"]["kind"] == "none"
            _assert_no_paths(lyric_payload, downloads, state, data)

            code, queued = _request_json(
                base + "/v1/music/queue",
                method="POST",
                payload={"mediaIds": [media_id], "replace": True},
            )
            assert code == 200 and queued["count"] == 1
            queue_id = queued["queue"][0]["id"]
            _assert_no_paths(queued, downloads, state, data)

            code, queue_list = _request_json(base + "/v1/music/queue")
            assert code == 200 and queue_list["queue"][0]["id"] == queue_id
            _assert_no_paths(queue_list, downloads, state, data)

            code, moved = _request_json(
                base + f"/v1/music/queue/{queue_id}/move",
                method="POST",
                payload={"position": 1},
            )
            assert code == 200 and moved["count"] == 1

            code, player = _request_json(
                base + "/v1/music/player",
                method="POST",
                payload={"currentMediaId": media_id, "repeatMode": "all", "shuffle": True, "volume": 0.65},
            )
            assert code == 200 and player["player"]["repeatMode"] == "all"
            assert player["player"]["currentMediaId"] == media_id
            code, player_get = _request_json(base + "/v1/music/player")
            assert code == 200 and player_get["player"]["volume"] == 0.65

            code, invalid_position = _http_error_json(
                base + f"/v1/music/songs/{media_id}/state",
                method="POST",
                payload={"lastPosition": "nan"},
            )
            assert code == 400 and invalid_position["code"] == "MUSIC_INVALID_REQUEST"

            code, invalid_volume = _http_error_json(
                base + "/v1/music/player",
                method="POST",
                payload={"volume": 2},
            )
            assert code == 400 and invalid_volume["code"] == "MUSIC_INVALID_REQUEST"

            code, invalid_favorites = _http_error_json(base + "/v1/music/songs?favoritesOnly=maybe")
            assert code == 400 and invalid_favorites["ok"] is False

            missing = "0" * 32
            code, missing_song = _http_error_json(base + f"/v1/music/songs/{missing}")
            assert code == 404 and missing_song["code"] in {"MUSIC_MEDIA_NOT_FOUND", "MUSIC_TRACK_NOT_FOUND"}

            code, removed = _request_json(
                base + f"/v1/music/queue/{queue_id}/delete",
                method="POST",
            )
            assert code == 200 and removed["deleted"] is True
            code, cleared = _request_json(base + "/v1/music/queue/clear", method="POST")
            assert code == 200 and cleared["count"] == 0
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()


if __name__ == "__main__":
    run()
    print("Headless Music API self-test passed")
