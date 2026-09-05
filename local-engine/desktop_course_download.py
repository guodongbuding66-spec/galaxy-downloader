from __future__ import annotations

from pathlib import Path
from typing import Any

from course_download_coordinator import CourseDownloadCoordinator, CourseDownloadCoordinatorError
from headless_browser_cookies import install_headless_browser_cookie_support
from headless_course_metadata_tracking import install_headless_course_metadata_tracking
from headless_learning_api import HeadlessLearningApi
from headless_learning_structure import install_headless_learning_structure
from headless_output_tracking import install_headless_output_tracking
from headless_service import HeadlessRuntime
from managed_course_download import build_managed_course_plan, submit_managed_course_download


class DesktopCourseDownloadError(RuntimeError):
    pass


class DesktopCourseDownloadService:
    """Desktop lifecycle wrapper around the managed Course download core."""

    def __init__(
        self,
        download_root: Path,
        *,
        runtime=None,
        learning_api=None,
        coordinator=None,
    ) -> None:
        install_headless_browser_cookie_support()
        install_headless_output_tracking()
        install_headless_course_metadata_tracking()
        install_headless_learning_structure()

        self.download_root = Path(download_root).expanduser().resolve(strict=False)
        self._closed = False
        self._owns_runtime = runtime is None
        self.runtime = runtime or HeadlessRuntime(self.download_root)
        self.learning_api = learning_api or HeadlessLearningApi(self.download_root)
        self._owns_coordinator = coordinator is None
        self.coordinator = coordinator or CourseDownloadCoordinator(self.runtime, self.learning_api)

    def _ensure_open(self) -> None:
        if self._closed:
            raise DesktopCourseDownloadError("desktop course download service is closed")

    def submit(
        self,
        source_url: object,
        *,
        provider: object = "auto",
        browser: object = "none",
        include_subtitles: object = True,
        course_id: object = "",
        course_name: object = "",
    ) -> dict[str, Any]:
        self._ensure_open()
        plan = build_managed_course_plan(
            source_url,
            provider=provider,
            browser=browser,
            include_subtitles=include_subtitles,
        )
        submitted = submit_managed_course_download(
            self.learning_api,
            self.coordinator,
            plan,
            course_id=course_id,
            course_name=course_name,
        )
        return {
            "provider": submitted["provider"],
            "course": submitted["course"],
            "session": submitted["session"],
            "job": submitted["job"].public_payload(),
            "warnings": submitted["warnings"],
        }

    def status(self, job_id: object) -> dict[str, Any]:
        self._ensure_open()
        return self.coordinator.status(job_id)

    def cancel(self, job_id: object) -> dict[str, Any]:
        self._ensure_open()
        job = self.runtime.cancel(job_id)
        try:
            status = self.coordinator.status(job_id)
        except CourseDownloadCoordinatorError:
            status = {"session": None, "job": job.public_payload()}
        if status.get("job") is None:
            status["job"] = job.public_payload()
        return status

    def sync_now(self, job_id: object) -> dict[str, Any]:
        self._ensure_open()
        return self.coordinator.sync_now(job_id)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None
        if self._owns_coordinator:
            try:
                self.coordinator.close()
            except Exception as exc:
                first_error = exc
        if self._owns_runtime:
            try:
                self.runtime.stop()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise DesktopCourseDownloadError(str(first_error)) from first_error

    def __enter__(self) -> "DesktopCourseDownloadService":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
