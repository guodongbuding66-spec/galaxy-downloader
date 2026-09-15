from __future__ import annotations

import queue
import threading
from contextlib import suppress
from typing import Any

from course_download_sessions import (
    CourseDownloadSessionError,
    course_download_session,
    discard_course_download_outputs,
    mark_course_download_sync_failed,
    register_course_download_session,
    sync_course_download_outputs,
)
from headless_output_tracking import clear_output_tracking, new_output_tracking_id
from hotmart_course_provider import (
    install_headless_hotmart_authorization,
    register_hotmart_download_authorization,
    resolve_authorized_hotmart_media,
    revoke_hotmart_download_authorization,
)

_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})


class CourseDownloadCoordinatorError(RuntimeError):
    pass


class CourseDownloadCoordinator:
    """Bind provider downloads to Course Workspace and reconcile terminal jobs."""

    def __init__(self, runtime, learning_api, *, hotmart_resolver=None) -> None:
        if runtime is None or learning_api is None:
            raise CourseDownloadCoordinatorError("course download coordinator requires runtime and learning api")
        # Install after the normal browser/output/metadata layers have been
        # composed by Headless/Desktop startup. The wrapper activates only when
        # a valid process-local Hotmart authorization token is present.
        install_headless_hotmart_authorization()
        self.runtime = runtime
        self.learning_api = learning_api
        self._hotmart_resolver = hotmart_resolver or resolve_authorized_hotmart_media
        self._hotmart_tokens: dict[str, str] = {}
        self._stop = threading.Event()
        self._subscriber_id, self._channel = runtime.events.subscribe()
        self._thread = threading.Thread(
            target=self._run,
            name="GalaxyCourseDownloadCoordinator",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        with suppress(Exception):
            self.runtime.events.unsubscribe(self._subscriber_id)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        for token in list(self._hotmart_tokens.values()):
            with suppress(Exception):
                revoke_hotmart_download_authorization(token)
        self._hotmart_tokens.clear()

    def _session(self, job_id: object) -> dict[str, Any] | None:
        try:
            return course_download_session(job_id)
        except CourseDownloadSessionError as exc:
            raise CourseDownloadCoordinatorError(str(exc)) from exc

    def _prepare_hotmart_payload(self, source_url: str, engine_payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if engine_payload.get("_hotmartResolveAuthorizedMedia") is not True:
            raise CourseDownloadCoordinatorError("Hotmart course plan is missing the authorized-media resolver marker")
        browser = str(engine_payload.get("browser") or "none").strip().lower()
        resolved = self._hotmart_resolver(source_url, browser)
        if not isinstance(resolved, dict):
            raise CourseDownloadCoordinatorError("Hotmart authorized-media resolver returned an invalid result")
        media_url = str(resolved.get("mediaUrl") or "").strip()
        referer = str(resolved.get("referer") or source_url).strip()
        resolved_browser = str(resolved.get("browser") or browser).strip().lower()
        if not media_url:
            raise CourseDownloadCoordinatorError("Hotmart authorized-media resolver returned no media URL")
        token = register_hotmart_download_authorization(browser=resolved_browser, referer=referer)
        payload = dict(engine_payload)
        payload.pop("_hotmartResolveAuthorizedMedia", None)
        payload["sourceUrl"] = media_url
        payload["browser"] = resolved_browser
        payload["collectionMode"] = "single"
        payload["includeSubtitle"] = False
        payload["includeCourseAttachments"] = False
        payload["_hotmartAuthorizationToken"] = token
        return payload, token

    def submit(self, plan: dict[str, Any], course_id: object) -> tuple[object, dict[str, Any]]:
        if not isinstance(plan, dict):
            raise CourseDownloadCoordinatorError("course provider plan is invalid")
        engine_payload = plan.get("enginePayload")
        if not isinstance(engine_payload, dict):
            raise CourseDownloadCoordinatorError("course provider engine payload is invalid")
        provider = str(plan.get("provider") or "").strip().lower()
        source_url = str(plan.get("sourceUrl") or engine_payload.get("sourceUrl") or "").strip()
        if not provider or not source_url:
            raise CourseDownloadCoordinatorError("course provider plan is incomplete")

        hotmart_token = ""
        if provider == "hotmart":
            submitted_payload, hotmart_token = self._prepare_hotmart_payload(source_url, engine_payload)
        else:
            submitted_payload = dict(engine_payload)

        tracking_id = new_output_tracking_id()
        submitted_payload["_outputTrackingId"] = tracking_id
        try:
            job = self.runtime.submit(submitted_payload)
        except Exception:
            with suppress(Exception):
                clear_output_tracking(tracking_id)
            if hotmart_token:
                with suppress(Exception):
                    revoke_hotmart_download_authorization(hotmart_token)
            raise

        if hotmart_token:
            self._hotmart_tokens[job.job_id] = hotmart_token

        try:
            # Always persist the member-area URL, never the transient signed CDN
            # URL that was resolved for this particular authorized session.
            session = register_course_download_session(
                job_id=job.job_id,
                tracking_id=tracking_id,
                course_id=course_id,
                provider=provider,
                source_url=source_url,
            )
        except CourseDownloadSessionError as exc:
            with suppress(Exception):
                self.runtime.cancel(job.job_id)
            with suppress(Exception):
                clear_output_tracking(tracking_id)
            token = self._hotmart_tokens.pop(job.job_id, "")
            if token:
                with suppress(Exception):
                    revoke_hotmart_download_authorization(token)
            raise CourseDownloadCoordinatorError(str(exc)) from exc
        except Exception:
            with suppress(Exception):
                self.runtime.cancel(job.job_id)
            with suppress(Exception):
                clear_output_tracking(tracking_id)
            token = self._hotmart_tokens.pop(job.job_id, "")
            if token:
                with suppress(Exception):
                    revoke_hotmart_download_authorization(token)
            raise

        self._handle_job(job.public_payload())
        refreshed = self._session(job.job_id)
        return job, refreshed or session

    def status(self, job_id: object) -> dict[str, Any]:
        session = self._session(job_id)
        job = self.runtime.get(job_id)
        if session is None and job is None:
            raise CourseDownloadCoordinatorError("course download session not found")
        return {"session": session, "job": None if job is None else job.public_payload()}

    def sync_now(self, job_id: object) -> dict[str, Any]:
        job = self.runtime.get(job_id)
        if job is None:
            raise CourseDownloadCoordinatorError("course download job not found")
        snapshot = job.public_payload()
        state = str(snapshot.get("state") or "").strip().lower()
        if state != "completed":
            raise CourseDownloadCoordinatorError(f"course download cannot sync from state {state or 'unknown'}")
        try:
            session = sync_course_download_outputs(self.learning_api.context, job.job_id)
        except CourseDownloadSessionError as exc:
            raise CourseDownloadCoordinatorError(str(exc)) from exc
        return {"job": snapshot, "session": session}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._channel.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                if not isinstance(event, dict):
                    continue
                job = event.get("job")
                if isinstance(job, dict):
                    self._handle_job(job)
            finally:
                with suppress(ValueError):
                    self._channel.task_done()

    def _handle_job(self, snapshot: dict[str, Any]) -> None:
        job_id = str(snapshot.get("id") or "").strip().lower()
        state = str(snapshot.get("state") or "").strip().lower()
        if not job_id or state not in _TERMINAL_STATES:
            return
        try:
            session = course_download_session(job_id)
        except CourseDownloadSessionError:
            return
        if session is None:
            return

        if state == "completed":
            try:
                sync_course_download_outputs(self.learning_api.context, job_id)
            except CourseDownloadSessionError as exc:
                with suppress(CourseDownloadSessionError):
                    mark_course_download_sync_failed(job_id, str(exc))
            return

        detail = str(snapshot.get("detail") or state).strip() or state
        with suppress(CourseDownloadSessionError):
            mark_course_download_sync_failed(job_id, detail)
        with suppress(CourseDownloadSessionError):
            discard_course_download_outputs(job_id)
