from __future__ import annotations

import unittest
from pathlib import Path

from headless_web_dashboard import _DASHBOARD_ASSETS, _with_learning_assets


_ROOT = Path(__file__).with_name("web-dashboard")


class HeadlessLearningPlayerUiTests(unittest.TestCase):
    def test_player_assets_are_registered_and_injected(self) -> None:
        self.assertIn("/dashboard/learning-player.js", _DASHBOARD_ASSETS)
        self.assertIn("/dashboard/learning-player.css", _DASHBOARD_ASSETS)
        rendered = _with_learning_assets(b"<html><head></head><body></body></html>", "index.html")
        self.assertIn(b"/dashboard/learning-player.css", rendered)
        self.assertIn(b"/dashboard/learning-player.js", rendered)

    def test_player_consumes_shared_resume_and_ticket_contracts(self) -> None:
        script = (_ROOT / "learning-player.js").read_text(encoding="utf-8")
        self.assertIn("/v1/learning/courses/${encodeURIComponent(courseId)}/resume", script)
        self.assertIn("/v1/learning/media/${encodeURIComponent(mediaId)}/playback-ticket", script)
        self.assertIn("playback.url", script)
        self.assertIn("media.src = playbackUrl", script)
        self.assertIn("loadedmetadata", script)
        self.assertIn("media.currentTime", script)
        for state in ("resume", "start", "completed", "empty"):
            self.assertIn(state, script)
        for label in ("Continue learning", "Continue", "Start course", "Completed", "Unavailable"):
            self.assertIn(label, script)

    def test_player_does_not_expose_paths_or_put_bearer_in_media_url(self) -> None:
        script = (_ROOT / "learning-player.js").read_text(encoding="utf-8")
        for private_field in ("localPath", "filePath", "relativePath", "trackingId", "cookieFile", "httpHeaders"):
            self.assertNotIn(private_field, script)
        self.assertNotIn("file://", script)
        self.assertNotIn("?token=", script)
        self.assertNotIn("?access_token=", script)
        self.assertNotIn("Authorization =", script)
        self.assertIn("headers.Authorization = `Bearer ${token}`", script)
        self.assertIn("playbackPathPattern", script)
        self.assertNotIn("https://cdn.", script)

    def test_player_styles_are_local_and_responsive(self) -> None:
        stylesheet = (_ROOT / "learning-player.css").read_text(encoding="utf-8")
        self.assertIn(".learning-player-panel", stylesheet)
        self.assertIn(".learning-player-media", stylesheet)
        self.assertIn("@media (max-width: 760px)", stylesheet)
        self.assertNotIn("@import", stylesheet)
        self.assertNotIn("http://", stylesheet)
        self.assertNotIn("https://", stylesheet)


if __name__ == "__main__":
    unittest.main()
