from __future__ import annotations

import threading
from typing import Any

from bridge_submission_policy import JobSubmissionResult, StructuredLocalBridge

MAX_QUEUED_MEDIA_JOBS = 25


def install_job_queue_policy(engine_module):
    """Install a bounded FIFO queue around EngineWindow media jobs.

    The original window deliberately accepts only one active job. Website and
    protocol requests can arrive while that job is running, though. Rejecting
    them made galaxy-downloader:// launch a second process, which then failed to
    bind the already-used loopback port. A queue keeps one resident engine and
    hands the next job to it after the current worker exits.
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

        def __init__(self, job):
            self.pending_jobs: list[Any] = []
            super().__init__(job)

        def bridge_status(self) -> dict[str, Any]:
            payload = super().bridge_status()
            payload["queueLength"] = len(self.pending_jobs)
            payload["queueCapacity"] = MAX_QUEUED_MEDIA_JOBS
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
                    if len(self.pending_jobs) >= MAX_QUEUED_MEDIA_JOBS:
                        result.update(
                            accepted=False,
                            message=f"Download queue is full ({MAX_QUEUED_MEDIA_JOBS} waiting jobs)",
                            status=409,
                            code="QUEUE_FULL",
                        )
                    else:
                        self.pending_jobs.append(job)
                        position = len(self.pending_jobs)
                        result.update(
                            accepted=True,
                            message=f"Download queued at position {position}",
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

        def _start_next_queued_job(self) -> None:
            if getattr(self, "_galaxy_close_pending", False):
                self.pending_jobs.clear()
                return
            if self.running or not self.pending_jobs:
                return
            self.job = self.pending_jobs.pop(0)
            self.start_job()

        def _run_job(self) -> None:
            super()._run_job()
            try:
                self.ui(self._start_next_queued_job)
            except Exception:
                # Tk may already be tearing down after a system-level shutdown.
                self.pending_jobs.clear()

        def clear_queued_jobs(self) -> int:
            count = len(self.pending_jobs)
            self.pending_jobs.clear()
            return count

    QueuedEngineWindow.__name__ = "QueuedEngineWindow"
    QueuedEngineWindow.__qualname__ = "QueuedEngineWindow"
    engine_module.EngineWindow = QueuedEngineWindow
    return QueuedEngineWindow
