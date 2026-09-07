from __future__ import annotations

import unittest
from pathlib import Path

from headless_web_dashboard import _with_learning_assets


ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "web-dashboard"
JS_PATH = DASHBOARD / "music-player.js"
CSS_PATH = DASHBOARD / "music-player.css"
DASHBOARD_SERVER_PATH = ROOT / "headless_web_dashboard.py"


class MusicPlayerUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = JS_PATH.read_text(encoding="utf-8")
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.server = DASHBOARD_SERVER_PATH.read_text(encoding="utf-8")

    def test_dashboard_serves_and_injects_music_assets_once(self) -> None:
        self.assertIn('"/dashboard/music-player.js": ("music-player.js", "text/javascript; charset=utf-8")', self.server)
        self.assertIn('"/dashboard/music-player.css": ("music-player.css", "text/css; charset=utf-8")', self.server)
        source = b"<html><head></head><body></body></html>"
        first = _with_learning_assets(source, "index.html").decode("utf-8")
        second = _with_learning_assets(first.encode("utf-8"), "index.html").decode("utf-8")
        self.assertEqual(second.count('/dashboard/music-player.css'), 1)
        self.assertEqual(second.count('/dashboard/music-player.js'), 1)

    def test_music_view_is_a_real_product_entry(self) -> None:
        for contract in (
            "data.musicView = 'music'",
            "Music Library",
            "Now Playing",
            "Favorites only",
            "Sync Library",
            "musicQueue",
            "musicLyrics",
            '<audio id="musicAudio"',
            'controls preload="metadata"',
        ):
            self.assertIn(contract, self.js)

    def test_player_uses_existing_bounded_music_contracts(self) -> None:
        required = (
            "/v1/music/songs?",
            "/v1/music/queue",
            "/v1/music/player",
            "/v1/music/player/seek",
            "/v1/music/player/${direction}",
            "/v1/music/media/${encodeURIComponent(id)}/playback-ticket",
            "/v1/music/songs/${encodeURIComponent(id)}/lyrics",
            "/v1/music/songs/${encodeURIComponent(id)}/state",
        )
        for value in required:
            self.assertIn(value, self.js)
        self.assertIn("playbackPathPattern", self.js)
        self.assertIn("/v1/music/playback/", self.js)

    def test_bearer_token_never_enters_playback_url_or_query(self) -> None:
        self.assertIn("sessionStorage.getItem('galaxy.headless.token')", self.js)
        self.assertIn("headers.Authorization = `Bearer ${token}`", self.js)
        forbidden = (
            "?token=",
            "&token=",
            "access_token=",
            "authToken=",
            "localPath",
            "filePath",
            "cookieFile",
            "httpHeaders",
        )
        for value in forbidden:
            self.assertNotIn(value, self.js)
        self.assertNotIn("Bearer ${token}` +", self.js)
        self.assertNotIn("playback.url +", self.js)

    def test_user_content_is_escaped_and_lyrics_use_text_content(self) -> None:
        self.assertIn("const esc =", self.js)
        self.assertIn("esc(song.title", self.js)
        self.assertIn("esc(song.artist", self.js)
        self.assertIn("node.textContent =", self.js)
        self.assertNotIn("musicLyrics').innerHTML", self.js)

    def test_playback_progress_and_transport_are_state_safe(self) -> None:
        self.assertIn("PROGRESS_INTERVAL_SECONDS = 10", self.js)
        self.assertIn("await queueProgress({ force: true })", self.js)
        self.assertIn("keepalive: Boolean(keepalive)", self.js)
        self.assertIn("if (state.loading || !['previous', 'next'].includes(direction)) return", self.js)
        self.assertIn("state.loading = false", self.js)
        self.assertIn("if (song) await prepareSong(song", self.js)
        self.assertIn("repeatMode", self.js)
        self.assertIn("shuffle", self.js)
        self.assertIn("volume", self.js)
        self.assertNotIn("setInterval(", self.js)

    def test_ticket_recovery_is_bounded(self) -> None:
        self.assertIn("state.recoveryAttempts >= 1", self.js)
        self.assertIn("state.recoveryAttempts += 1", self.js)
        self.assertIn("Playback stream refreshed.", self.js)

    def test_accessibility_and_responsive_contract(self) -> None:
        for value in (
            'aria-live="polite"',
            'aria-label="Playback controls"',
            'aria-pressed="${song.favorite ? \'true\' : \'false\'}"',
            ":focus-visible",
            "min-height:44px",
            "@media(max-width:900px)",
            "@media(max-width:620px)",
            "@media(max-width:380px)",
            "@media(hover:hover)",
            "@media(prefers-color-scheme:dark)",
        ):
            self.assertIn(value, self.js if value.startswith("aria-") else self.css)

    def test_assets_do_not_widen_dashboard_csp(self) -> None:
        self.assertIn("default-src 'self'", self.server)
        self.assertIn("connect-src 'self'", self.server)
        self.assertIn("object-src 'none'", self.server)
        self.assertIn("frame-ancestors 'none'", self.server)
        self.assertNotIn("unsafe-inline", self.server)
        self.assertNotIn("unsafe-eval", self.server)


if __name__ == "__main__":
    unittest.main()
