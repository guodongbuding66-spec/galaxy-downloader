from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, got {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


job_queue = ROOT / "local-engine" / "job_queue.py"
replace_once(
    job_queue,
    'from bridge_submission_policy import (\n    JobSubmissionResult,\n    QueueCancellationResult,\n    StructuredLocalBridge,\n)\n',
    'from bridge_submission_policy import (\n    JobSubmissionResult,\n    QueueCancellationResult,\n    StructuredLocalBridge,\n)\nfrom job_scheduler import JobScheduler\n',
)
replace_once(
    job_queue,
    '        def __init__(self, job):\n            self.pending_jobs: list[QueuedMediaJob] = []\n            self._queue_lock = threading.Lock()\n            super().__init__(job)\n',
    '        def __init__(self, job):\n            self.scheduler = JobScheduler[QueuedMediaJob](\n                max_waiting=MAX_QUEUED_MEDIA_JOBS,\n                concurrency_limit=1,\n            )\n            # Compatibility alias: queue controls and desktop presenters still\n            # operate on this exact list while lifecycle operations migrate to\n            # JobScheduler. Keep the list identity stable.\n            self.pending_jobs = self.scheduler.waiting\n            self._queue_lock = threading.Lock()\n            super().__init__(job)\n',
)
replace_once(
    job_queue,
    '''                    with self._queue_lock:
                        if len(self.pending_jobs) >= MAX_QUEUED_MEDIA_JOBS:
                            queue_position = None
                        else:
                            queued = _queued_media_job(payload, job)
                            self.pending_jobs.append(queued)
                            queue_position = len(self.pending_jobs)
''',
    '''                    queued = _queued_media_job(payload, job)
                    with self._queue_lock:
                        queue_position = self.scheduler.enqueue(queued)
''',
)
replace_once(
    job_queue,
    '            with self._queue_lock:\n                queued = self.pending_jobs.pop(0) if self.pending_jobs else None\n',
    '            with self._queue_lock:\n                queued = self.scheduler.pop_next()\n',
)
replace_once(
    job_queue,
    '''                removed: QueuedMediaJob | None = None
                with self._queue_lock:
                    for index, queued in enumerate(self.pending_jobs):
                        if queued.job_id == job_id:
                            removed = self.pending_jobs.pop(index)
                            break
''',
    '''                with self._queue_lock:
                    removed = self.scheduler.remove_first(lambda queued: queued.job_id == job_id)
''',
)
replace_once(
    job_queue,
    '''        def clear_queued_jobs(self) -> int:
            with self._queue_lock:
                count = len(self.pending_jobs)
                self.pending_jobs.clear()
            return count
''',
    '''        def clear_queued_jobs(self) -> int:
            with self._queue_lock:
                return self.scheduler.clear()
''',
)

queue_test = ROOT / "scripts" / "test-local-job-queue.py"
replace_once(
    queue_test,
    '        self.assertEqual(window.started[-1]["sourceUrl"], "https://example.com/1")\n        self.assertEqual(window.pending_jobs, [])\n',
    '        self.assertEqual(window.started[-1]["sourceUrl"], "https://example.com/1")\n        self.assertEqual(window.pending_jobs, [])\n        self.assertIs(window.pending_jobs, window.scheduler.waiting)\n        self.assertEqual(window.scheduler.max_waiting, job_queue.MAX_QUEUED_MEDIA_JOBS)\n        self.assertEqual(window.scheduler.concurrency_limit, 1)\n',
)
replace_once(
    queue_test,
    '        self.assertEqual(len(window.pending_jobs), job_queue.MAX_QUEUED_MEDIA_JOBS)\n',
    '        self.assertEqual(len(window.pending_jobs), job_queue.MAX_QUEUED_MEDIA_JOBS)\n        self.assertEqual(window.scheduler.waiting_count, job_queue.MAX_QUEUED_MEDIA_JOBS)\n',
)

entrypoint = ROOT / "local-engine" / "entrypoint.py"
replace_once(
    entrypoint,
    'from job_queue import install_job_queue_policy\n',
    'from job_queue import install_job_queue_policy\nfrom job_scheduler import run_job_scheduler_self_test\n',
)
replace_once(
    entrypoint,
    '    run_queue_controls_self_test()\n',
    '    run_job_scheduler_self_test()\n    run_queue_controls_self_test()\n',
)

ci = ROOT / ".github" / "workflows" / "ci.yml"
replace_once(
    ci,
    '            local-engine/job_queue.py \\\n            local-engine/queue_controls.py \\\n',
    '            local-engine/job_queue.py \\\n            local-engine/job_scheduler.py \\\n            local-engine/queue_controls.py \\\n',
)
replace_once(
    ci,
    '          python3 scripts/test-local-job-queue.py\n',
    '          python3 scripts/test-local-job-scheduler.py\n          python3 scripts/test-local-job-queue.py\n',
)

windows = ROOT / ".github" / "workflows" / "local-engine-windows.yml"
# Add explicit test-only path triggers in both pull_request and push sections.
text = windows.read_text(encoding="utf-8")
needle = "      - 'scripts/test-local-job-queue.py'\n"
if text.count(needle) != 2:
    raise RuntimeError(f"{windows}: expected two job-queue path entries, got {text.count(needle)}")
text = text.replace(needle, "      - 'scripts/test-local-job-scheduler.py'\n" + needle)
windows.write_text(text, encoding="utf-8")
replace_once(
    windows,
    '          local-engine/job_queue.py\n          local-engine/queue_controls.py\n',
    '          local-engine/job_queue.py\n          local-engine/job_scheduler.py\n          local-engine/queue_controls.py\n',
)
replace_once(
    windows,
    '          python scripts/test-local-job-queue.py\n',
    '          python scripts/test-local-job-scheduler.py\n          python scripts/test-local-job-queue.py\n',
)

release = ROOT / ".github" / "workflows" / "local-engine-release.yml"
replace_once(
    release,
    '            local-engine/job_queue.py `\n            local-engine/queue_controls.py `\n',
    '            local-engine/job_queue.py `\n            local-engine/job_scheduler.py `\n            local-engine/queue_controls.py `\n',
)
replace_once(
    release,
    '          python scripts/test-local-job-queue.py\n',
    '          python scripts/test-local-job-scheduler.py\n          python scripts/test-local-job-queue.py\n',
)

print("scheduler core integration applied")
