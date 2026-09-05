from __future__ import annotations

from urllib.parse import urlsplit

from course_providers import CourseProviderError, build_course_provider_plan, list_course_providers
from headless_service import HeadlessServiceError, _safe_detail


def _provider_plan(payload: dict) -> dict:
    return build_course_provider_plan(
        payload.get("sourceUrl"),
        provider=payload.get("provider", "auto"),
        browser=payload.get("browser", "none"),
        include_subtitles=payload.get("includeSubtitles", True),
    )


class HeadlessCourseProvidersHttpMixin:
    """Headless discovery, resolve and queue endpoints for course providers."""

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
        if path not in {
            "/v1/learning/providers/resolve",
            "/v1/learning/providers/download",
        }:
            super().do_POST()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            payload = self._read_json()
            plan = _provider_plan(payload)
            if path == "/v1/learning/providers/resolve":
                self._json(200, {"ok": True, "plan": plan})
                return

            job = self.runtime.submit(plan["enginePayload"])
            self._json(
                202,
                {
                    "ok": True,
                    "provider": plan["provider"],
                    "job": job.public_payload(),
                    "warnings": list(plan.get("warnings") or []),
                },
            )
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
            detail = _safe_detail(exc)
            queue_full = "queue" in detail.lower() and "full" in detail.lower()
            self._json(
                429 if queue_full else 400,
                {
                    "ok": False,
                    "error": detail,
                    "code": (
                        "LEARNING_COURSE_DOWNLOAD_QUEUE_FULL"
                        if queue_full
                        else "LEARNING_COURSE_DOWNLOAD_REJECTED"
                    ),
                },
            )
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})
