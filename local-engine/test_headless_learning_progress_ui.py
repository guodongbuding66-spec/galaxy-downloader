from __future__ import annotations

import unittest
from pathlib import Path


_SCRIPT = Path(__file__).with_name("web-dashboard") / "learning-player.js"


class HeadlessLearningProgressUiTests(unittest.TestCase):
    def test_progress_uses_existing_authenticated_learning_endpoint(self) -> None:
        script = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn("/v1/learning/items/${encodeURIComponent(snapshot.itemId)}/progress", script)
        self.assertIn("method: 'POST'", script)
        self.assertIn("headers: authHeaders({ 'Content-Type': 'application/json' })", script)
        self.assertIn("progressSeconds: snapshot.seconds", script)
        self.assertIn("completed: snapshot.completed", script)

    def test_progress_is_throttled_and_flushes_on_meaningful_events(self) -> None:
        script = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn("PROGRESS_INTERVAL_SECONDS = 10", script)
        self.assertIn("distance < PROGRESS_INTERVAL_SECONDS", script)
        for event in ("'timeupdate'", "'seeked'", "'pause'", "'ended'"):
            self.assertIn(event, script)
        self.assertIn("queueProgress(false)", script)
        self.assertIn("queueProgress(false, { force: true })", script)
        self.assertIn("queueProgress(true, { force: true })", script)

    def test_completion_refreshes_shared_resume_contract(self) -> None:
        script = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn("async function completePlayback", script)
        self.assertIn("stopMedia({ save: false })", script)
        self.assertIn("state.resume = null", script)
        self.assertIn("await refreshCurrent()", script)
        self.assertIn("Lesson completed. Finding the next lesson", script)

    def test_page_exit_uses_keepalive_fetch_not_send_beacon(self) -> None:
        script = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn("keepalive: Boolean(keepalive)", script)
        self.assertIn("writeProgress(snapshot, { keepalive: true })", script)
        self.assertIn("visibilitychange", script)
        self.assertIn("beforeunload", script)
        self.assertNotIn("sendBeacon", script)
        self.assertIn("headers.Authorization = `Bearer ${token}`", script)

    def test_switching_course_or_view_saves_before_stopping_player(self) -> None:
        script = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn("nextCourseId !== state.courseId", script)
        self.assertIn("stopMedia()", script)
        self.assertIn("!navItem.matches('[data-learning-view]')", script)
        self.assertIn("if (save) void queueProgress(false, { force: true })", script)

    def test_progress_sync_still_does_not_reference_local_paths(self) -> None:
        script = _SCRIPT.read_text(encoding="utf-8")
        for private_field in ("localPath", "filePath", "relativePath", "cookieFile", "httpHeaders"):
            self.assertNotIn(private_field, script)
        self.assertNotIn("file://", script)


if __name__ == "__main__":
    unittest.main()
