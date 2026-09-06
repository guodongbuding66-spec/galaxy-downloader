from __future__ import annotations

from urllib.parse import urlsplit

from course_attachment_download_service import CourseAttachmentDownloadServiceError
from headless_browser_cookies import HeadlessBrowserCookieError
from headless_service import _safe_detail


def _attachment_download_service(handler):
    server = getattr(handler, "server", None)
    return getattr(server, "course_attachment_download_service", None)


def _attachment_error(handler, exc: Exception) -> None:
    detail = _safe_detail(exc, 360)
    lowered = detail.lower()
    if "not found" in lowered:
        status = 404
        code = "LEARNING_ATTACHMENT_DOWNLOAD_NOT_FOUND"
    elif "queue" in lowered and "full" in lowered:
        status = 429
        code = "LEARNING_ATTACHMENT_DOWNLOAD_QUEUE_FULL"
    elif "closed" in lowered or "unavailable" in lowered:
        status = 503
        code = "LEARNING_ATTACHMENT_DOWNLOAD_UNAVAILABLE"
    elif "cannot" in lowered or "state" in lowered:
        status = 409
        code = "LEARNING_ATTACHMENT_DOWNLOAD_CONFLICT"
    else:
        status = 400
        code = "LEARNING_ATTACHMENT_DOWNLOAD_REJECTED"
    handler._json(status, {"ok": False, "error": detail, "code": code})


class HeadlessCourseAttachmentsHttpMixin:
    """Authenticated public contract for bounded Course attachment downloads."""

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        prefix = "/v1/learning/attachments/downloads/"
        if not path.startswith(prefix):
            super().do_GET()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        service = _attachment_download_service(self)
        if service is None:
            self._json(
                503,
                {
                    "ok": False,
                    "error": "course attachment download service is unavailable",
                    "code": "LEARNING_ATTACHMENT_DOWNLOAD_UNAVAILABLE",
                },
            )
            return
        job_id = path[len(prefix) :].strip("/")
        if not job_id or "/" in job_id:
            super().do_GET()
            return
        try:
            job = service.status(job_id)
            self._json(200, {"ok": True, "job": job})
        except CourseAttachmentDownloadServiceError as exc:
            _attachment_error(self, exc)
        except Exception:
            self._json(
                502,
                {
                    "ok": False,
                    "error": "course attachment status failed",
                    "code": "LEARNING_ATTACHMENT_DOWNLOAD_FAILED",
                },
            )

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/v1/learning/attachments/download":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            service = _attachment_download_service(self)
            if service is None:
                self._json(
                    503,
                    {
                        "ok": False,
                        "error": "course attachment download service is unavailable",
                        "code": "LEARNING_ATTACHMENT_DOWNLOAD_UNAVAILABLE",
                    },
                )
                return
            try:
                payload = self._read_json()
                job = service.submit(
                    payload.get("attachmentId"),
                    browser=payload.get("browser", "none"),
                )
                self._json(202, {"ok": True, "job": job})
            except (CourseAttachmentDownloadServiceError, HeadlessBrowserCookieError) as exc:
                _attachment_error(self, exc)
            except Exception:
                self._json(
                    502,
                    {
                        "ok": False,
                        "error": "course attachment download submission failed",
                        "code": "LEARNING_ATTACHMENT_DOWNLOAD_FAILED",
                    },
                )
            return

        prefix = "/v1/learning/attachments/downloads/"
        suffix = "/cancel"
        if path.startswith(prefix) and path.endswith(suffix):
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            service = _attachment_download_service(self)
            if service is None:
                self._json(
                    503,
                    {
                        "ok": False,
                        "error": "course attachment download service is unavailable",
                        "code": "LEARNING_ATTACHMENT_DOWNLOAD_UNAVAILABLE",
                    },
                )
                return
            job_id = path[len(prefix) : -len(suffix)].strip("/")
            try:
                job = service.cancel(job_id)
                self._json(200, {"ok": True, "job": job})
            except CourseAttachmentDownloadServiceError as exc:
                _attachment_error(self, exc)
            except Exception:
                self._json(
                    502,
                    {
                        "ok": False,
                        "error": "course attachment cancellation failed",
                        "code": "LEARNING_ATTACHMENT_DOWNLOAD_FAILED",
                    },
                )
            return

        super().do_POST()
