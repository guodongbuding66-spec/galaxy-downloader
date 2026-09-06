from __future__ import annotations

from urllib.parse import urlsplit

from course_download_coordinator import CourseDownloadCoordinatorError
from course_providers import CourseProviderError, list_course_providers, resolve_course_provider
from headless_learning_api import HeadlessLearningApiError
from headless_service import HeadlessServiceError, _safe_detail
from managed_course_download import build_managed_course_plan, submit_managed_course_download


def _provider_plan(payload: dict) -> dict:
    return build_managed_course_plan(
        payload.get("sourceUrl"),
        provider=payload.get("provider", "auto"),
        browser=payload.get("browser", "none"),
        include_subtitles=payload.get("includeSubtitles", True),
        include_attachments=payload.get("includeAttachments", True),
    )


def _provider_resolution(payload: dict) -> dict:
    return resolve_course_provider(
        payload.get("sourceUrl"),
        provider=payload.get("provider", "auto"),
    )


def _course_download_coordinator(handler):
    server = getattr(handler, "server", None)
    return getattr(server, "course_download_coordinator", None)


class HeadlessCourseProvidersHttpMixin:
    """Headless discovery, resolve and managed download endpoints for course providers."""

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/v1/learning/providers":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            self._json(200, {"ok": True, "providers": list_course_providers()})
            return

        prefix = "/v1/learning/providers/downloads/"
        if path.startswith(prefix):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            coordinator = _course_download_coordinator(self)
            if coordinator is None:
                self._json(503, {"ok": False, "error": "course download coordinator is unavailable"})
                return
            job_id = path[len(prefix) :].strip("/")
            try:
                status = coordinator.status(job_id)
                self._json(200, {"ok": True, **status})
            except CourseDownloadCoordinatorError as exc:
                self._json(
                    404,
                    {
                        "ok": False,
                        "error": _safe_detail(exc),
                        "code": "LEARNING_COURSE_DOWNLOAD_NOT_FOUND",
                    },
                )
            except Exception as exc:
                self._json(502, {"ok": False, "error": _safe_detail(exc)})
            return

        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        sync_prefix = "/v1/learning/providers/downloads/"
        sync_suffix = "/sync"
        if path.startswith(sync_prefix) and path.endswith(sync_suffix):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            coordinator = _course_download_coordinator(self)
            if coordinator is None:
                self._json(503, {"ok": False, "error": "course download coordinator is unavailable"})
                return
            job_id = path[len(sync_prefix) : -len(sync_suffix)].strip("/")
            try:
                result = coordinator.sync_now(job_id)
                self._json(200, {"ok": True, **result})
            except CourseDownloadCoordinatorError as exc:
                detail = _safe_detail(exc)
                missing = "not found" in detail.lower()
                self._json(
                    404 if missing else 409,
                    {
                        "ok": False,
                        "error": detail,
                        "code": (
                            "LEARNING_COURSE_DOWNLOAD_NOT_FOUND"
                            if missing
                            else "LEARNING_COURSE_SYNC_REJECTED"
                        ),
                    },
                )
            except Exception as exc:
                self._json(502, {"ok": False, "error": _safe_detail(exc)})
            return

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
            if path == "/v1/learning/providers/resolve":
                resolution = _provider_resolution(payload)
                self._json(200, {"ok": True, "resolution": resolution})
                return

            plan = _provider_plan(payload)
            learning_api = getattr(self, "learning_api", None)
            coordinator = _course_download_coordinator(self)
            if learning_api is None or coordinator is None:
                self._json(503, {"ok": False, "error": "managed course downloads are unavailable"})
                return

            submitted = submit_managed_course_download(
                learning_api,
                coordinator,
                plan,
                course_id=payload.get("courseId", ""),
                course_name=payload.get("courseName", ""),
            )
            self._json(
                202,
                {
                    "ok": True,
                    "provider": submitted["provider"],
                    "course": submitted["course"],
                    "session": submitted["session"],
                    "job": submitted["job"].public_payload(),
                    "warnings": submitted["warnings"],
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
        except HeadlessLearningApiError as exc:
            self._json(exc.status, {"ok": False, "error": _safe_detail(exc), "code": exc.code})
        except CourseDownloadCoordinatorError as exc:
            detail = _safe_detail(exc)
            status = 404 if "not found" in detail.lower() else 409
            self._json(status, {"ok": False, "error": detail, "code": "LEARNING_COURSE_DOWNLOAD_REJECTED"})
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
