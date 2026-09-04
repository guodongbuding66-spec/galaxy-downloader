from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from job_scheduler import JobScheduler
from media_cleanup import (
    CleanupRegion,
    MediaCleanupCancelled,
    MediaCleanupError,
    MediaCleanupResult,
    _tool_path,
    _validate_input,
    cleanup_visible_overlay,
    probe_media,
)
from media_cleanup_inpainting import inpaint_visible_overlay_image
from media_cleanup_tracking import (
    cleanup_tracked_visible_overlay,
    track_visible_overlay_for_video,
)

MAX_CLEANUP_BATCH_ITEMS = 32
MAX_CLEANUP_QUEUE_ITEMS = 64
MAX_CLEANUP_COMPLETED_RECORDS = 200
MAX_CLEANUP_ERROR_CHARS = 1200
MAX_CLEANUP_STATUS_CHARS = 240

QUEUED = "queued"
RUNNING = "running"
CANCELLING = "cancelling"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"
TERMINAL_STATES = frozenset({SUCCEEDED, FAILED, CANCELLED})

MODE_AUTO = "auto"
MODE_STATIC = "static"
MODE_IMAGE_INPAINT = "image-inpaint"
MODE_TRACKED_VIDEO = "tracked-video"
CLEANUP_MODES = frozenset({MODE_AUTO, MODE_STATIC, MODE_IMAGE_INPAINT, MODE_TRACKED_VIDEO})

_SECRET_DETAIL_RE = re.compile(
    r"(?i)(authorization|api[-_ ]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"
)


class MediaCleanupBatchError(RuntimeError):
    pass


class MediaCleanupBatchFullError(MediaCleanupBatchError):
    pass


@dataclass(frozen=True)
class CleanupBatchRequest:
    id: str
    input_path: Path
    input_name: str
    media_kind: str
    regions: tuple[CleanupRegion, ...]
    mode: str
    anchor_seconds: float | None
    output_path: Path | None
    created_at: float


@dataclass
class _CleanupRecord:
    request: CleanupBatchRequest | None
    input_name: str
    media_kind: str
    mode: str
    region_count: int
    created_at: float
    state: str = QUEUED
    started_at: float | None = None
    finished_at: float | None = None
    progress: float = 0.0
    status_message: str = "Queued"
    output_name: str = ""
    result_path: Path | None = None
    error_code: str = ""
    error_detail: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)


CleanupBatchExecutor = Callable[
    [CleanupBatchRequest, threading.Event, Callable[[float, str], None]],
    MediaCleanupResult,
]


def _clean_mode(value: object, *, media_kind: str) -> str:
    mode = str(value or MODE_AUTO).strip().lower()
    if mode not in CLEANUP_MODES:
        raise MediaCleanupBatchError("Unsupported media cleanup batch mode")
    if mode == MODE_IMAGE_INPAINT and media_kind != "image":
        raise MediaCleanupBatchError("Image inpainting batch mode requires an image")
    if mode == MODE_TRACKED_VIDEO and media_kind != "video":
        raise MediaCleanupBatchError("Tracked batch mode requires a video")
    if mode == MODE_AUTO:
        return MODE_IMAGE_INPAINT if media_kind == "image" else MODE_STATIC
    return mode


def _clean_regions(values: Iterable[CleanupRegion]) -> tuple[CleanupRegion, ...]:
    regions = tuple(item.validate() for item in values)
    if not regions:
        raise MediaCleanupBatchError("At least one cleanup region is required")
    if len(regions) > 16:
        raise MediaCleanupBatchError("At most 16 cleanup regions are supported per task")
    return regions


def _clean_anchor(value: object, *, mode: str) -> float | None:
    if mode != MODE_TRACKED_VIDEO:
        return None
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise MediaCleanupBatchError("Tracked cleanup anchor time is invalid") from exc
    if parsed < 0 or parsed > 86_400:
        raise MediaCleanupBatchError("Tracked cleanup anchor time is outside the supported range")
    return parsed


def _clean_output(value: object) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    return Path(str(value)).expanduser().resolve()


def _status_message(value: object) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())[:MAX_CLEANUP_STATUS_CHARS]


def _error_payload(exc: Exception) -> tuple[str, str]:
    code = str(getattr(exc, "code", "") or exc.__class__.__name__).strip().upper()
    code = re.sub(r"[^A-Z0-9_-]", "_", code)[:64] or "MEDIA_CLEANUP_FAILED"
    detail = _status_message(exc) or code
    detail = _SECRET_DETAIL_RE.sub(lambda match: match.group(1) + ": [REDACTED]", detail)
    return code, detail[-MAX_CLEANUP_ERROR_CHARS:]


def _build_request(spec: dict[str, Any]) -> CleanupBatchRequest:
    input_value = spec.get("inputPath")
    if not input_value:
        raise MediaCleanupBatchError("Cleanup batch inputPath is required")
    source, media_kind = _validate_input(Path(str(input_value)))
    regions_value = spec.get("regions") or ()
    regions: list[CleanupRegion] = []
    for item in regions_value:
        if isinstance(item, CleanupRegion):
            regions.append(item)
            continue
        if not isinstance(item, dict):
            raise MediaCleanupBatchError("Cleanup batch region must be an object")
        try:
            regions.append(
                CleanupRegion(
                    int(item.get("x")),
                    int(item.get("y")),
                    int(item.get("width")),
                    int(item.get("height")),
                )
            )
        except (TypeError, ValueError) as exc:
            raise MediaCleanupBatchError("Cleanup batch region values must be integers") from exc
    normalized_regions = _clean_regions(regions)
    mode = _clean_mode(spec.get("mode"), media_kind=media_kind)
    if mode == MODE_TRACKED_VIDEO and len(normalized_regions) != 1:
        raise MediaCleanupBatchError("Tracked video cleanup requires exactly one region")
    anchor = _clean_anchor(spec.get("anchorSeconds"), mode=mode)
    output_path = _clean_output(spec.get("outputPath"))
    return CleanupBatchRequest(
        id=uuid.uuid4().hex,
        input_path=source,
        input_name=source.name,
        media_kind=media_kind,
        regions=normalized_regions,
        mode=mode,
        anchor_seconds=anchor,
        output_path=output_path,
        created_at=time.time(),
    )


def execute_cleanup_batch_request(
    ffmpeg_directory: Path,
    request: CleanupBatchRequest,
    cancel_event: threading.Event,
    progress_callback: Callable[[float, str], None],
) -> MediaCleanupResult:
    if request.mode == MODE_IMAGE_INPAINT:
        return inpaint_visible_overlay_image(
            request.input_path,
            request.regions,
            output_path=request.output_path,
            cancel_event=cancel_event,
            progress_callback=progress_callback,
        )
    if request.mode == MODE_TRACKED_VIDEO:
        ffmpeg_path = _tool_path(ffmpeg_directory, "ffmpeg")
        ffprobe_path = _tool_path(ffmpeg_directory, "ffprobe")
        probe = probe_media(ffprobe_path, request.input_path, "video")
        anchor = request.anchor_seconds
        if anchor is None:
            anchor = min(1.0, probe.duration_seconds / 2.0) if probe.duration_seconds > 0 else 0.0
        progress_callback(2.0, "Tracking moving visible overlay")
        track = track_visible_overlay_for_video(
            ffmpeg_path,
            request.input_path,
            probe,
            request.regions[0],
            anchor_seconds=anchor,
        )
        if cancel_event.is_set():
            raise MediaCleanupCancelled("Temporal visible-overlay cleanup was cancelled")
        progress_callback(10.0, "Moving overlay track ready")

        def scaled(percent: float, message: str) -> None:
            progress_callback(10.0 + max(0.0, min(100.0, percent)) * 0.9, message)

        return cleanup_tracked_visible_overlay(
            ffmpeg_directory,
            request.input_path,
            track,
            output_path=request.output_path,
            cancel_event=cancel_event,
            progress_callback=scaled,
        )
    return cleanup_visible_overlay(
        ffmpeg_directory,
        request.input_path,
        request.regions,
        output_path=request.output_path,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
    )


class MediaCleanupBatchCenter:
    """Bounded FIFO lifecycle for visible-overlay cleanup batches.

    The public snapshot intentionally exposes file basenames only. Full local
    paths remain inside active requests/results and are released from the request
    record after completion.
    """

    def __init__(
        self,
        *,
        max_waiting: int = MAX_CLEANUP_QUEUE_ITEMS,
        concurrency_limit: int = 1,
        max_completed_records: int = MAX_CLEANUP_COMPLETED_RECORDS,
    ) -> None:
        completed_limit = int(max_completed_records)
        if completed_limit < 0:
            raise ValueError("max_completed_records must be zero or greater")
        self.scheduler = JobScheduler[str](
            max_waiting=int(max_waiting),
            concurrency_limit=int(concurrency_limit),
        )
        self.max_completed_records = completed_limit
        self._condition = threading.Condition(threading.RLock())
        self._records: dict[str, _CleanupRecord] = {}
        self._active: set[str] = set()
        self._executor: CleanupBatchExecutor | None = None
        self._workers: list[threading.Thread] = []
        self._stopping = False

    @property
    def waiting_count(self) -> int:
        with self._condition:
            return self.scheduler.waiting_count

    @property
    def active_count(self) -> int:
        with self._condition:
            return len(self._active)

    def submit(self, spec: dict[str, Any]) -> dict[str, Any]:
        return self.submit_many((spec,))[0]

    def submit_many(self, specs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        items = list(specs)
        if not items:
            raise MediaCleanupBatchError("Cleanup batch must contain at least one task")
        if len(items) > MAX_CLEANUP_BATCH_ITEMS:
            raise MediaCleanupBatchError(
                f"Cleanup batch supports at most {MAX_CLEANUP_BATCH_ITEMS} tasks at once"
            )
        requests = tuple(_build_request(dict(item)) for item in items)
        with self._condition:
            if self._stopping:
                raise MediaCleanupBatchError("Cleanup Batch Center is shutting down")
            available = self.scheduler.max_waiting - self.scheduler.waiting_count
            if len(requests) > available:
                raise MediaCleanupBatchFullError(
                    f"Cleanup Batch Center queue has only {available} waiting slots available"
                )
            accepted: list[dict[str, Any]] = []
            for request in requests:
                position = self.scheduler.enqueue(request.id)
                if position is None:
                    raise MediaCleanupBatchFullError("Cleanup Batch Center queue is full")
                self._records[request.id] = _CleanupRecord(
                    request=request,
                    input_name=request.input_name,
                    media_kind=request.media_kind,
                    mode=request.mode,
                    region_count=len(request.regions),
                    created_at=request.created_at,
                )
                accepted.append(
                    {
                        "accepted": True,
                        "id": request.id,
                        "state": QUEUED,
                        "position": position,
                    }
                )
            self._condition.notify_all()
            return accepted

    def start(self, executor: CleanupBatchExecutor) -> None:
        if not callable(executor):
            raise TypeError("executor must be callable")
        with self._condition:
            if self._workers:
                if self._executor is not executor:
                    raise MediaCleanupBatchError("Cleanup Batch Center already uses another executor")
                return
            if self._stopping:
                raise MediaCleanupBatchError("Cleanup Batch Center is closed")
            self._executor = executor
            for index in range(self.scheduler.concurrency_limit):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"galaxy-cleanup-worker-{index + 1}",
                    daemon=True,
                )
                self._workers.append(worker)
                worker.start()

    def start_default(self, ffmpeg_directory: Path) -> None:
        directory = ffmpeg_directory.expanduser().resolve()

        def executor(
            request: CleanupBatchRequest,
            cancel_event: threading.Event,
            progress_callback: Callable[[float, str], None],
        ) -> MediaCleanupResult:
            return execute_cleanup_batch_request(
                directory,
                request,
                cancel_event,
                progress_callback,
            )

        self.start(executor)

    def cancel(self, task_id: object) -> dict[str, Any]:
        clean = str(task_id or "").strip().lower()
        if not re.fullmatch(r"[a-f0-9]{32}", clean):
            return {"cancelled": False, "code": "CLEANUP_TASK_NOT_FOUND"}
        with self._condition:
            record = self._records.get(clean)
            if record is None:
                return {"cancelled": False, "code": "CLEANUP_TASK_NOT_FOUND"}
            if record.state == QUEUED:
                removed = self.scheduler.remove_first(lambda item: item == clean)
                if removed is None:
                    return {"cancelled": False, "code": "CLEANUP_TASK_NOT_FOUND"}
                record.cancel_event.set()
                self._finish_locked(record, CANCELLED)
                self._condition.notify_all()
                return {"cancelled": True, "state": CANCELLED}
            if record.state == RUNNING:
                record.cancel_event.set()
                record.state = CANCELLING
                record.status_message = "Cancellation requested"
                self._condition.notify_all()
                return {"cancelled": True, "state": CANCELLING}
            if record.state == CANCELLING:
                return {"cancelled": True, "state": CANCELLING}
            return {"cancelled": False, "state": record.state, "code": "CLEANUP_TASK_ALREADY_FINISHED"}

    def clear_waiting(self) -> int:
        with self._condition:
            waiting = list(self.scheduler.waiting)
            self.scheduler.clear()
            for task_id in waiting:
                record = self._records.get(task_id)
                if record is not None and record.state == QUEUED:
                    record.cancel_event.set()
                    self._finish_locked(record, CANCELLED)
            self._condition.notify_all()
            return len(waiting)

    def status(self, task_id: object) -> dict[str, Any] | None:
        clean = str(task_id or "").strip().lower()
        with self._condition:
            record = self._records.get(clean)
            return self._public_record_locked(clean, record) if record is not None else None

    def result_path(self, task_id: object) -> Path | None:
        clean = str(task_id or "").strip().lower()
        with self._condition:
            record = self._records.get(clean)
            return record.result_path if record is not None else None

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            positions = {
                task_id: index for index, task_id in enumerate(self.scheduler.waiting, start=1)
            }
            active = [
                self._public_record_locked(task_id, self._records[task_id])
                for task_id in sorted(
                    self._active,
                    key=lambda value: (self._records[value].started_at or 0.0, value),
                )
            ]
            waiting = [
                {
                    **self._public_record_locked(task_id, self._records[task_id]),
                    "position": positions[task_id],
                }
                for task_id in self.scheduler.waiting
            ]
            completed = [
                self._public_record_locked(task_id, record)
                for task_id, record in sorted(
                    self._records.items(),
                    key=lambda item: (item[1].finished_at or 0.0, item[0]),
                    reverse=True,
                )
                if record.state in TERMINAL_STATES
            ]
            return {
                "waitingCount": len(waiting),
                "activeCount": len(active),
                "concurrencyLimit": self.scheduler.concurrency_limit,
                "queueCapacity": self.scheduler.max_waiting,
                "active": active,
                "waiting": waiting,
                "completed": completed,
            }

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while self.scheduler.waiting_count or self._active:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def shutdown(self, *, cancel_running: bool = False, timeout: float = 5.0) -> None:
        with self._condition:
            self._stopping = True
            self.clear_waiting()
            if cancel_running:
                for task_id in tuple(self._active):
                    record = self._records.get(task_id)
                    if record is not None:
                        record.cancel_event.set()
                        if record.state == RUNNING:
                            record.state = CANCELLING
            self._condition.notify_all()
            workers = list(self._workers)
        deadline = time.monotonic() + max(0.0, float(timeout))
        for worker in workers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(remaining)
        with self._condition:
            self._workers = [worker for worker in self._workers if worker.is_alive()]

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                while not self._stopping and not (
                    self.scheduler.waiting_count and self.scheduler.can_start(len(self._active))
                ):
                    self._condition.wait()
                if self._stopping:
                    return
                task_id = self.scheduler.pop_next()
                if task_id is None:
                    continue
                record = self._records.get(task_id)
                if record is None or record.request is None or record.state != QUEUED:
                    continue
                record.state = RUNNING
                record.started_at = time.time()
                record.progress = 0.0
                record.status_message = "Running"
                self._active.add(task_id)
                request = record.request
                executor = self._executor
                self._condition.notify_all()

            def report(percent: float, message: str) -> None:
                with self._condition:
                    current = self._records.get(task_id)
                    if current is None or current.state not in {RUNNING, CANCELLING}:
                        return
                    current.progress = max(0.0, min(100.0, float(percent)))
                    current.status_message = _status_message(message) or current.status_message
                    self._condition.notify_all()

            state = SUCCEEDED
            error_code = ""
            error_detail = ""
            result_path: Path | None = None
            try:
                if executor is None:
                    raise MediaCleanupBatchError("Cleanup Batch Center executor is not configured")
                result = executor(request, record.cancel_event, report)
                result_path = Path(result.output_path).resolve()
                if record.cancel_event.is_set():
                    state = CANCELLED
                    result_path = None
            except Exception as exc:
                if record.cancel_event.is_set() or isinstance(exc, MediaCleanupCancelled):
                    state = CANCELLED
                else:
                    state = FAILED
                    error_code, error_detail = _error_payload(exc)

            with self._condition:
                current = self._records.get(task_id)
                if current is None:
                    continue
                current.error_code = error_code
                current.error_detail = error_detail
                current.result_path = result_path
                current.output_name = result_path.name if result_path is not None else ""
                self._active.discard(task_id)
                self._finish_locked(current, state)
                self._condition.notify_all()

    def _finish_locked(self, record: _CleanupRecord, state: str) -> None:
        record.state = state
        record.finished_at = time.time()
        record.progress = 100.0 if state == SUCCEEDED else record.progress
        if state == SUCCEEDED:
            record.status_message = "Completed"
        elif state == CANCELLED:
            record.status_message = "Cancelled"
        elif state == FAILED:
            record.status_message = "Failed"
        record.request = None
        self._prune_completed_locked()

    def _prune_completed_locked(self) -> None:
        completed = [
            (task_id, record.finished_at or 0.0)
            for task_id, record in self._records.items()
            if record.state in TERMINAL_STATES
        ]
        excess = len(completed) - self.max_completed_records
        if excess <= 0:
            return
        for task_id, _finished in sorted(completed, key=lambda item: (item[1], item[0]))[:excess]:
            self._records.pop(task_id, None)

    def _public_record_locked(self, task_id: str, record: _CleanupRecord) -> dict[str, Any]:
        return {
            "id": task_id,
            "state": record.state,
            "inputName": record.input_name,
            "mediaKind": record.media_kind,
            "mode": record.mode,
            "regionCount": record.region_count,
            "createdAt": record.created_at,
            "startedAt": record.started_at,
            "finishedAt": record.finished_at,
            "progress": round(record.progress, 2),
            "status": record.status_message,
            "outputName": record.output_name or None,
            "errorCode": record.error_code or None,
            "errorDetail": record.error_detail or None,
        }


def run_media_cleanup_batch_self_test() -> None:
    import tempfile
    from types import SimpleNamespace

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        first_file = root / "first.png"
        second_file = root / "second.png"
        first_file.write_bytes(b"fake-image")
        second_file.write_bytes(b"fake-image")
        region = {"x": 1, "y": 1, "width": 8, "height": 8}

        center = MediaCleanupBatchCenter(max_waiting=3, concurrency_limit=1, max_completed_records=10)
        first_started = threading.Event()
        release_first = threading.Event()
        executed: list[str] = []

        def executor(request, cancel_event, progress_callback):
            executed.append(request.input_name)
            progress_callback(42.0, "Working on local file")
            if request.input_name == "first.png":
                first_started.set()
                release_first.wait(3.0)
            if cancel_event.is_set():
                raise MediaCleanupCancelled("cancelled")
            output = root / f"{request.input_path.stem}.cleaned.png"
            return SimpleNamespace(output_path=output)

        accepted = center.submit_many(
            (
                {"inputPath": first_file, "regions": [region], "mode": "auto"},
                {"inputPath": second_file, "regions": [region], "mode": "image-inpaint"},
            )
        )
        assert [item["position"] for item in accepted] == [1, 2]
        center.start(executor)
        assert first_started.wait(3.0)
        snapshot = center.snapshot()
        rendered = json.dumps(snapshot)
        assert str(root) not in rendered
        assert snapshot["activeCount"] == 1 and snapshot["waitingCount"] == 1
        assert snapshot["active"][0]["progress"] == 42.0
        assert center.cancel(accepted[1]["id"])["state"] == CANCELLED
        release_first.set()
        assert center.wait_for_idle(3.0)
        first_status = center.status(accepted[0]["id"])
        second_status = center.status(accepted[1]["id"])
        assert first_status is not None and first_status["state"] == SUCCEEDED
        assert first_status["outputName"] == "first.cleaned.png"
        assert second_status is not None and second_status["state"] == CANCELLED
        assert executed == ["first.png"]
        assert center.result_path(accepted[0]["id"]) == root / "first.cleaned.png"
        center.shutdown()

        capacity = MediaCleanupBatchCenter(max_waiting=1)
        try:
            capacity.submit_many(
                (
                    {"inputPath": first_file, "regions": [region]},
                    {"inputPath": second_file, "regions": [region]},
                )
            )
        except MediaCleanupBatchFullError:
            pass
        else:
            raise AssertionError("oversized atomic batch was accepted")
        assert capacity.waiting_count == 0
        capacity.shutdown()

        try:
            _build_request(
                {
                    "inputPath": first_file,
                    "regions": [region],
                    "mode": "tracked-video",
                }
            )
        except MediaCleanupBatchError:
            pass
        else:
            raise AssertionError("tracked-video mode accepted an image")
