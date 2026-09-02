from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import job_queue  # noqa: E402
from batch_input import parse_batch_input  # noqa: E402
from batch_submission import run_batch_submission_self_test  # noqa: E402
from bridge_submission_policy import StructuredLocalBridge  # noqa: E402
from job_scheduler import run_job_scheduler_self_test  # noqa: E402


class _FakeWindow:
    def __init__(self, job):
        self.job = job
        self.running = False
        self.started: list[object] = []

    def bridge_status(self):
        return {"busy": self.running}

    def after(self, _delay, callback, *args):
        callback(*args)

    def ui(self, callback, *args):
        callback(*args)

    def deiconify(self):
        pass

    def lift(self):
        pass

    def focus_force(self):
        pass

    def start_job(self):
        self.running = True
        self.started.append(self.job)

    def _run_job(self):
        self.running = False


class LocalJobQueueTests(unittest.TestCase):
    def make_window(self):
        fake_engine = types.SimpleNamespace(
            EngineWindow=_FakeWindow,
            LocalBridge=object,
            job_from_payload=lambda payload: dict(payload),
        )
        window_type = job_queue.install_job_queue_policy(fake_engine)
        return fake_engine, window_type(None)

    def queue(self, window, source_url: str, title: str | None = None):
        window.running = True
        payload = {"sourceUrl": source_url}
        if title is not None:
            payload["displayTitle"] = title
        result = window.submit_bridge_job(payload)
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "QUEUED")
        return window.pending_jobs[-1]

    def test_scheduler_core_self_test(self):
        run_job_scheduler_self_test()

    def test_batch_submission_controller_self_test(self):
        run_batch_submission_self_test()

    def test_idle_job_starts_immediately(self):
        fake_engine, window = self.make_window()
        result = window.submit_bridge_job({"sourceUrl": "https://example.com/1"})
        accepted, message = result
        self.assertTrue(accepted)
        self.assertEqual(message, "Download job accepted")
        self.assertEqual(result.status, 202)
        self.assertEqual(result.code, "ACCEPTED")
        self.assertIs(fake_engine.LocalBridge, StructuredLocalBridge)
        self.assertTrue(window.running)
        self.assertEqual(window.started[-1]["sourceUrl"], "https://example.com/1")
        self.assertEqual(window.pending_jobs, [])
        self.assertIs(window.pending_jobs, window.scheduler.waiting)
        self.assertEqual(window.scheduler.max_waiting, job_queue.MAX_QUEUED_MEDIA_JOBS)
        self.assertEqual(window.scheduler.concurrency_limit, 1)

    def test_batch_submission_starts_first_and_queues_remaining_in_order(self):
        _engine, window = self.make_window()
        batch = parse_batch_input(
            "https://example.com/1\nhttps://example.com/2\nhttps://example.com/3\n",
            format_hint="txt",
        )
        result = window.submit_batch_jobs_from_bridge(batch, {"videoQuality": "720p"})
        self.assertEqual(result.accepted_count, 3)
        self.assertEqual(result.started_count, 1)
        self.assertEqual(result.queued_count, 2)
        self.assertEqual(result.remaining_count, 0)
        self.assertTrue(result.batch_id)
        self.assertEqual(window.started[-1]["batchId"], result.batch_id)
        self.assertEqual(window.started[-1]["batchIndex"], 1)
        self.assertEqual(window.started[-1]["batchSize"], 3)
        self.assertEqual(window.started[-1]["sourceUrl"], "https://example.com/1")
        self.assertEqual(window.started[-1]["videoQuality"], "720p")
        self.assertEqual(
            [queued.job["sourceUrl"] for queued in window.pending_jobs],
            ["https://example.com/2", "https://example.com/3"],
        )
        self.assertTrue(all(queued.job["videoQuality"] == "720p" for queued in window.pending_jobs))
        self.assertEqual([queued.job["batchIndex"] for queued in window.pending_jobs], [2, 3])
        self.assertTrue(all(queued.job["batchId"] == result.batch_id for queued in window.pending_jobs))
        queued_status = window.bridge_status()["queuedJobs"]
        self.assertEqual([item["batchIndex"] for item in queued_status], [2, 3])
        self.assertTrue(all(item["batchId"] == result.batch_id for item in queued_status))

    def test_batch_submission_bad_request_isolated_to_one_row(self):
        fake_engine, window = self.make_window()

        def normalize(payload):
            if str(payload.get("sourceUrl") or "").endswith("/bad"):
                raise ValueError("A valid public HTTP URL is required")
            return dict(payload)

        fake_engine.job_from_payload = normalize
        batch = parse_batch_input(
            "https://example.com/1\nhttps://example.com/bad\nhttps://example.com/3\n",
            format_hint="txt",
        )
        result = window.submit_batch_jobs_from_bridge(batch, {})
        self.assertEqual(result.accepted_count, 2)
        self.assertEqual(result.rejected_count, 1)
        self.assertEqual(result.remaining_count, 0)
        self.assertFalse(result.stopped)
        self.assertEqual([outcome.code for outcome in result.outcomes], ["ACCEPTED", "BAD_REQUEST", "QUEUED"])
        self.assertEqual(window.started[-1]["sourceUrl"], "https://example.com/1")
        self.assertEqual(
            [queued.job["sourceUrl"] for queued in window.pending_jobs],
            ["https://example.com/3"],
        )

    def test_busy_job_is_queued_with_safe_visible_summary(self):
        _engine, window = self.make_window()
        queued = self.queue(
            window,
            "https://example.com/watch?id=secret-token",
            "  Example   title  ",
        )
        status = window.bridge_status()
        self.assertEqual(status["queueLength"], 1)
        self.assertEqual(status["queueCapacity"], job_queue.MAX_QUEUED_MEDIA_JOBS)
        self.assertEqual(status["queuedJobs"], [
            {
                "id": queued.job_id,
                "position": 1,
                "label": "Example title",
                "sourceHost": "example.com",
            }
        ])
        rendered = repr(status["queuedJobs"])
        self.assertNotIn("secret-token", rendered)
        self.assertNotIn("sourceUrl", rendered)

    def test_hostname_is_fallback_label_without_display_title(self):
        _engine, window = self.make_window()
        queued = self.queue(window, "https://media.example.org/private/path?token=hidden")
        self.assertEqual(queued.label, "media.example.org")
        self.assertEqual(queued.source_host, "media.example.org")

    def test_next_job_starts_after_current_worker_finishes(self):
        _engine, window = self.make_window()
        self.queue(window, "https://example.com/2")
        self.queue(window, "https://example.com/3")
        window._run_job()
        self.assertTrue(window.running)
        self.assertEqual(window.started[-1]["sourceUrl"], "https://example.com/2")
        self.assertEqual(
            [queued.job["sourceUrl"] for queued in window.pending_jobs],
            ["https://example.com/3"],
        )

    def test_queue_is_bounded_with_conflict_status(self):
        _engine, window = self.make_window()
        window.running = True
        for index in range(job_queue.MAX_QUEUED_MEDIA_JOBS):
            queued = job_queue._queued_media_job(
                {"sourceUrl": f"https://example.com/{index}"},
                {"sourceUrl": f"https://example.com/{index}"},
            )
            window.pending_jobs.append(queued)
        result = window.submit_bridge_job({"sourceUrl": "https://example.com/overflow"})
        accepted, message = result
        self.assertFalse(accepted)
        self.assertIn("queue is full", message.lower())
        self.assertEqual(result.status, 409)
        self.assertEqual(result.code, "QUEUE_FULL")
        self.assertEqual(len(window.pending_jobs), job_queue.MAX_QUEUED_MEDIA_JOBS)
        self.assertEqual(window.scheduler.waiting_count, job_queue.MAX_QUEUED_MEDIA_JOBS)

    def test_cancel_one_waiting_job_preserves_fifo_order(self):
        _engine, window = self.make_window()
        first = self.queue(window, "https://example.com/1", "One")
        second = self.queue(window, "https://example.com/2", "Two")
        third = self.queue(window, "https://example.com/3", "Three")

        result = window.cancel_queued_job_from_bridge(second.job_id)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.status, 200)
        self.assertEqual(result.code, "QUEUE_ITEM_CANCELLED")
        self.assertEqual([queued.job_id for queued in window.pending_jobs], [first.job_id, third.job_id])
        self.assertEqual(
            [item["position"] for item in window.bridge_status()["queuedJobs"]],
            [1, 2],
        )

    def test_cancel_unknown_waiting_job_is_not_found(self):
        _engine, window = self.make_window()
        self.queue(window, "https://example.com/1")
        result = window.cancel_queued_job_from_bridge("0" * 32)
        self.assertFalse(result.cancelled)
        self.assertEqual(result.status, 404)
        self.assertEqual(result.code, "QUEUE_ITEM_NOT_FOUND")
        self.assertEqual(len(window.pending_jobs), 1)

    def test_shutting_down_rejects_with_service_unavailable(self):
        _engine, window = self.make_window()
        window._galaxy_close_pending = True
        result = window.submit_bridge_job({"sourceUrl": "https://example.com/new"})
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, 503)
        self.assertEqual(result.code, "ENGINE_SHUTTING_DOWN")

    def test_shutting_down_rejects_queue_cancellation(self):
        _engine, window = self.make_window()
        queued = self.queue(window, "https://example.com/1")
        window._galaxy_close_pending = True
        result = window.cancel_queued_job_from_bridge(queued.job_id)
        self.assertFalse(result.cancelled)
        self.assertEqual(result.status, 503)
        self.assertEqual(result.code, "ENGINE_SHUTTING_DOWN")

    def test_invalid_payload_is_bad_request(self):
        fake_engine, window = self.make_window()

        def invalid(_payload):
            raise ValueError("A valid public HTTP URL is required")

        fake_engine.job_from_payload = invalid
        result = window.submit_bridge_job({"sourceUrl": "file:///secret"})
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, 400)
        self.assertEqual(result.code, "BAD_REQUEST")

    def test_shutdown_drops_waiting_jobs_without_overwriting_active_state(self):
        _engine, window = self.make_window()
        self.queue(window, "https://example.com/1")
        self.queue(window, "https://example.com/2")
        window._galaxy_close_pending = True
        window._start_next_queued_job()
        self.assertEqual(window.pending_jobs, [])
        self.assertTrue(window.running)
        self.assertEqual(window.started, [])

    def test_clear_queued_jobs_returns_removed_count(self):
        _engine, window = self.make_window()
        self.queue(window, "https://example.com/1")
        self.queue(window, "https://example.com/2")
        self.assertEqual(window.clear_queued_jobs(), 2)
        self.assertEqual(window.bridge_status()["queuedJobs"], [])

    def test_install_is_idempotent(self):
        fake_engine, _window = self.make_window()
        first = fake_engine.EngineWindow
        second = job_queue.install_job_queue_policy(fake_engine)
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
