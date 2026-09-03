from __future__ import annotations

import tempfile
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from music_workspace import (  # noqa: E402
    albums,
    artists,
    attach_lrc,
    clear_queue,
    enqueue,
    get_track,
    lyrics,
    most_played,
    parse_lrc,
    player_state,
    queue_items,
    recently_played,
    set_track_state,
    songs,
    sync_music_library,
    update_player_state,
    update_track_metadata,
)
from runtime_storage import run_runtime_storage_self_test  # noqa: E402


def run_test() -> None:
    assert parse_lrc("[00:01.50]Hello\n[01:02.003]World") == [
        {"time": 1.5, "text": "Hello"},
        {"time": 62.003, "text": "World"},
    ]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        data = root / "data"
        downloads = root / "downloads"
        state.mkdir()
        data.mkdir()
        downloads.mkdir()
        media_id = "a" * 32
        audio = downloads / "Artist - Song.mp3"
        audio.write_bytes(b"demo")
        item = {
            "id": media_id,
            "title": "Artist - Song",
            "fileName": audio.name,
            "mediaType": "audio",
            "available": True,
            "sourceHost": "example.com",
        }

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return state

            @staticmethod
            def data_dir() -> Path:
                return data

            @staticmethod
            def default_download_dir() -> Path:
                return downloads

        def fake_list(_engine, **kwargs):
            return [item] if int(kwargs.get("offset", 0)) == 0 else []

        with patch("music_workspace.list_media_items", side_effect=fake_list), patch(
            "music_workspace.resolve_media_item_path", return_value=audio.resolve()
        ):
            assert sync_music_library(Engine) == 1
            track = get_track(Engine, media_id)
            assert track["artist"] == "Artist"
            update_track_metadata(Engine, media_id, {"album": "Album", "year": 2026, "genre": "Demo"})
            assert albums(Engine)[0]["album"] == "Album"
            assert artists(Engine)[0]["artist"] == "Artist"
            set_track_state(Engine, media_id, favorite=True, increment_play=True, last_position=12.5)
            assert songs(Engine, favorites_only=True)[0]["favorite"] is True
            assert recently_played(Engine)[0]["mediaId"] == media_id
            assert most_played(Engine)[0]["playCount"] == 1
            lrc = root / "demo.lrc"
            lrc.write_text("[00:01.50]Hello\n[01:02.003]World", encoding="utf-8")
            assert attach_lrc(Engine, media_id, lrc) == 2
            assert lyrics(Engine, media_id)["synced"][0] == {"time": 1.5, "text": "Hello"}
            assert enqueue(Engine, [media_id]) == 1
            assert len(queue_items(Engine)) == 1
            state_payload = update_player_state(
                Engine,
                current_media_id=media_id,
                repeat_mode="all",
                shuffle=True,
                volume=0.7,
            )
            assert state_payload["repeatMode"] == "all" and state_payload["shuffle"] is True
            assert abs(player_state(Engine)["volume"] - 0.7) < 1e-9
            clear_queue(Engine)
            assert queue_items(Engine) == []

    run_runtime_storage_self_test()


if __name__ == "__main__":
    run_test()
    print("Music workspace and runtime migration self-tests passed")
