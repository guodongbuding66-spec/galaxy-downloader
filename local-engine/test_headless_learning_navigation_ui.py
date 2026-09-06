from __future__ import annotations

import unittest
from pathlib import Path

from headless_web_dashboard import _DASHBOARD_ASSETS, _with_learning_assets


_ROOT = Path(__file__).with_name("web-dashboard")


class HeadlessLearningNavigationUiTests(unittest.TestCase):
    def test_navigation_assets_are_registered_and_injected(self) -> None:
        self.assertIn("/dashboard/learning-navigation.js", _DASHBOARD_ASSETS)
        self.assertIn("/dashboard/learning-navigation.css", _DASHBOARD_ASSETS)
        rendered = _with_learning_assets(b"<html><head></head><body></body></html>", "index.html")
        self.assertIn(b"/dashboard/learning-navigation.css", rendered)
        self.assertIn(b"/dashboard/learning-navigation.js", rendered)

    def test_navigation_script_uses_structured_public_fields_only(self) -> None:
        script = (_ROOT / "learning-navigation.js").read_text(encoding="utf-8")
        for public_field in (
            "subtitleTracks",
            "previousItemId",
            "nextItemId",
            "courseItemIndex",
            "completedCount",
            "itemCount",
        ):
            self.assertIn(public_field, script)
        for label in ("Chapter navigation & subtitles", "Manual", "Auto", "Previous", "Next"):
            self.assertIn(label, script)
        for private_field in (
            "providerItemId",
            "relativePath",
            "trackingId",
            "cookieFile",
            "httpHeaders",
            "providerCourseId",
            "providerLectureId",
        ):
            self.assertNotIn(private_field, script)
        self.assertNotIn("https://cdn.", script)

    def test_navigation_styles_remain_local(self) -> None:
        stylesheet = (_ROOT / "learning-navigation.css").read_text(encoding="utf-8")
        self.assertIn(".learning-chapter-nav", stylesheet)
        self.assertIn(".learning-subtitle-badge", stylesheet)
        self.assertNotIn("@import", stylesheet)
        self.assertNotIn("http://", stylesheet)
        self.assertNotIn("https://", stylesheet)


if __name__ == "__main__":
    unittest.main()
