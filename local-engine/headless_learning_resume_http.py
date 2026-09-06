from __future__ import annotations

from urllib.parse import urlsplit

from headless_learning_api import HeadlessLearningApiError
from headless_learning_resume import resolve_headless_course_resume
from headless_service import _safe_detail


class HeadlessLearningResumeHttpMixin:
    """Authenticated, path-safe HTTP contract for deterministic course resume."""

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        prefix = "/v1/learning/courses/"
        suffix = "/resume"
        if not path.startswith(prefix) or not path.endswith(suffix):
            super().do_GET()
            return

        course_id = path[len(prefix) : -len(suffix)].strip("/")
        if not course_id or "/" in course_id:
            super().do_GET()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return

        learning_api = getattr(self, "learning_api", None)
        if learning_api is None:
            self._json(503, {"ok": False, "error": "learning api is unavailable"})
            return

        try:
            result = resolve_headless_course_resume(learning_api, course_id)
            self._json(200, {"ok": True, **result})
        except HeadlessLearningApiError as exc:
            self._json(
                exc.status,
                {"ok": False, "error": _safe_detail(exc), "code": exc.code},
            )
        except Exception:
            self._json(
                502,
                {
                    "ok": False,
                    "error": "course resume resolution failed",
                    "code": "LEARNING_COURSE_RESUME_FAILED",
                },
            )
