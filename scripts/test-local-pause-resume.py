from __future__ import annotations

import importlib.util
import sys
import tempfile
import threading
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pause_resume = load_module(
    "galaxy_pause_resume_lifecycle_test",
    ROOT / "local-engine" / "pause_resume_policy.py",
)


class Value:
    def __init__(self, value: object) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value: object) -> None:
        self.value = value


@dataclass(frozen=True)
class FakeJob:
    source_url: str
    video_quality: str = "best"


class PauseResumeLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

        root = self.root

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
                return FakeJob(
                    source_url=source,
                    video_quality=str(payload.get("videoQuality") or "best"),
                )

            @staticmethod
            def is_wechat_channels_url(source_url: str) -> bool:
                return "channels.weixin.qq.com" in source_url or "weixin.qq.com/sph/" in source_url

        self.engine = FakeEngine
        pause_resume.install_pause_resume_policy(self.engine)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_pause_persists_progress_and_resume_reuses_same_job_id(self) -> None:
        window = self.engine.EngineWindow(FakeJob("https://media.example.com/video/123", "1080"))
        window.start_job()
        active_id = window.bridge_status()["activeJobId"]
        self.assertTrue(active_id)
        self.assertTrue(window.running)

        window.percent_var.set(47.25)
        window.size_var.set("472 MB / 1.0 GB")
        window._update_bridge(progress=47.25, downloaded="472 MB / 1.0 GB")

        self.assertTrue(window.pause_active_job())
        self.assertTrue(window.queue_paused)
        self.assertTrue(window.cancel_event.is_set())
        self.assertEqual(window.bridge_status()["state"], "pausing")

        window._run_job()
        self.assertFalse(window.running)
        paused = window.get_resume_jobs()
        self.assertEqual(len(paused), 1)
        self.assertEqual(paused[0]["id"], active_id)
        self.assertEqual(paused[0]["state"], "paused")
        self.assertEqual(paused[0]["progress"], 47.25)
        self.assertEqual(paused[0]["downloaded"], "472 MB / 1.0 GB")
        self.assertEqual(paused[0]["resumeMode"], "continue")
        self.assertFalse(window.pause_event.is_set())

        self.assertTrue(window.resume_job(active_id))
        self.assertTrue(window.running)
        self.assertTrue(window.deiconified)
        self.assertEqual(window.bridge_status()["activeJobId"], active_id)
        self.assertFalse(window.queue_paused, "queue pause state must return to its pre-pause value")
        running_record = window._resume_store.get(active_id)
        self.assertIsNotNone(running_record)
        self.assertEqual(running_record["state"], "running")

        window.cancel()
        self.assertTrue(window.cancel_event.is_set())
        window._run_job()
        self.assertFalse(window.running)
        self.assertEqual(window.status_var.get(), "Cancelled")
        self.assertEqual(window.get_resume_jobs(), [], "explicit cancel must remove recovery state")

    def test_pause_preserves_preexisting_queue_pause_state(self) -> None:
        window = self.engine.EngineWindow(FakeJob("https://media.example.com/video/456"))
        window.queue_paused = True
        window.start_job()
        active_id = window.bridge_status()["activeJobId"]
        self.assertTrue(window.pause_active_job())
        window._run_job()
        self.assertTrue(window.resume_job(active_id))
        self.assertTrue(window.queue_paused)

    def test_wechat_recovery_is_explicit_restart_not_fake_checkpoint_resume(self) -> None:
        window = self.engine.EngineWindow(
            FakeJob("https://channels.weixin.qq.com/finder-preview/pages/sph?id=abc123")
        )
        window.start_job()
        window.percent_var.set(63.0)
        self.assertTrue(window.pause_active_job())
        window._run_job()
        records = window.get_resume_jobs()
        self.assertEqual(records[0]["resumeMode"], "restart")
        self.assertEqual(records[0]["progress"], 63.0)

    def test_stale_running_record_becomes_interrupted_without_auto_restart(self) -> None:
        store = pause_resume.ResumeStateStore(self.engine)
        record = store.upsert(
            {
                "id": "abc123",
                "state": "running",
                "payload": {
                    "sourceUrl": "https://media.example.com/video/stale",
                    "videoQuality": "720",
                },
                "progress": 31.0,
                "downloaded": "310 MB",
                "resumeMode": "continue",
            }
        )
        self.assertIsNotNone(record)

        window = self.engine.EngineWindow(None)
        self.assertFalse(window.running, "restart recovery must never auto-start a download")
        records = window.get_resume_jobs()
        self.assertEqual(records[0]["state"], "interrupted")
        self.assertEqual(records[0]["progress"], 31.0)
        self.assertEqual(window.status_var.get(), "Paused")


if __name__ == "__main__":
    unittest.main(verbosity=2)
