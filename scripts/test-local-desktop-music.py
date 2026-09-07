from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_hooks import registered_after_build_ui_hooks
from desktop_music import (
    MAX_LYRICS_DISPLAY_ROWS,
    _format_album,
    _format_artist,
    _format_timestamp,
    _format_track,
    _render_lyrics_payload,
    install_desktop_music,
    run_desktop_music_self_test,
)


class FakeWindow:
    pass


class FakeEngine:
    EngineWindow = FakeWindow


def test_formatters() -> None:
    assert _format_album({"album": "Discovery", "albumArtist": "Daft Punk", "year": 2001, "trackCount": 14}) == (
        "Discovery — Daft Punk · 2001 · 14 首"
    )
    assert _format_album({}) == "Unknown Album — Unknown Artist · 0 首"
    assert _format_artist({"artist": "Daft Punk", "albumCount": 2, "trackCount": 31}) == (
        "Daft Punk · 2 张专辑 · 31 首"
    )
    assert _format_artist({}) == "Unknown Artist · 0 首"
    assert _format_track({"artist": "Artist", "title": "Track", "favorite": True}) == "★ Artist — Track"
    assert _format_track({"artist": "Artist", "title": "Track", "playCount": 7}, show_favorite=False, show_plays=True) == (
        "Artist — Track · 播放 7 次"
    )
    assert _format_timestamp(65.2) == "01:05"
    assert _format_timestamp(3661) == "1:01:01"
    assert _format_timestamp("bad") == "00:00"


def test_lyrics_renderer() -> None:
    text, kind = _render_lyrics_payload(
        {"lyrics": {"kind": "lrc", "synced": [{"time": 1.5, "text": "Line one"}, {"time": 65, "text": "Line two"}]}}
    )
    assert kind == "lrc"
    assert text == "[00:01]  Line one\n[01:05]  Line two"

    text, kind = _render_lyrics_payload({"lyrics": {"kind": "embedded", "synced": [], "text": "Plain lyrics"}})
    assert kind == "embedded"
    assert text == "Plain lyrics"

    text, kind = _render_lyrics_payload({"lyrics": {"kind": "none", "synced": [], "text": ""}})
    assert kind == "none"
    assert text == "暂无歌词"

    oversized = [{"time": index, "text": f"line-{index}"} for index in range(MAX_LYRICS_DISPLAY_ROWS + 2)]
    text, kind = _render_lyrics_payload({"lyrics": {"kind": "lrc", "synced": oversized}})
    assert kind == "lrc"
    assert f"仅显示前 {MAX_LYRICS_DISPLAY_ROWS} 行" in text
    assert "line-5001" not in text


def run_test() -> None:
    install_desktop_music(FakeEngine)
    assert getattr(FakeWindow, "_galaxy_desktop_music_installed", False)
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-music") == 1
    install_desktop_music(FakeEngine)
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-music") == 1
    test_formatters()
    test_lyrics_renderer()
    run_desktop_music_self_test()


if __name__ == "__main__":
    run_test()
    print("Desktop Music self-test passed")
