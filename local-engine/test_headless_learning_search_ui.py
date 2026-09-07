from __future__ import annotations

import unittest
from pathlib import Path

from headless_web_dashboard import _DASHBOARD_ASSETS, _with_learning_assets


_ROOT = Path(__file__).with_name("web-dashboard")


class HeadlessLearningSearchUiTests(unittest.TestCase):
    def test_search_assets_are_registered_and_injected(self) -> None:
        self.assertIn("/dashboard/learning-search.js", _DASHBOARD_ASSETS)
        self.assertIn("/dashboard/learning-search.css", _DASHBOARD_ASSETS)
        rendered = _with_learning_assets(b"<html><head></head><body></body></html>", "index.html")
        self.assertIn(b"/dashboard/learning-search.css", rendered)
        self.assertIn(b"/dashboard/learning-search.js", rendered)

    def test_search_is_scoped_to_section_and_lecture_titles(self) -> None:
        script = (_ROOT / "learning-search.js").read_text(encoding="utf-8")
        self.assertIn(".learning-section-head strong", script)
        self.assertIn(".learning-lecture", script)
        self.assertIn("lecture.querySelector('strong')", script)
        self.assertIn("section.hidden = !showSection", script)
        self.assertIn("lecture.hidden = !matches", script)
        self.assertIn("No matching lectures.", script)
        self.assertNotIn("fetch(", script)
        self.assertNotIn("setInterval", script)

    def test_search_reapplies_after_course_render_and_is_keyboard_accessible(self) -> None:
        script = (_ROOT / "learning-search.js").read_text(encoding="utf-8")
        self.assertIn("MutationObserver", script)
        self.assertIn("[data-learning-course]", script)
        self.assertIn("event.key === 'Escape'", script)
        self.assertIn("input.focus()", script)
        self.assertIn("aria-describedby", script)
        self.assertIn("aria-live", script)
        self.assertIn("role', 'status'", script)

    def test_search_styles_keep_focus_touch_and_mobile_states(self) -> None:
        stylesheet = (_ROOT / "learning-search.css").read_text(encoding="utf-8")
        self.assertIn("min-height: 44px", stylesheet)
        self.assertIn(":focus-visible", stylesheet)
        self.assertIn("[hidden]", stylesheet)
        self.assertIn("@media (max-width: 760px)", stylesheet)
        self.assertNotIn("@import", stylesheet)
        self.assertNotIn("http://", stylesheet)
        self.assertNotIn("https://", stylesheet)


if __name__ == "__main__":
    unittest.main()
