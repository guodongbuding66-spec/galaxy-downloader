from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiServer  # noqa: E402
from headless_media_api import (  # noqa: E402
    HeadlessMediaApi,
    HeadlessMediaContext,
    run_headless_media_api_self_test,
)
from headless_service import HeadlessRuntime  # noqa: E402
from media_library import sync_media_library  # noqa: E402


def _request_json(url: str, *, method: str = "GET") -> tuple[int, dict]:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=4) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


class CountingMediaApi(HeadlessMediaApi):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.sync_calls = 0

    def sync(self) -> dict:
        self.sync_calls += 1
        return {"accepted": 0, "summary": self.summary()}


def run() -> None:
    run_headless_media_api_self_test()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        downloads = root / "downloads"
        state = root / "state"
        program = root / "program"
        downloads.mkdir()
        state.mkdir()
        program.mkdir()
        video = downloads / "API Demo.mp4"
        audio = downloads / "Audio Demo.mp3"
        video.write_bytes(b"video")
        audio.write_bytes(b"audio")
        context = HeadlessMediaContext(program, state, downloads)
        history = [
            {
                "state": "completed",
                "filePath": str(video),
                "fileName": video.name,
                "label": "API Demo",
                "durationSeconds": 30,
                "sourceUrl": "https://example.com/video",
                "finishedAt": "2026-09-03T10:00:00Z",
            },
            {
                "state": "completed",
                "filePath": str(audio),
                "fileName": audio.name,
                "label": "Audio Demo",
                "durationSeconds": 20,
                "sourceUrl": "https://example.com/audio",
                "finishedAt": "2026-09-03T09:00:00Z",
            },
        ]
        assert sync_media_library(context, history) == 2

        media_api = CountingMediaApi(downloads, context=context)
        runtime = HeadlessRuntime(downloads, max_queue_size=2)
        server = GalaxyApiServer(("127.0.0.1", 0), runtime, "", "127.0.0.1", media_api)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            base = f"http://127.0.0.1:{port}"

            code, core = _request_json(base + "/v1/status")
            assert code == 200 and core["ok"] is True and core["protocol"] == 2

            code, summary = _request_json(base + "/v1/media/summary")
            assert code == 200 and summary["summary"]["total"] == 2
            assert summary["summary"]["video"] == 1 and summary["summary"]["audio"] == 1

            code, listed = _request_json(base + "/v1/media?type=video&limit=1")
            assert code == 200 and len(listed["items"]) == 1
            assert listed["items"][0]["mediaType"] == "video"
            assert "filePath" not in listed["items"][0]

            code, searched = _request_json(base + "/v1/media?q=Audio")
            assert code == 200 and len(searched["items"]) == 1
            assert searched["items"][0]["title"] == "Audio Demo"

            try:
                _request_json(base + "/v1/media?type=document")
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
            else:
                raise AssertionError("invalid media type did not return 400")

            code, synced = _request_json(base + "/v1/media/sync", method="POST")
            assert code == 200 and synced["ok"] is True and media_api.sync_calls == 1
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()


if __name__ == "__main__":
    run()
    print("Headless media API self-test passed")
