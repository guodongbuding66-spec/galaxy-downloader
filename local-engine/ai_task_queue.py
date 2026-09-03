from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from job_scheduler import JobScheduler

MAX_AI_QUEUE_ITEMS = 50
MAX_AI_CONTENT_CHARS = 450_000
MAX_AI_INSTRUCTIONS_CHARS = 20_000
MAX_AI_EXTRA_INSTRUCTION_CHARS = 4_000
MAX_AI_QUEUE_LABEL_CHARS = 120
MAX_AI_ERROR_CHARS = 1_400
MAX_AI_COMPLETED_RECORDS = 200

QUEUED = "queued"
RUNNING = "running"
CANCELLING = "cancelling"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"
TERMINAL_STATES = frozenset({SUCCEEDED, FAILED, CANCELLED})

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SECRET_DETAIL_RE = re.compile(
    r"(?i)(authorization|api[-_ ]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"
)


class AiQueueError(RuntimeError):
    pass


class AiQueueFullError(AiQueueError):
    pass


@dataclass(frozen=True)
class AiTaskRequest:
    id: str
    provider_id: str
    prompt_id: str
    instructions: str
    content: str
    extra_instruction: str
    label: str
    created_at: float

    @property
    def mode(self) -> str:
        return "template" if self.prompt_id else "raw"


@dataclass
class _TaskRecord:
    request: AiTaskRequest | None
    provider_id: str
    prompt_id: str
    mode: str
    label: str
    created_at: float
    state: str = QUEUED
    started_at: float | None = None
    finished_at: float | None = None
    error_code: str = ""
    error_detail: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)


AiTaskExecutor = Callable[[AiTaskRequest, threading.Event], Any]


def _clean_id(value: object, *, field_name: str, allow_empty: bool = False) -> str:
    clean = str(value or "").strip().lower()
    if not clean and allow_empty:
        return ""
    if not _ID_RE.fullmatch(clean):
        raise AiQueueError(f"{field_name} 无效")
    return clean


def _clean_label(value: object, fallback: str) -> str:
    label = " ".join(str(value or fallback).split()).strip()
    return (label or fallback)[:MAX_AI_QUEUE_LABEL_CHARS]


def _clean_text(value: object, *, field_name: str, limit: int, allow_empty: bool = False) -> str:
    text = str(value or "").strip()
    if not text and not allow_empty:
        raise AiQueueError(f"{field_name} 不能为空")
    if len(text) > limit:
        raise AiQueueError(f"{field_name} 超过安全长度限制")
    return text


def _error_payload(exc: Exception) -> tuple[str, str]:
    code = str(getattr(exc, "code", "") or exc.__class__.__name__).strip().upper()
    code = re.sub(r"[^A-Z0-9_-]", "_", code)[:64] or "AI_TASK_FAILED"
    detail = " ".join(str(exc or code).replace("\x00", " ").split()).strip()
    detail = _SECRET_DETAIL_RE.sub(lambda match: match.group(1) + ": [REDACTED]", detail)
    return code, detail[-MAX_AI_ERROR_CHARS:] or code


class AiTaskQueue:
    """Bounded in-memory FIFO queue for AI work.

    This contract owns lifecycle, bounded concurrency and cooperative
    cancellation only. Provider networking and artifact/history persistence stay
    outside the queue and are supplied through the executor callback.

    Public status deliberately excludes prompt instructions and source content.
    Completed tasks drop their request payload immediately so large transcripts
    are not retained by queue metadata.
    """

    def __init__(
        self,
        *,
        max_waiting: int = MAX_AI_QUEUE_ITEMS,
        concurrency_limit: int = 1,
        max_completed_records: int = MAX_AI_COMPLETED_RECORDS,
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
        self._records: dict[str, _TaskRecord] = {}
        self._active: set[str] = set()
        self._executor: AiTaskExecutor | None = None
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

    def submit(
        self,
        *,
        provider_id: object,
        content: object,
        prompt_id: object = "",
        instructions: object = "",
        extra_instruction: object = "",
        label: object = "",
    ) -> dict[str, Any]:
        provider = _clean_id(provider_id, field_name="Provider ID")
        prompt = _clean_id(prompt_id, field_name="Prompt ID", allow_empty=True)
        body = _clean_text(content, field_name="AI 输入内容", limit=MAX_AI_CONTENT_CHARS)
        system = _clean_text(
            instructions,
            field_name="Prompt instructions",
            limit=MAX_AI_INSTRUCTIONS_CHARS,
            allow_empty=bool(prompt),
        )
        extra = _clean_text(
            extra_instruction,
            field_name="额外要求",
            limit=MAX_AI_EXTRA_INSTRUCTION_CHARS,
            allow_empty=True,
        )
        if not prompt and not system:
            raise AiQueueError("Raw AI task 必须提供 instructions")

        task_id = uuid.uuid4().hex
        request = AiTaskRequest(
            id=task_id,
            provider_id=provider,
            prompt_id=prompt,
            instructions=system,
            content=body,
            extra_instruction=extra,
            label=_clean_label(label, prompt or provider),
            created_at=time.time(),
        )
        record = _TaskRecord(
            request=request,
            provider_id=request.provider_id,
            prompt_id=request.prompt_id,
            mode=request.mode,
            label=request.label,
            created_at=request.created_at,
        )
        with self._condition:
            if self._stopping:
                raise AiQueueError("AI Queue 正在关闭")
            position = self.scheduler.enqueue(task_id)
            if position is None:
                raise AiQueueFullError(
                    f"AI Queue 已满（最多 {self.scheduler.max_waiting} 个等待任务）"
                )
            self._records[task_id] = record
            self._condition.notify_all()
            return {
                "accepted": True,
                "id": task_id,
                "state": QUEUED,
                "position": position,
            }

    def start(self, executor: AiTaskExecutor) -> None:
        if not callable(executor):
            raise TypeError("executor must be callable")
        with self._condition:
            if self._workers:
                if self._executor is not executor:
                    raise AiQueueError("AI Queue 已经使用另一个 executor 启动")
                return
            if self._stopping:
                raise AiQueueError("AI Queue 已关闭")
            self._executor = executor
            for index in range(self.scheduler.concurrency_limit):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"galaxy-ai-worker-{index + 1}",
                    daemon=True,
                )
                self._workers.append(worker)
                worker.start()

    def cancel(self, task_id: object) -> dict[str, Any]:
        clean = str(task_id or "").strip().lower()
        if not re.fullmatch(r"[a-f0-9]{32}", clean):
            return {"cancelled": False, "code": "AI_TASK_NOT_FOUND"}
        with self._condition:
            record = self._records.get(clean)
            if record is None:
                return {"cancelled": False, "code": "AI_TASK_NOT_FOUND"}
            if record.state == QUEUED:
                removed = self.scheduler.remove_first(lambda item: item == clean)
                if removed is None:
                    return {"cancelled": False, "code": "AI_TASK_NOT_FOUND"}
                record.cancel_event.set()
                self._finish_locked(record, CANCELLED)
                self._condition.notify_all()
                return {"cancelled": True, "code": "AI_TASK_CANCELLED", "state": CANCELLED}
            if record.state == RUNNING:
                record.cancel_event.set()
                record.state = CANCELLING
                self._condition.notify_all()
                return {
                    "cancelled": True,
                    "code": "AI_TASK_CANCEL_REQUESTED",
                    "state": CANCELLING,
                }
            if record.state == CANCELLING:
                return {
                    "cancelled": True,
                    "code": "AI_TASK_CANCEL_REQUESTED",
                    "state": CANCELLING,
                }
            return {
                "cancelled": False,
                "code": "AI_TASK_ALREADY_FINISHED",
                "state": record.state,
            }

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

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            queue_positions = {
                task_id: index
                for index, task_id in enumerate(self.scheduler.waiting, start=1)
            }
            active = [
                self._public_record_locked(task_id, self._records[task_id])
                for task_id in sorted(
                    self._active,
                    key=lambda value: (
                        self._records[value].started_at or 0.0,
                        value,
                    ),
                )
            ]
            waiting = [
                {
                    **self._public_record_locked(task_id, self._records[task_id]),
                    "position": queue_positions[task_id],
                }
                for task_id in self.scheduler.waiting
            ]
            return {
                "waitingCount": len(waiting),
                "activeCount": len(active),
                "concurrencyLimit": self.scheduler.concurrency_limit,
                "queueCapacity": self.scheduler.max_waiting,
                "active": active,
                "waiting": waiting,
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
                    self.scheduler.waiting_count
                    and self.scheduler.can_start(len(self._active))
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
                self._active.add(task_id)
                request = record.request
                executor = self._executor
                self._condition.notify_all()

            state = SUCCEEDED
            error_code = ""
            error_detail = ""
            try:
                if executor is None:
                    raise AiQueueError("AI Queue executor 未配置")
                executor(request, record.cancel_event)
                if record.cancel_event.is_set():
                    state = CANCELLED
            except Exception as exc:
                if record.cancel_event.is_set():
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
                self._active.discard(task_id)
                self._finish_locked(current, state)
                self._condition.notify_all()

    def _finish_locked(self, record: _TaskRecord, state: str) -> None:
        record.state = state
        record.finished_at = time.time()
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

    def _public_record_locked(self, task_id: str, record: _TaskRecord) -> dict[str, Any]:
        return {
            "id": task_id,
            "state": record.state,
            "providerId": record.provider_id,
            "promptId": record.prompt_id or None,
            "mode": record.mode,
            "label": record.label,
            "createdAt": record.created_at,
            "startedAt": record.started_at,
            "finishedAt": record.finished_at,
            "errorCode": record.error_code or None,
            "errorDetail": record.error_detail or None,
        }


def run_ai_task_queue_self_test() -> None:
    class ExpectedFailure(RuntimeError):
        code = "RATE_LIMIT"

    queue = AiTaskQueue(max_waiting=2, concurrency_limit=1, max_completed_records=10)
    first_started = threading.Event()
    release_first = threading.Event()
    executed: list[str] = []

    def executor(request: AiTaskRequest, cancel_event: threading.Event) -> None:
        executed.append(request.label)
        if request.label == "first":
            first_started.set()
            release_first.wait(5.0)
            return
        if request.label == "failure":
            raise ExpectedFailure("rate limited")

    first = queue.submit(
        provider_id="openai",
        instructions="Summarize",
        content="secret first content",
        label="first",
    )
    second = queue.submit(
        provider_id="openai",
        prompt_id="summary",
        content="secret second content",
        label="second",
    )
    try:
        queue.submit(
            provider_id="openai",
            prompt_id="summary",
            content="overflow",
            label="overflow",
        )
    except AiQueueFullError:
        pass
    else:
        raise AssertionError("queue overflow was accepted")

    snapshot = queue.snapshot()
    assert snapshot["waitingCount"] == 2
    assert "secret first content" not in repr(snapshot)
    assert "secret second content" not in repr(snapshot)

    queue.start(executor)
    assert first_started.wait(2.0)
    assert queue.status(first["id"])["state"] == RUNNING
    assert queue.cancel(second["id"])["state"] == CANCELLED
    assert queue.cancel(first["id"])["state"] == CANCELLING
    release_first.set()
    assert queue.wait_for_idle(3.0)
    assert queue.status(first["id"])["state"] == CANCELLED
    assert queue.status(first["id"])["providerId"] == "openai"
    assert "second" not in executed

    failure = queue.submit(
        provider_id="openai",
        instructions="Fail",
        content="failure content",
        label="failure",
    )
    assert queue.wait_for_idle(3.0)
    failure_status = queue.status(failure["id"])
    assert failure_status["state"] == FAILED
    assert failure_status["errorCode"] == "RATE_LIMIT"
    assert failure_status["errorDetail"] == "rate limited"
    assert "failure content" not in repr(failure_status)

    success = queue.submit(
        provider_id="openai",
        prompt_id="summary",
        content="third content",
        label="third",
    )
    assert queue.wait_for_idle(3.0)
    assert queue.status(success["id"])["state"] == SUCCEEDED
    assert queue.cancel(success["id"])["code"] == "AI_TASK_ALREADY_FINISHED"

    try:
        queue.submit(provider_id="../bad", instructions="x", content="y")
    except AiQueueError:
        pass
    else:
        raise AssertionError("unsafe provider id was accepted")

    queue.shutdown(timeout=1.0)
