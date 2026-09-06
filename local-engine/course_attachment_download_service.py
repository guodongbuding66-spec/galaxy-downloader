from __future__ import annotations

import queue
import threading
import uuid
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from course_attachments import CourseAttachmentError, attachment_download_context
from headless_browser_cookies import browser_cookie_source
from headless_service import _safe_detail
from udemy_attachment_downloader import (
    UdemyAttachmentDownloadCancelled,
    UdemyAttachmentDownloadError,
    download_udemy_attachment,
)

MAX_ATTACHMENT_DOWNLOAD_JOBS = 300
MAX_ATTACHMENT_DOWNLOAD_QUEUE = 25
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})


class CourseAttachmentDownloadServiceError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class _AttachmentJob:
    id: str
    attachment_id: str
    browser: str
    state: str = "queued"
    progress: float = 0.0
    downloaded_bytes: int = 0
    size_bytes: int = 0
    file_name: str = ""
    error: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "attachmentId": self.attachment_id,
            "state": self.state,
            "progress": round(max(0.0, min(float(self.progress), 100.0)), 1),
            "downloadedBytes": max(0, int(self.downloaded_bytes)),
            "sizeBytes": max(0, int(self.size_bytes)),
            "fileName": self.file_name[:240],
            "error": self.error[:360],
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class CourseAttachmentDownloadService:
    def __init__(self, learning_context) -> None:
        if learning_context is None:
            raise CourseAttachmentDownloadServiceError("learning context is required")
        self.context = learning_context
        self._jobs: OrderedDict[str, _AttachmentJob] = OrderedDict()
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=MAX_ATTACHMENT_DOWNLOAD_QUEUE)
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._worker = threading.Thread(
            target=self._run,
            name="GalaxyCourseAttachmentDownloads",
            daemon=True,
        )
        self._worker.start()

    def _prune_locked(self) -> None:
        while len(self._jobs) >= MAX_ATTACHMENT_DOWNLOAD_JOBS:
            removed = False
            for job_id, job in list(self._jobs.items()):
                if job.state in _TERMINAL_STATES:
                    self._jobs.pop(job_id, None)
                    removed = True
                    break
            if not removed:
                raise CourseAttachmentDownloadServiceError("attachment download job limit reached")

    def submit(self, attachment_id: object, *, browser: object = "none") -> dict[str, Any]:
        if self._closed.is_set():
            raise CourseAttachmentDownloadServiceError("attachment download service is closed")
        browser_id = browser_cookie_source(browser)
        try:
            context = attachment_download_context(self.context, attachment_id)
        except CourseAttachmentError as exc:
            raise CourseAttachmentDownloadServiceError(str(exc)) from exc
        attachment = str(context.get("id") or "").strip().lower()
        if not attachment:
            raise CourseAttachmentDownloadServiceError("course attachment not found")
        with self._lock:
            # Reuse an in-flight job before applying queue/job capacity. A repeated
            # click must not turn into a spurious 429 just because unrelated jobs
            # filled the queue after this attachment was already accepted.
            for existing in self._jobs.values():
                if existing.attachment_id == attachment and existing.state not in _TERMINAL_STATES:
                    return existing.public_payload()
            self._prune_locked()
            if self._queue.full():
                raise CourseAttachmentDownloadServiceError("attachment download queue is full")
            job = _AttachmentJob(uuid.uuid4().hex, attachment, browser_id)
            self._jobs[job.id] = job
            self._queue.put_nowait(job.id)
            return job.public_payload()

    def status(self, job_id: object) -> dict[str, Any]:
        clean = str(job_id or "").strip().lower()
        if len(clean) != 32 or any(ch not in "0123456789abcdef" for ch in clean):
            raise CourseAttachmentDownloadServiceError("attachment download job not found")
        with self._lock:
            job = self._jobs.get(clean)
            if job is None:
                raise CourseAttachmentDownloadServiceError("attachment download job not found")
            self._jobs.move_to_end(clean)
            return job.public_payload()

    def cancel(self, job_id: object) -> dict[str, Any]:
        clean = str(job_id or "").strip().lower()
        with self._lock:
            job = self._jobs.get(clean)
            if job is None:
                raise CourseAttachmentDownloadServiceError("attachment download job not found")
            if job.state in _TERMINAL_STATES:
                return job.public_payload()
            job.cancel_event.set()
            job.state = "cancelled" if job.state == "queued" else "cancelling"
            job.updated_at = _now()
            return job.public_payload()

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        with self._lock:
            for job in self._jobs.values():
                if job.state in _TERMINAL_STATES:
                    continue
                job.cancel_event.set()
                if job.state == "queued":
                    job.state = "cancelled"
                else:
                    job.state = "cancelling"
                job.updated_at = _now()
        with suppress(queue.Full):
            self._queue.put_nowait(None)
        if self._worker.is_alive():
            self._worker.join(timeout=3.0)

    def _progress(self, job_id: str, downloaded: int, total: int, file_name: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.downloaded_bytes = max(0, int(downloaded))
            job.size_bytes = max(0, int(total))
            job.file_name = str(file_name or "")[:240]
            if total > 0:
                job.progress = min(99.9, (job.downloaded_bytes / total) * 100.0)
            job.updated_at = _now()

    def _run(self) -> None:
        while not self._closed.is_set():
            try:
                job_id = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                if job_id is None:
                    return
                with self._lock:
                    job = self._jobs.get(job_id)
                    if job is None or job.state == "cancelled":
                        continue
                    job.state = "running"
                    job.error = ""
                    job.updated_at = _now()
                try:
                    result = download_udemy_attachment(
                        self.context,
                        job.attachment_id,
                        browser=job.browser,
                        cancel_event=job.cancel_event,
                        progress_hook=lambda downloaded, total, name: self._progress(
                            job_id, downloaded, total, name
                        ),
                    )
                    with self._lock:
                        current = self._jobs.get(job_id)
                        if current is None:
                            continue
                        current.state = "completed"
                        current.progress = 100.0
                        current.downloaded_bytes = int(result.get("sizeBytes") or current.downloaded_bytes)
                        current.size_bytes = current.downloaded_bytes
                        current.file_name = str(result.get("fileName") or current.file_name)[:240]
                        current.error = ""
                        current.updated_at = _now()
                except UdemyAttachmentDownloadCancelled:
                    with self._lock:
                        current = self._jobs.get(job_id)
                        if current is not None:
                            current.state = "cancelled"
                            current.error = ""
                            current.updated_at = _now()
                except UdemyAttachmentDownloadError as exc:
                    with self._lock:
                        current = self._jobs.get(job_id)
                        if current is not None:
                            current.state = "failed"
                            current.error = _safe_detail(exc, 360)
                            current.updated_at = _now()
                except Exception:
                    with self._lock:
                        current = self._jobs.get(job_id)
                        if current is not None:
                            current.state = "failed"
                            current.error = "attachment download failed"
                            current.updated_at = _now()
            finally:
                self._queue.task_done()
