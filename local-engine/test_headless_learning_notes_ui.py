from __future__ import annotations

import unittest
from pathlib import Path

from headless_web_dashboard import _DASHBOARD_ASSETS, _with_learning_assets


_ROOT = Path(__file__).with_name("web-dashboard")


class HeadlessLearningNotesUiTests(unittest.TestCase):
    def test_notes_assets_are_registered_and_injected(self) -> None:
        self.assertIn("/dashboard/learning-notes.js", _DASHBOARD_ASSETS)
        self.assertIn("/dashboard/learning-notes.css", _DASHBOARD_ASSETS)
        rendered = _with_learning_assets(b"<html><head></head><body></body></html>", "index.html")
        self.assertIn(b"/dashboard/learning-notes.css", rendered)
        self.assertIn(b"/dashboard/learning-notes.js", rendered)

    def test_notes_ui_consumes_existing_learning_crud(self) -> None:
        script = (_ROOT / "learning-notes.js").read_text(encoding="utf-8")
        self.assertIn("/v1/learning/courses/${encodeURIComponent(courseId)}/resume", script)
        self.assertIn("/v1/learning/items/${encodeURIComponent(itemId)}/notes?limit=1000", script)
        self.assertIn("/v1/learning/items/${encodeURIComponent(itemId)}/notes", script)
        self.assertIn("/v1/learning/notes/${encodeURIComponent(noteId)}/delete", script)
        self.assertIn("timestampSeconds", script)
        self.assertIn("media.currentTime", script)
        self.assertIn("Save note", script)
        self.assertIn("No notes for this lecture yet.", script)
        self.assertIn("Loading timestamp notes…", script)

    def test_note_body_is_rendered_as_text_and_bearer_stays_in_headers(self) -> None:
        script = (_ROOT / "learning-notes.js").read_text(encoding="utf-8")
        self.assertIn("body.textContent = String(note?.body || '')", script)
        self.assertIn("headers.Authorization = `Bearer ${token}`", script)
        self.assertNotIn("?token=", script)
        self.assertNotIn("?access_token=", script)
        self.assertNotIn("localPath", script)
        self.assertNotIn("filePath", script)
        self.assertNotIn("cookieFile", script)
        self.assertNotIn("httpHeaders", script)
        self.assertNotIn("setInterval", script)

    def test_notes_ui_is_keyboard_and_touch_target_aware(self) -> None:
        script = (_ROOT / "learning-notes.js").read_text(encoding="utf-8")
        stylesheet = (_ROOT / "learning-notes.css").read_text(encoding="utf-8")
        self.assertIn("event.ctrlKey || event.metaKey", script)
        self.assertIn("textarea?.focus()", script)
        self.assertIn("aria-live", script)
        self.assertIn("aria-label", script)
        self.assertIn("min-height: 44px", stylesheet)
        self.assertIn(":focus-visible", stylesheet)
        self.assertIn("@media (hover: hover)", stylesheet)
        self.assertIn("@media (max-width: 760px)", stylesheet)
        self.assertNotIn("@import", stylesheet)
        self.assertNotIn("http://", stylesheet)
        self.assertNotIn("https://", stylesheet)


if __name__ == "__main__":
    unittest.main()
