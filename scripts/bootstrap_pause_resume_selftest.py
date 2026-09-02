from __future__ import annotations

from pathlib import Path

path = Path("local-engine/pause_resume_policy.py")
text = path.read_text(encoding="utf-8")
marker = "\ndef run_pause_resume_self_test() -> None:\n"
if text.count(marker) != 1:
    raise SystemExit(f"expected one pause resume self-test marker, got {text.count(marker)}")
prefix = text.split(marker, 1)[0]

self_test = r'''
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
'''

path.write_text(prefix + self_test + "\n", encoding="utf-8")
