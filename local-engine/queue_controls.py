from __future__ import annotations

from typing import Any


def install_queue_controls(engine_module):
    """Add pause-after-current and reordering to the bounded waiting queue.

    These controls never pause or mutate the active downloader. They only govern
    the waiting list that job_queue.py already owns.
    """
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_queue_controls_installed", False):
        return window_cls

    original_start_next = window_cls._start_next_queued_job
    original_bridge_status = window_cls.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        payload["queuePaused"] = bool(getattr(window, "queue_paused", False))
        return payload

    def set_queue_paused(window, paused: bool) -> bool:
        window.queue_paused = bool(paused)
        if not window.queue_paused and not bool(getattr(window, "running", False)):
            original_start_next(window)
        return window.queue_paused

    def toggle_queue_paused(window) -> bool:
        return set_queue_paused(window, not bool(getattr(window, "queue_paused", False)))

    def move_queued_job(window, job_id: str, direction: int) -> bool:
        if getattr(window, "_galaxy_close_pending", False):
            return False
        lock = getattr(window, "_queue_lock", None)
        pending = getattr(window, "pending_jobs", None)
        if lock is None or not isinstance(pending, list):
            return False
        step = -1 if int(direction) < 0 else 1
        with lock:
            index = next(
                (
                    idx
                    for idx, queued in enumerate(pending)
                    if str(getattr(queued, "job_id", "")) == str(job_id)
                ),
                -1,
            )
            if index < 0:
                return False
            target = index + step
            if target < 0 or target >= len(pending):
                return False
            pending[index], pending[target] = pending[target], pending[index]
        return True

    def start_next_queued_job(window) -> None:
        if bool(getattr(window, "queue_paused", False)):
            return
        original_start_next(window)

    window_cls.bridge_status = bridge_status
    window_cls.set_queue_paused = set_queue_paused
    window_cls.toggle_queue_paused = toggle_queue_paused
    window_cls.move_queued_job = move_queued_job
    window_cls._start_next_queued_job = start_next_queued_job
    window_cls._galaxy_queue_controls_installed = True
    return window_cls


def run_queue_controls_self_test() -> None:
    class Queued:
        def __init__(self, job_id: str):
            self.job_id = job_id

    class FakeWindow:
        def __init__(self, _job=None):
            import threading

            self.pending_jobs = [Queued("a"), Queued("b"), Queued("c")]
            self._queue_lock = threading.Lock()
            self.running = True
            self.started = 0

        def bridge_status(self):
            return {"queueLength": len(self.pending_jobs)}

        def _start_next_queued_job(self):
            self.started += 1

    class FakeEngine:
        EngineWindow = FakeWindow

    install_queue_controls(FakeEngine)
    window = FakeEngine.EngineWindow(None)
    assert window.move_queued_job("b", -1) is True
    assert [item.job_id for item in window.pending_jobs] == ["b", "a", "c"]
    assert window.move_queued_job("b", -1) is False
    assert window.set_queue_paused(True) is True
    assert window.bridge_status()["queuePaused"] is True
    window.running = False
    assert window.set_queue_paused(False) is False
    assert window.started == 1
