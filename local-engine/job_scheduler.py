from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class JobScheduler(Generic[T]):
    """Small deterministic scheduler core shared by queue and future batch work.

    Phase 1 deliberately keeps execution policy outside this class. The current
    Local Engine still owns exactly one active media worker; this scheduler owns
    only the ordered waiting set plus the future concurrency limit contract.

    `waiting` is intentionally a stable list object. Existing queue controls and
    UI code can keep a compatibility alias to it while enqueue/pop/cancel/clear
    migrate behind this API one operation at a time.
    """

    def __init__(self, *, max_waiting: int, concurrency_limit: int = 1) -> None:
        max_waiting_value = int(max_waiting)
        concurrency_value = int(concurrency_limit)
        if max_waiting_value <= 0:
            raise ValueError("max_waiting must be greater than zero")
        if concurrency_value <= 0:
            raise ValueError("concurrency_limit must be greater than zero")
        self.max_waiting = max_waiting_value
        self.concurrency_limit = concurrency_value
        self.waiting: list[T] = []

    @property
    def waiting_count(self) -> int:
        return len(self.waiting)

    def can_accept_waiting(self) -> bool:
        return self.waiting_count < self.max_waiting

    def available_start_slots(self, active_count: int) -> int:
        active = max(0, int(active_count))
        return max(0, self.concurrency_limit - active)

    def can_start(self, active_count: int) -> bool:
        return self.available_start_slots(active_count) > 0

    def enqueue(self, item: T) -> int | None:
        """Append one waiting job and return its 1-based queue position."""
        if not self.can_accept_waiting():
            return None
        self.waiting.append(item)
        return self.waiting_count

    def pop_next(self) -> T | None:
        """Pop the oldest waiting job while preserving FIFO semantics."""
        return self.waiting.pop(0) if self.waiting else None

    def remove_first(self, predicate: Callable[[T], bool]) -> T | None:
        """Remove the first matching waiting job without disturbing others."""
        for index, item in enumerate(self.waiting):
            if predicate(item):
                return self.waiting.pop(index)
        return None

    def clear(self) -> int:
        count = self.waiting_count
        self.waiting.clear()
        return count


def run_job_scheduler_self_test() -> None:
    scheduler = JobScheduler[str](max_waiting=2, concurrency_limit=1)
    waiting_identity = scheduler.waiting
    assert scheduler.available_start_slots(0) == 1
    assert scheduler.available_start_slots(1) == 0
    assert scheduler.enqueue("one") == 1
    assert scheduler.enqueue("two") == 2
    assert scheduler.enqueue("overflow") is None
    assert scheduler.pop_next() == "one"
    assert scheduler.remove_first(lambda item: item == "two") == "two"
    assert scheduler.waiting is waiting_identity
    assert scheduler.clear() == 0

    future = JobScheduler[int](max_waiting=3, concurrency_limit=3)
    assert future.available_start_slots(0) == 3
    assert future.available_start_slots(2) == 1
    assert future.can_start(3) is False
