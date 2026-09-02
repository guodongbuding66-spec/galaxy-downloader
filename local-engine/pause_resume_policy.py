from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from batch_identity import batch_identity_from_payload

RESUME_STATE_FILENAME = "resume-jobs.json"
RESUME_SCHEMA_VERSION = 1
MAX_RESUME_JOBS = 25
PERSIST_PROGRESS_INTERVAL_SECONDS = 2.0
_RESUME_LOCK = threading.RLock()
_RECOVERABLE_STATES = {"running", "pausing", "paused", "interrupted"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_host(source_url: object) -> str:
    try:
        return (urlparse(str(source_url or "")).hostname or "").lower()[:160]
    except ValueError:
        return ""


def _bounded_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _bounded_progress(value: object) -> float:
    try:
        return max(0.0, min(100.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


class ResumeStateStore:
    """Atomic local persistence for resumable media jobs.

    The full source URL is intentionally kept only inside this local state file:
    signed URLs and stable identity query parameters may be required to resume a
    job after restart. `public_records()` never returns the payload or source URL,
    so Bridge status and diagnostics do not accidentally expose those values.
    """

    def __init__(self, engine_module) -> None:
        self.engine_module = engine_module
        state_dir = engine_module.app_dir() / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.path = state_dir / RESUME_STATE_FILENAME

    def _clean_record(self, value: object) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        job_id = _bounded_text(value.get("id"), 64)
        state = str(value.get("state") or "").strip().lower()
        payload = value.get("payload")
        if not job_id or state not in _RECOVERABLE_STATES or not isinstance(payload, dict):
            return None
        try:
            # Validate with the fully installed Job schema. Do not persist stale
            # or malformed payloads that the current engine can no longer run.
            self.engine_module.job_from_payload(dict(payload))
        except Exception:
            return None

        source_url = str(payload.get("sourceUrl") or "")
        batch_id, batch_index, batch_size = batch_identity_from_payload(payload)
        created_at = _bounded_text(value.get("createdAt"), 40) or _utc_now()
        updated_at = _bounded_text(value.get("updatedAt"), 40) or created_at
        resume_mode = str(value.get("resumeMode") or "continue").strip().lower()
        if resume_mode not in {"continue", "restart"}:
            resume_mode = "continue"
        return {
            "id": job_id,
            "state": state,
            "createdAt": created_at,
            "updatedAt": updated_at,
            "payload": dict(payload),
            "sourceHost": _safe_host(source_url),
            "label": _bounded_text(value.get("label"), 180) or _safe_host(source_url) or "Download",
            "videoQuality": _bounded_text(value.get("videoQuality"), 40),
            "batchId": batch_id,
            "batchIndex": batch_index,
            "batchSize": batch_size,
            "progress": _bounded_progress(value.get("progress")),
            "downloaded": _bounded_text(value.get("downloaded"), 80),
            "resumeMode": resume_mode,
            "queueWasPaused": bool(value.get("queueWasPaused", False)),
        }

    def _read_unlocked(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return []
        if isinstance(raw, dict):
            values = raw.get("jobs")
        else:
            values = raw
        if not isinstance(values, list):
            return []
        records: list[dict[str, Any]] = []
        for value in values[:MAX_RESUME_JOBS]:
            cleaned = self._clean_record(value)
            if cleaned is not None:
                records.append(cleaned)
        return records

    def _write_unlocked(self, records: list[dict[str, Any]]) -> None:
        payload = {
            "schemaVersion": RESUME_SCHEMA_VERSION,
            "updatedAt": _utc_now(),
            "jobs": records[:MAX_RESUME_JOBS],
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def recover_after_restart(self) -> list[dict[str, Any]]:
        """Turn stale active records into user-resumable interrupted records."""
        with _RESUME_LOCK:
            records = self._read_unlocked()
            changed = False
            now = _utc_now()
            for record in records:
                if record["state"] in {"running", "pausing"}:
                    record["state"] = "interrupted"
                    record["updatedAt"] = now
                    changed = True
            if changed:
                self._write_unlocked(records)
            return [dict(record) for record in records]

    def records(self) -> list[dict[str, Any]]:
        with _RESUME_LOCK:
            return [dict(record) for record in self._read_unlocked()]

    def get(self, job_id: str) -> dict[str, Any] | None:
        wanted = str(job_id or "")
        with _RESUME_LOCK:
            return next((dict(record) for record in self._read_unlocked() if record["id"] == wanted), None)

    def upsert(self, record: dict[str, Any]) -> dict[str, Any] | None:
        cleaned = self._clean_record(record)
        if cleaned is None:
            return None
        cleaned["updatedAt"] = _utc_now()
        with _RESUME_LOCK:
            records = self._read_unlocked()
            previous = next((item for item in records if item["id"] == cleaned["id"]), None)
            if previous and not cleaned.get("createdAt"):
                cleaned["createdAt"] = previous.get("createdAt") or _utc_now()
            records = [item for item in records if item["id"] != cleaned["id"]]
            records.insert(0, cleaned)
            self._write_unlocked(records)
        return dict(cleaned)

    def remove(self, job_id: str) -> bool:
        wanted = str(job_id or "")
        if not wanted:
            return False
        with _RESUME_LOCK:
            records = self._read_unlocked()
            remaining = [record for record in records if record["id"] != wanted]
            if len(remaining) == len(records):
                return False
            self._write_unlocked(remaining)
            return True

    def public_records(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for record in self.records():
            result.append(
                {
                    "id": record["id"],
                    "state": record["state"],
                    "createdAt": record["createdAt"],
                    "updatedAt": record["updatedAt"],
                    "sourceHost": record["sourceHost"],
                    "label": record["label"],
                    "videoQuality": record["videoQuality"],
                    "batchId": record.get("batchId"),
                    "batchIndex": int(record.get("batchIndex") or 0),
                    "batchSize": int(record.get("batchSize") or 0),
                    "progress": record["progress"],
                    "downloaded": record["downloaded"],
                    "resumeMode": record["resumeMode"],
                }
            )
        return result


def _resume_mode(engine_module, job: Any) -> str:
    try:
        if engine_module.is_wechat_channels_url(str(getattr(job, "source_url", "") or "")):
            # The custom WeChat downloader does not yet expose byte-range resume.
            return "restart"
    except Exception:
        pass
    return "continue"


def _record_for_window(window, engine_module, state: str) -> dict[str, Any] | None:
    job = getattr(window, "job", None)
    job_id = str(getattr(window, "_active_resume_job_id", "") or "")
    if job is None or not job_id:
        return None
    try:
        payload = dict(engine_module.job_to_payload(job))
    except Exception:
        return None
    progress = 0.0
    downloaded = ""
    try:
        progress = float(window.percent_var.get() or 0.0)
    except Exception:
        pass
    try:
        downloaded = str(window.size_var.get() or "")
    except Exception:
        pass
    source_host = _safe_host(payload.get("sourceUrl"))
    return {
        "id": job_id,
        "state": state,
        "createdAt": str(getattr(window, "_active_resume_created_at", "") or _utc_now()),
        "updatedAt": _utc_now(),
        "payload": payload,
        "sourceHost": source_host,
        "label": source_host or "Download",
        "videoQuality": str(getattr(job, "video_quality", "") or ""),
        "progress": progress,
        "downloaded": downloaded,
        "resumeMode": _resume_mode(engine_module, job),
        "queueWasPaused": bool(getattr(window, "_resume_queue_was_paused", False)),
    }


def install_pause_resume_policy(engine_module):
    """Add persistent active-job pause/restart recovery without changing yt-dlp semantics.

    Pause is implemented as a resumable stop, not an OS process suspension. The
    downloader is asked to stop at its normal cancellation boundary, `.part` and
    fragment files are preserved, and the same Job is later rerun. yt-dlp already
    uses `--continue` / `continuedl=True`, so supported HTTP/HLS sources resume at
    their nearest available checkpoint instead of pretending a sleeping process
    can survive reboot.
    """
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_pause_resume_installed", False):
        return window_cls

    original_init = window_cls.__init__
    original_bridge_status = window_cls.bridge_status
    original_start_job = window_cls.start_job
    original_run_job = window_cls._run_job
    original_set_status = window_cls.set_status
    original_update_bridge = window_cls._update_bridge
    original_cancel = window_cls.cancel

    def init(window, job) -> None:
        window.pause_event = threading.Event()
        window._resume_store = ResumeStateStore(engine_module)
        window._resume_store.recover_after_restart()
        window._active_resume_job_id = ""
        window._active_resume_created_at = ""
        window._resume_queue_was_paused = False
        window._pause_queue_holder_id = ""
        window._resume_last_persist_at = 0.0
        original_init(window, job)

        if job is None:
            recoverable = window._resume_store.public_records()
            if recoverable:
                count = len(recoverable)
                window.set_status("Paused", f"{count} 个未完成任务可以从任务中心继续。")

    def public_resume_jobs(window) -> list[dict[str, Any]]:
        return window._resume_store.public_records()

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        records = public_resume_jobs(window)
        payload["activeJobId"] = str(getattr(window, "_active_resume_job_id", "") or "") or None
        payload["resumeJobCount"] = len(records)
        payload["resumeJobs"] = records
        payload["canPause"] = bool(getattr(window, "running", False)) and not window.pause_event.is_set()
        payload["canResume"] = (not bool(getattr(window, "running", False))) and bool(records)
        return payload

    def persist(window, state: str, *, force: bool = False) -> None:
        if not getattr(window, "_active_resume_job_id", ""):
            return
        now = time.monotonic()
        if not force and state == "running" and now - float(getattr(window, "_resume_last_persist_at", 0.0)) < PERSIST_PROGRESS_INTERVAL_SECONDS:
            return
        record = _record_for_window(window, engine_module, state)
        if record is None:
            return
        window._resume_store.upsert(record)
        window._resume_last_persist_at = now

    def update_bridge(window, **changes: Any) -> None:
        original_update_bridge(window, **changes)
        if "progress" in changes and bool(getattr(window, "running", False)) and not window.pause_event.is_set():
            try:
                persist(window, "running")
            except Exception:
                # Resume state must never change download success/failure semantics.
                pass

    def set_status(window, title: str, detail: str | None = None) -> None:
        mapped_title = title
        mapped_detail = detail
        if window.pause_event.is_set():
            if title == "Cancelling":
                mapped_title = "Pausing"
                mapped_detail = detail or "Stopping at a resumable download checkpoint"
            elif title == "Cancelled":
                mapped_title = "Paused"
                mapped_detail = "下载已暂停；临时分片保留在本机，可稍后继续。"
        original_set_status(window, mapped_title, mapped_detail)
        if mapped_title == "Pausing":
            original_update_bridge(window, state="pausing", busy=True)
        elif mapped_title == "Paused":
            original_update_bridge(window, state="paused", busy=False)

    def start_job(window) -> None:
        if not getattr(window, "job", None) or bool(getattr(window, "running", False)):
            return
        if not getattr(window, "_active_resume_job_id", ""):
            window._active_resume_job_id = uuid.uuid4().hex
            window._active_resume_created_at = _utc_now()
            window._resume_queue_was_paused = bool(getattr(window, "queue_paused", False))
        window.pause_event.clear()
        try:
            persist(window, "running", force=True)
        except Exception:
            pass
        original_start_job(window)

    def run_job(window) -> None:
        job_id = str(getattr(window, "_active_resume_job_id", "") or "")
        try:
            original_run_job(window)
        finally:
            try:
                if window.pause_event.is_set():
                    persist(window, "paused", force=True)
                    original_update_bridge(window, state="paused", status="Paused", busy=False)
                elif job_id:
                    # Completed, explicitly cancelled and normally failed jobs use
                    # history/retry. Only paused or unexpectedly interrupted jobs
                    # stay in the resume state store.
                    window._resume_store.remove(job_id)
            except Exception:
                pass
            window._active_resume_job_id = ""
            window._active_resume_created_at = ""
            window._resume_last_persist_at = 0.0
            if window.pause_event.is_set():
                window.pause_event.clear()

    def restore_queue_after_pause(window, job_id: str, *, start_if_idle: bool) -> bool:
        """Release only the temporary queue hold created by this paused job."""
        holder = str(getattr(window, "_pause_queue_holder_id", "") or "")
        if not holder or holder != str(job_id or ""):
            return False
        window.queue_paused = bool(getattr(window, "_resume_queue_was_paused", False))
        window._pause_queue_holder_id = ""
        if start_if_idle and not window.queue_paused and not bool(getattr(window, "running", False)):
            starter = getattr(window, "_start_next_queued_job", None)
            if callable(starter):
                starter()
        return True


    def pause_active_job(window) -> bool:
        if not bool(getattr(window, "running", False)) or window.pause_event.is_set():
            return False
        window._resume_queue_was_paused = bool(getattr(window, "queue_paused", False))
        window._pause_queue_holder_id = str(getattr(window, "_active_resume_job_id", "") or "")
        # Prevent the single-active-job scheduler from immediately starting the
        # next queued item after the paused worker exits.
        window.queue_paused = True
        window.pause_event.set()
        try:
            persist(window, "pausing", force=True)
        except Exception:
            pass
        original_set_status(window, "Pausing", "正在保留临时文件并停止到可恢复检查点…")
        original_update_bridge(window, state="pausing", busy=True)
        window.cancel_event.set()
        return True

    def pause_for_exit(window) -> bool:
        return pause_active_job(window)

    def resume_job(window, job_id: str | None = None) -> bool:
        if bool(getattr(window, "running", False)):
            return False
        records = window._resume_store.records()
        if not records:
            return False
        selected = None
        if job_id:
            selected = next((record for record in records if record["id"] == str(job_id)), None)
        else:
            selected = records[0]
        if selected is None:
            return False
        try:
            job = engine_module.job_from_payload(dict(selected["payload"]))
        except Exception:
            return False

        window.job = job
        window._active_resume_job_id = str(selected["id"])
        window._active_resume_created_at = str(selected.get("createdAt") or _utc_now())
        window._resume_queue_was_paused = bool(selected.get("queueWasPaused", False))
        if not restore_queue_after_pause(window, str(selected["id"]), start_if_idle=False):
            # After an application restart there is no in-memory queue hold to
            # release, but preserve the recorded queue preference for the new run.
            window.queue_paused = window._resume_queue_was_paused
        window.cancel_event.clear()
        window.pause_event.clear()
        selected["state"] = "running"
        window._resume_store.upsert(selected)
        window.deiconify()
        window.lift()
        try:
            window.focus_force()
        except Exception:
            pass
        original_set_status(window, "Resuming", "正在从本机保留的下载检查点继续…")
        original_update_bridge(window, state="resuming", busy=True)
        start_job(window)
        return True

    def discard_resume_job(window, job_id: str) -> bool:
        wanted = str(job_id or "")
        if wanted == str(getattr(window, "_active_resume_job_id", "") or "") and bool(getattr(window, "running", False)):
            return False
        removed = window._resume_store.remove(wanted)
        if removed:
            restore_queue_after_pause(window, wanted, start_if_idle=True)
        return removed

    def cancel(window) -> None:
        # Explicit Cancel means "do not offer this job for restart recovery".
        if window.pause_event.is_set():
            restore_queue_after_pause(
                window,
                str(getattr(window, "_active_resume_job_id", "") or ""),
                start_if_idle=False,
            )
        window.pause_event.clear()
        original_cancel(window)

    window_cls.__init__ = init
    window_cls.bridge_status = bridge_status
    window_cls._update_bridge = update_bridge
    window_cls.set_status = set_status
    window_cls.start_job = start_job
    window_cls._run_job = run_job
    window_cls.pause_active_job = pause_active_job
    window_cls.pause_for_exit = pause_for_exit
    window_cls.resume_job = resume_job
    window_cls.discard_resume_job = discard_resume_job
    window_cls.get_resume_jobs = public_resume_jobs
    window_cls.cancel = cancel
    window_cls._galaxy_pause_resume_installed = True
    engine_module._galaxy_pause_resume_installed = True
    return window_cls


def run_pause_resume_self_test() -> None:
    """Exercise persistence plus the full pause -> resume -> cancel lifecycle.

    This intentionally uses a tiny fake EngineWindow so the same assertions run
    inside source and packaged ``--self-test`` without performing network I/O or
    creating a Tk window.
    """
    import tempfile
    from dataclasses import dataclass

    class Value:
        def __init__(self, value: object) -> None:
            self.value = value

        def get(self):
            return self.value

        def set(self, value: object) -> None:
            self.value = value

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        @dataclass(frozen=True)
        class FakeJob:
            source_url: str
            video_quality: str = "best"

        class FakeWindow:
            def __init__(self, job: FakeJob | None) -> None:
                self.job = job
                self.cancel_event = threading.Event()
                self.running = False
                self.queue_paused = False
                self.percent_var = Value(0.0)
                self.size_var = Value("—")
                self.status_var = Value("Ready")
                self.detail_var = Value("Waiting")
                self._snapshot: dict[str, Any] = {
                    "state": "ready",
                    "status": "Ready",
                    "detail": "Waiting",
                    "busy": False,
                    "progress": 0.0,
                }
                self.deiconified = False
                self.started_next = 0

            def bridge_status(self) -> dict[str, Any]:
                return dict(self._snapshot)

            def _update_bridge(self, **changes: Any) -> None:
                self._snapshot.update(changes)

            def set_status(self, title: str, detail: str | None = None) -> None:
                self.status_var.set(title)
                if detail is not None:
                    self.detail_var.set(detail)
                state = {
                    "Ready": "ready",
                    "Starting": "starting",
                    "Completed": "completed",
                    "Cancelling": "cancelling",
                    "Cancelled": "cancelled",
                    "Download failed": "failed",
                }.get(title, "working" if self.running else "ready")
                self._update_bridge(
                    state=state,
                    status=title,
                    detail=self.detail_var.get(),
                    busy=self.running,
                )

            def start_job(self) -> None:
                if self.job is None or self.running:
                    return
                self.running = True
                self.cancel_event.clear()
                self.set_status("Starting", self.job.source_url)
                self._update_bridge(busy=True)

            def _run_job(self) -> None:
                if self.cancel_event.is_set():
                    self.set_status("Cancelled", "The local download was cancelled")
                else:
                    self.percent_var.set(100.0)
                    self._update_bridge(progress=100.0)
                    self.set_status("Completed", "Finished")
                self.running = False
                self._update_bridge(busy=False)

            def cancel(self) -> None:
                if not self.running:
                    return
                self.cancel_event.set()
                self.set_status("Cancelling", "Stopping")

            def deiconify(self) -> None:
                self.deiconified = True

            def lift(self) -> None:
                return

            def focus_force(self) -> None:
                return

            def _start_next_queued_job(self) -> None:
                if not self.running and not self.queue_paused:
                    self.started_next += 1

        class FakeEngine:
            EngineWindow = FakeWindow

            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def job_to_payload(job: FakeJob) -> dict[str, Any]:
                return {
                    "sourceUrl": job.source_url,
                    "videoQuality": job.video_quality,
                }

            @staticmethod
            def job_from_payload(payload: dict[str, Any]) -> FakeJob:
                source = str(payload.get("sourceUrl") or "")
                if not source.startswith(("http://", "https://")):
                    raise ValueError("bad source")
                return FakeJob(source, str(payload.get("videoQuality") or "best"))

            @staticmethod
            def is_wechat_channels_url(source_url: str) -> bool:
                return "channels.weixin.qq.com" in source_url or "weixin.qq.com/sph/" in source_url

        # First validate stale-record recovery and public privacy boundaries.
        store = ResumeStateStore(FakeEngine)
        record = store.upsert(
            {
                "id": "abc123",
                "state": "running",
                "payload": {
                    "sourceUrl": "https://user:secret@example.com/watch/123?token=local-only",
                    "videoQuality": "1080",
                },
                "progress": 43.25,
                "downloaded": "430 MB / 1.0 GB",
                "resumeMode": "continue",
                "queueWasPaused": False,
            }
        )
        assert record is not None
        recovered = store.recover_after_restart()
        assert recovered[0]["state"] == "interrupted"
        assert recovered[0]["progress"] == 43.25
        public = store.public_records()[0]
        rendered_public = json.dumps(public)
        assert "payload" not in public
        assert "token=local-only" not in rendered_public
        assert "user:secret" not in rendered_public
        assert public["sourceHost"] == "example.com"
        assert store.remove("abc123") is True
        assert store.records() == []

        # Install the policy on the fake window and exercise the actual wrappers.
        install_pause_resume_policy(FakeEngine)
        window = FakeEngine.EngineWindow(FakeJob("https://media.example.com/video/123", "1080"))
        window.start_job()
        active_id = window.bridge_status()["activeJobId"]
        assert active_id
        assert window.running is True

        window.percent_var.set(47.25)
        window.size_var.set("472 MB / 1.0 GB")
        window._update_bridge(progress=47.25, downloaded="472 MB / 1.0 GB")
        assert window.pause_active_job() is True
        assert window.queue_paused is True
        assert window.cancel_event.is_set() is True
        assert window.bridge_status()["state"] == "pausing"

        window._run_job()
        assert window.running is False
        paused = window.get_resume_jobs()
        assert len(paused) == 1
        assert paused[0]["id"] == active_id
        assert paused[0]["state"] == "paused"
        assert paused[0]["progress"] == 47.25
        assert paused[0]["downloaded"] == "472 MB / 1.0 GB"
        assert paused[0]["resumeMode"] == "continue"
        assert window.pause_event.is_set() is False

        assert window.resume_job(active_id) is True
        assert window.running is True
        assert window.deiconified is True
        assert window.bridge_status()["activeJobId"] == active_id
        assert window.queue_paused is False
        running = window._resume_store.get(active_id)
        assert running is not None and running["state"] == "running"

        # Explicit Cancel is terminal and must not leave a resume offer behind.
        window.cancel()
        assert window.cancel_event.is_set() is True
        window._run_job()
        assert window.running is False
        assert window.status_var.get() == "Cancelled"
        assert window.get_resume_jobs() == []

        # Queue pause state must round-trip through a paused active task.
        queue_window = FakeEngine.EngineWindow(FakeJob("https://media.example.com/video/queue"))
        queue_window.queue_paused = True
        queue_window.start_job()
        queue_id = queue_window.bridge_status()["activeJobId"]
        assert queue_window.pause_active_job() is True
        queue_window._run_job()
        assert queue_window.resume_job(queue_id) is True
        assert queue_window.queue_paused is True
        queue_window.cancel()
        queue_window._run_job()

        # Custom WeChat downloads must advertise restart, never fake byte resume.
        wechat = FakeEngine.EngineWindow(
            FakeJob("https://channels.weixin.qq.com/finder-preview/pages/sph?id=abc123")
        )
        wechat.start_job()
        wechat.percent_var.set(63.0)
        assert wechat.pause_active_job() is True
        wechat._run_job()
        wechat_records = wechat.get_resume_jobs()
        assert wechat_records[0]["resumeMode"] == "restart"
        assert wechat_records[0]["progress"] == 63.0


        # Discarding a paused task must release only the queue hold that task made.
        discard_window = FakeEngine.EngineWindow(FakeJob("https://media.example.com/video/discard"))
        discard_window.start_job()
        discard_id = discard_window.bridge_status()["activeJobId"]
        assert discard_window.pause_active_job() is True
        discard_window._run_job()
        assert discard_window.queue_paused is True
        assert discard_window.discard_resume_job(discard_id) is True
        assert discard_window.queue_paused is False
        assert discard_window.started_next == 1

        # If Cancel is pressed while Pausing, it becomes a true terminal cancel
        # and the temporary queue hold is released before the worker exits.
        cancel_window = FakeEngine.EngineWindow(FakeJob("https://media.example.com/video/cancel-during-pause"))
        cancel_window.start_job()
        cancel_id = cancel_window.bridge_status()["activeJobId"]
        assert cancel_window.pause_active_job() is True
        assert cancel_window.queue_paused is True
        cancel_window.cancel()
        assert cancel_window.pause_event.is_set() is False
        assert cancel_window.queue_paused is False
        cancel_window._run_job()
        assert cancel_window._resume_store.get(cancel_id) is None

