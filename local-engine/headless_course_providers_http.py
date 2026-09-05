from __future__ import annotations

from urllib.parse import urlsplit

from course_providers import CourseProviderError, build_course_provider_plan, list_course_providers
from headless_service import HeadlessServiceError, _safe_detail


class HeadlessCourseProvidersHttpMixin:
    """Headless discovery/resolve endpoints for production course providers."""

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path != "/v1/learning/providers":
            super().do_GET()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        self._json(200, {"ok": True, "providers": list_course_providers()})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path != "/v1/learning/providers/resolve":
            super().do_POST()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            payload = self._read_json()
            plan = build_course_provider_plan(
                payload.get("sourceUrl"),
                provider=payload.get("provider", "auto"),
                browser=payload.get("browser", "none"),
                include_subtitles=payload.get("includeSubtitles", True),
            )
            self._json(200, {"ok": True, "plan": plan})
        except CourseProviderError as exc:
            self._json(
                400,
                {
                    "ok": False,
                    "error": _safe_detail(exc),
                    "code": "LEARNING_COURSE_PROVIDER_INVALID",
                },
            )
        except HeadlessServiceError as exc:
            self._json(400, {"ok": False, "error": _safe_detail(exc)})
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})
