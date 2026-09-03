from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] if '__file__' in globals() else Path.cwd()
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_service import (  # noqa: E402
    GalaxyHeadlessServer,
    HeadlessConflict,
    HeadlessRuntime,
)


_BLOCK_STARTED = threading.Event()
_BLOCK_RELEASE = threading.Event()
_PAUSE_READY = threading.Event()
_PAUSE_CONTINUE = threading.Event()
_EXECUTIONS: dict[str, int] = {}
_CURRENT_ROOT = Path.cwd()


class FakeYoutubeDL:
    def __init__(self, options: dict) -> None:
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def extract_info(self, url: str, download: bool = True):
        assert download is True
        _EXECUTIONS[url] = _EXECUTIONS.get(url, 0) + 1
        hook = self.options["progress_hooks"][0]
        filename = str(_CURRENT_ROOT / "fixture.mp4")
        if url.endswith("/block"):
            _BLOCK_STARTED.set()
            assert _BLOCK_RELEASE.wait(5), "blocker timed out"
            hook({"status": "finished", "downloaded_bytes": 1, "total_bytes": 1, "filename": filename})
        elif url.endswith("/pause"):
            hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 10, "filename": filename})
            _PAUSE_READY.set()
            assert _PAUSE_CONTINUE.wait(5), "pause fixture timed out"
            hook({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10, "filename": filename})
            hook({"status": "finished", "downloaded_bytes": 10, "total_bytes": 10, "filename": filename})
        elif url.endswith("/retry") and _EXECUTIONS[url] == 1:
            raise RuntimeError("provider failed token=super-secret")
        elif url.endswith("/api-retry") and _EXECUTIONS[url] == 1:
            raise RuntimeError("temporary provider failure")
        else:
            hook({"status": "finished", "downloaded_bytes": 1, "total_bytes": 1, "filename": filename})
        return {"id": "fixture", "title": "Fixture", "ext": "mp4"}

    def prepare_filename(self, _info: dict) -> str:
        return str(_CURRENT_ROOT / "fixture.mp4")


def _wait_state(runtime: HeadlessRuntime, job_id: str, states: set[str], timeout: float = 6.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = runtime.get(job_id)
        if job is not None and job.state in states:
            return job.state
        time.sleep(0.02)
    job = runtime.get(job_id)
    raise AssertionError(f"job did not reach {sorted(states)}; state={getattr(job, 'state', None)}")


def _post_json(url: str) -> tuple[int, dict]:
    request = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(request, timeout=4) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def run() -> None:
    global _CURRENT_ROOT
    with tempfile.TemporaryDirectory() as temp_dir:
        _CURRENT_ROOT = Path(temp_dir)
        with patch("headless_service.validated_public_http_url", side_effect=str), patch(
            "headless_service.YoutubeDL", FakeYoutubeDL
        ):
            runtime = HeadlessRuntime(_CURRENT_ROOT, max_queue_size=4)
            try:
                blocker = runtime.submit({"sourceUrl": "https://example.com/block"})
                assert _BLOCK_STARTED.wait(4), "blocker never started"

                queued = runtime.submit({"sourceUrl": "https://example.com/queued"})
                assert runtime.pause(queued.job_id).state == "paused"
                assert runtime.resume(queued.job_id).state == "queued"
                _BLOCK_RELEASE.set()
                assert _wait_state(runtime, blocker.job_id, {"completed"}) == "completed"
                assert _wait_state(runtime, queued.job_id, {"completed"}) == "completed"
                assert _EXECUTIONS["https://example.com/queued"] == 1, "stale queue token executed twice"

                pausable = runtime.submit({"sourceUrl": "https://example.com/pause"})
                assert _PAUSE_READY.wait(4), "pause fixture never reached first progress hook"
                assert runtime.pause(pausable.job_id).state in {"pausing", "paused"}
                _PAUSE_CONTINUE.set()
                assert _wait_state(runtime, pausable.job_id, {"paused"}) == "paused"
                assert runtime.resume(pausable.job_id).state == "running"
                assert _wait_state(runtime, pausable.job_id, {"completed"}) == "completed"

                retryable = runtime.submit({"sourceUrl": "https://example.com/retry"})
                assert _wait_state(runtime, retryable.job_id, {"failed"}) == "failed"
                failed = runtime.get(retryable.job_id)
                assert failed is not None and "super-secret" not in failed.detail and "[REDACTED]" in failed.detail
                retried = runtime.retry(retryable.job_id)
                assert retried.attempt == 2 and retried.state == "queued"
                assert _wait_state(runtime, retryable.job_id, {"completed"}) == "completed"
                assert _EXECUTIONS["https://example.com/retry"] == 2

                try:
                    runtime.retry(retryable.job_id)
                except HeadlessConflict:
                    pass
                else:
                    raise AssertionError("completed job retry must conflict")

                status = runtime.status()
                assert status["capacity"] == 4 and "paused" in status

                api_retry = runtime.submit({"sourceUrl": "https://example.com/api-retry"})
                assert _wait_state(runtime, api_retry.job_id, {"failed"}) == "failed"
                server = GalaxyHeadlessServer(("127.0.0.1", 0), runtime, "", "127.0.0.1")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    port = server.server_address[1]
                    code, payload = _post_json(f"http://127.0.0.1:{port}/v1/jobs/{api_retry.job_id}/retry")
                    assert code == 202 and payload["ok"] is True and payload["job"]["attempt"] == 2
                    assert _wait_state(runtime, api_retry.job_id, {"completed"}) == "completed"
                    try:
                        _post_json(f"http://127.0.0.1:{port}/v1/jobs/{api_retry.job_id}/pause")
                    except urllib.error.HTTPError as exc:
                        assert exc.code == 409
                    else:
                        raise AssertionError("pause completed HTTP action must return 409")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=3)
            finally:
                runtime.stop()


if __name__ == "__main__":
    run()
    print("Headless job controls self-test passed")
