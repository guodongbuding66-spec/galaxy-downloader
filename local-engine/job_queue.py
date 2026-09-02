from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from batch_identity import batch_identity_from_job
from batch_input import BatchInputResult
from batch_submission import BatchSubmissionResult, submit_batch_input_result
from bridge_submission_policy import (
    JobSubmissionResult,
    QueueCancellationResult,
    StructuredLocalBridge,
)
from job_scheduler import JobScheduler

MAX_QUEUED_MEDIA_JOBS = 25
MAX_QUEUE_LABEL_CHARS = 120


@dataclass(frozen=True)
class QueuedMediaJob:
    job_id: str
    job: Any
    label: str
    source_host: str


def _safe_queue_text(value: object, limit: int = MAX_QUEUE_LABEL_CHARS) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


def _job_source_url(job: Any) -> str:
    source = getattr(job, "source_url", None)
    if source is None and isinstance(job, dict):
        source = job.get("sourceUrl") or job.get("source_url")
    return str(source or "").strip()


def _batch_queue_status_fields(job: Any) -> dict[str, Any]:
    batch_id, batch_index, batch_size = batch_identity_from_job(job)
    if batch_id is None:
        return {}
    return {
        "batchId": batch_id,
        "batchIndex": batch_index,
        "batchSize": batch_size,
    }


def _queued_media_job(payload: dict[str, Any], job: Any) -> QueuedMediaJob:
    source_url = _job_source_url(job)
    try:
        source_host = _safe_queue_text(urlparse(source_url).hostname or "")
    except ValueError:
        source_host = ""
    label = _safe_queue_text(payload.get("displayTitle")) or source_host or "Queued download"
    return QueuedMediaJob(
        job_id=uuid.uuid4().hex,
        job=job,
        label=label,
        source_host=source_host,
    )


def install_job_queue_policy(engine_module):
    """Install a bounded FIFO queue around EngineWindow media jobs.

    The original window deliberately accepts only one active job. Website and
    protocol requests can arrive while that job is running, though. Rejecting
    them made galaxy-downloader:// launch a second process, which then failed to
    bind the already-used loopback port. A queue keeps one resident engine and
    hands the next job to it after the current worker exits.

    Queue status deliberately exposes only a generated job id, a user-facing
    label and the source hostname. The full source URL may contain private query
    tokens and is never copied into the status endpoint.
    """
    base_window = engine_module.EngineWindow
    if getattr(base_window, "_galaxy_queue_enabled", False):
        return base_window

    # EngineWindow resolves this module global when an instance is created.
    # Replace it before any window exists so /download can expose precise
    # 400/409/503/504 semantics while keeping the stable parse bridge intact.
    engine_module.LocalBridge = StructuredLocalBridge

    class QueuedEngineWindow(base_window):
        _galaxy_queue_enabled = True
        _galaxy_batch_submission_enabled = True

        def __init__(self, job):
            self.scheduler = JobScheduler[QueuedMediaJob](
                max_waiting=MAX_QUEUED_MEDIA_JOBS,
                concurrency_limit=1,
            )
            # Compatibility alias: queue controls and desktop presenters still
            # operate on this exact list while lifecycle operations migrate to
            # JobScheduler. Keep the list identity stable.
            self.pending_jobs = self.scheduler.waiting
            self._queue_lock = threading.Lock()
            super().__init__(job)

        def bridge_status(self) -> dict[str, Any]:
            payload = super().bridge_status()
            with self._queue_lock:
                queued_jobs = [
                    {
                        "id": queued.job_id,
                        "position": position,
                        "label": queued.label,
                        "sourceHost": queued.source_host,
                        **_batch_queue_status_fields(queued.job),
                    }
                    for position, queued in enumerate(self.pending_jobs, start=1)
                ]
            payload["queueLength"] = len(queued_jobs)
            payload["queueCapacity"] = MAX_QUEUED_MEDIA_JOBS
            payload["queuedJobs"] = queued_jobs
            return payload

        def submit_bridge_job(self, payload: dict[str, Any]) -> JobSubmissionResult:
            try:
                job = engine_module.job_from_payload(payload)
            except ValueError as exc:
                return JobSubmissionResult(False, str(exc), 400, "BAD_REQUEST")

            completed = threading.Event()
            result: dict[str, Any] = {
                "accepted": False,
                "message": "Local engine did not accept the job",
                "status": 409,
                "code": "ENGINE_BUSY",
            }

            def accept() -> None:
                if getattr(self, "_galaxy_close_pending", False):
                    result.update(
                        accepted=False,
                        message="Galaxy Local Engine is shutting down",
                        status=503,
                        code="ENGINE_SHUTTING_DOWN",
                    )
                elif self.running:
                    queued = _queued_media_job(payload, job)
                    with self._queue_lock:
                        queue_position = self.scheduler.enqueue(queued)
                    if queue_position is None:
                        result.update(
                            accepted=False,
                            message=f"Download queue is full ({MAX_QUEUED_MEDIA_JOBS} waiting jobs)",
                            status=409,
                            code="QUEUE_FULL",
                        )
                    else:
                        result.update(
                            accepted=True,
                            message=f"Download queued at position {queue_position}",
                            status=202,
                            code="QUEUED",
                        )
                else:
                    self.job = job
                    self.deiconify()
                    self.lift()
                    try:
                        self.focus_force()
                    except Exception:
                        pass
                    self.start_job()
                    result.update(
                        accepted=True,
                        message="Download job accepted",
                        status=202,
                        code="ACCEPTED",
                    )
                completed.set()

            self.after(0, accept)
            if not completed.wait(timeout=2.0):
                return JobSubmissionResult(
                    False,
                    "Timed out while handing the job to the desktop window",
                    504,
                    "ENGINE_HANDOFF_TIMEOUT",
                )
            return JobSubmissionResult(
                bool(result["accepted"]),
                str(result["message"]),
                int(result["status"]),
                str(result["code"]),
            )

        def submit_batch_jobs_from_bridge(
            self,
            batch: BatchInputResult,
            base_payload: dict[str, Any],
        ) -> BatchSubmissionResult:
            """Submit a reviewed batch from a bridge/background thread.

            The controller intentionally reuses ``submit_bridge_job`` for every
            row. That keeps final Job normalization, DNS-aware public URL checks,
            single-active execution and bounded scheduler FIFO semantics in one
            place. A future desktop workbench must call this from a worker thread,
            not directly inside the Tk event handler.
            """
            return submit_batch_input_result(batch, base_payload, self.submit_bridge_job)

        def _start_next_queued_job(self) -> None:
            if getattr(self, "_galaxy_close_pending", False):
                self.clear_queued_jobs()
                return
            if self.running:
                return
            with self._queue_lock:
                queued = self.scheduler.pop_next()
            if queued is None:
                return
            self.job = queued.job
            self.start_job()

        def _run_job(self) -> None:
            super()._run_job()
            try:
                self.ui(self._start_next_queued_job)
            except Exception:
                # Tk may already be tearing down after a system-level shutdown.
                self.clear_queued_jobs()

        def cancel_queued_job_from_bridge(self, job_id: str) -> QueueCancellationResult:
            completed = threading.Event()
            result: dict[str, Any] = {
                "cancelled": False,
                "message": "Queued download not found",
                "status": 404,
                "code": "QUEUE_ITEM_NOT_FOUND",
            }

            def cancel_waiting_job() -> None:
                if getattr(self, "_galaxy_close_pending", False):
                    result.update(
                        cancelled=False,
                        message="Galaxy Local Engine is shutting down",
                        status=503,
                        code="ENGINE_SHUTTING_DOWN",
                    )
                    completed.set()
                    return

                with self._queue_lock:
                    removed = self.scheduler.remove_first(lambda queued: queued.job_id == job_id)
                if removed is not None:
                    result.update(
                        cancelled=True,
                        message="Queued download cancelled",
                        status=200,
                        code="QUEUE_ITEM_CANCELLED",
                    )
                completed.set()

            self.after(0, cancel_waiting_job)
            if not completed.wait(timeout=2.0):
                return QueueCancellationResult(
                    False,
                    "Timed out while handing queue cancellation to the desktop window",
                    504,
                    "ENGINE_HANDOFF_TIMEOUT",
                )
            return QueueCancellationResult(
                bool(result["cancelled"]),
                str(result["message"]),
                int(result["status"]),
                str(result["code"]),
            )

        def clear_queued_jobs(self) -> int:
            with self._queue_lock:
                return self.scheduler.clear()

    QueuedEngineWindow.__name__ = "QueuedEngineWindow"
    QueuedEngineWindow.__qualname__ = "QueuedEngineWindow"
    engine_module.EngineWindow = QueuedEngineWindow
    return QueuedEngineWindow
