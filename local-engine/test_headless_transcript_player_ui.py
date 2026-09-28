from __future__ import annotations

import unittest
from pathlib import Path

from headless_web_dashboard import _DASHBOARD_ASSETS, _with_learning_assets


_ROOT = Path(__file__).with_name("web-dashboard")


class HeadlessTranscriptPlayerUiTests(unittest.TestCase):
    def test_player_assets_are_registered_and_injected(self) -> None:
        self.assertIn("/dashboard/transcript-player.js", _DASHBOARD_ASSETS)
        self.assertIn("/dashboard/transcript-player.css", _DASHBOARD_ASSETS)
        rendered = _with_learning_assets(b"<html><head></head><body></body></html>", "index.html")
        self.assertIn(b"/dashboard/transcript-player.css", rendered)
        self.assertIn(b"/dashboard/transcript-player.js", rendered)

    def test_transcript_rows_publish_safe_seek_metadata(self) -> None:
        script = (_ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("data-transcript-seek", script)
        self.assertIn("data-transcript-end", script)
        self.assertIn("data-transcript-media-id", script)
        self.assertIn('aria-label="Seek ', script)
        self.assertNotIn("Web Dashboard has no media streaming endpoint yet", script)

    def test_player_uses_opaque_ticket_and_html5_seek(self) -> None:
        script = (_ROOT / "transcript-player.js").read_text(encoding="utf-8")
        self.assertIn("/playback-ticket", script)
        self.assertIn("playbackPathPattern", script)
        self.assertIn("playbackPathPattern", script)
        self.assertIn("media.currentTime", script)
        self.assertIn("timeupdate", script)
        self.assertIn("syncActiveSegment", script)
        self.assertIn("scrollIntoView", script)
        self.assertIn("aria-current", script)
        self.assertIn("headers.Authorization = 'Bearer ' + token", script)
        self.assertNotIn("file://", script)
        self.assertNotIn("filePath", script)
        self.assertNotIn("localPath", script)
        self.assertNotIn("?token=", script)
        self.assertNotIn("?access_token=", script)

    def test_player_styles_keep_timestamp_target_accessible(self) -> None:
        stylesheet = (_ROOT / "transcript-player.css").read_text(encoding="utf-8")
        self.assertIn(".time-button[data-transcript-seek]{min-height:44px", stylesheet)
        self.assertIn(":focus-visible", stylesheet)
        self.assertIn(".segment.is-active", stylesheet)
        self.assertIn("@media(prefers-color-scheme:dark)", stylesheet)
        self.assertNotIn("@import", stylesheet)
        self.assertNotIn("http://", stylesheet)
        self.assertNotIn("https://", stylesheet)


if __name__ == "__main__":
    unittest.main()
