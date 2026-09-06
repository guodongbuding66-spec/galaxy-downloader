from __future__ import annotations

import unittest

from desktop_learning_navigation import navigation_target, section_display_text, subtitle_tracks_text


class DesktopLearningNavigationModelTests(unittest.TestCase):
    def test_subtitle_tracks_render_only_language_and_kind(self) -> None:
        rendered = subtitle_tracks_text(
            {
                "subtitleTracks": [
                    {"language": "en", "kind": "manual", "url": "https://cdn.example/?sig=SECRET"},
                    {"language": "zh-CN", "kind": "automatic", "path": "/private/sub.vtt"},
                    {"language": "en", "kind": "manual"},
                    {"language": "fr", "kind": "unknown"},
                ]
            }
        )
        self.assertEqual(rendered, "en 人工 · zh-CN 自动")
        self.assertNotIn("SECRET", rendered)
        self.assertNotIn("https://", rendered)
        self.assertNotIn("private", rendered.lower())

    def test_subtitle_tracks_handle_missing_or_malformed_data(self) -> None:
        self.assertEqual(subtitle_tracks_text({}), "—")
        self.assertEqual(subtitle_tracks_text({"subtitleTracks": "en"}), "—")
        self.assertEqual(subtitle_tracks_text({"subtitleTracks": [{"language": "", "kind": "manual"}]}), "—")

    def test_section_label_includes_completion_summary(self) -> None:
        self.assertEqual(
            section_display_text({"title": "Python Basics", "itemCount": 5, "completedCount": 2}, 0),
            "Python Basics · 2/5",
        )
        self.assertEqual(section_display_text({"title": "Intro"}, 1), "Intro")

    def test_navigation_target_accepts_only_public_item_ids(self) -> None:
        previous_id = "a" * 32
        next_id = "b" * 32
        item = {
            "previousItemId": previous_id,
            "nextItemId": next_id,
            "providerItemId": "udemy:asset:SECRET",
        }
        self.assertEqual(navigation_target(item, "previous"), previous_id)
        self.assertEqual(navigation_target(item, "next"), next_id)
        self.assertEqual(navigation_target(item, "sideways"), "")
        self.assertEqual(navigation_target({"nextItemId": "udemy:asset:SECRET"}, "next"), "")


if __name__ == "__main__":
    unittest.main()
