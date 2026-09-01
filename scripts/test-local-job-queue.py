from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import job_queue  # noqa: E402
from bridge_submission_policy import StructuredLocalBridge  # noqa: E402


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

    def test_busy_job_is_queued_and_reported_in_status(self):
        _engine, window = self.make_window()
        window.running = True
        result = window.submit_bridge_job({"sourceUrl": "https://example.com/2"})
        accepted, message = result
        self.assertTrue(accepted)
        self.assertIn("position 1", message)
        self.assertEqual(result.status, 202)
        self.assertEqual(result.code, "QUEUED")
        self.assertEqual(len(window.pending_jobs), 1)
        self.assertEqual(window.bridge_status()["queueLength"], 1)

    def test_next_job_starts_after_current_worker_finishes(self):
        _engine, window = self.make_window()
        window.running = True
        window.pending_jobs.extend([
            {"sourceUrl": "https://example.com/2"},
            {"sourceUrl": "https://example.com/3"},
        ])
        window._run_job()
        self.assertTrue(window.running)
        self.assertEqual(window.started[-1]["sourceUrl"], "https://example.com/2")
        self.assertEqual([job["sourceUrl"] for job in window.pending_jobs], ["https://example.com/3"])

    def test_queue_is_bounded_with_conflict_status(self):
        _engine, window = self.make_window()
        window.running = True
        window.pending_jobs.extend({"id": index} for index in range(job_queue.MAX_QUEUED_MEDIA_JOBS))
        result = window.submit_bridge_job({"sourceUrl": "https://example.com/overflow"})
        accepted, message = result
        self.assertFalse(accepted)
        self.assertIn("queue is full", message.lower())
        self.assertEqual(result.status, 409)
        self.assertEqual(result.code, "QUEUE_FULL")
        self.assertEqual(len(window.pending_jobs), job_queue.MAX_QUEUED_MEDIA_JOBS)

    def test_shutting_down_rejects_with_service_unavailable(self):
        _engine, window = self.make_window()
        window._galaxy_close_pending = True
        result = window.submit_bridge_job({"sourceUrl": "https://example.com/new"})
        self.assertFalse(result.accepted)
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

    def test_shutdown_drops_waiting_jobs(self):
        _engine, window = self.make_window()
        window.pending_jobs.extend([{"id": 1}, {"id": 2}])
        window._galaxy_close_pending = True
        window._start_next_queued_job()
        self.assertEqual(window.pending_jobs, [])
        self.assertFalse(window.running)

    def test_install_is_idempotent(self):
        fake_engine, _window = self.make_window()
        first = fake_engine.EngineWindow
        second = job_queue.install_job_queue_policy(fake_engine)
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
