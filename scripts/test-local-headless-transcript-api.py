from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from ai_workspace import transcript_path  # noqa: E402
from headless_api import GalaxyApiServer  # noqa: E402
from headless_media_api import HeadlessMediaApi, HeadlessMediaContext  # noqa: E402
from headless_service import HeadlessRuntime  # noqa: E402
from headless_transcript_api import (  # noqa: E402
    HeadlessTranscriptApi,
    HeadlessTranscriptContext,
    run_headless_transcript_api_self_test,
)
from media_library import search_media_items, sync_media_library  # noqa: E402


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
) -> tuple[int, dict]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, method=method, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=4) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def run() -> None:
    run_headless_transcript_api_self_test()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        program = root / "program"
        for target in (downloads, state, data, program):
            target.mkdir()

        video = downloads / "Transcript API Demo.mp4"
        video.write_bytes(b"video")
        transcript_context = HeadlessTranscriptContext(program, data, state, downloads)
        history = [
            {
                "state": "completed",
                "filePath": str(video),
                "fileName": video.name,
                "label": "Transcript API Demo",
                "durationSeconds": 30,
                "sourceUrl": "https://example.com/video",
                "finishedAt": "2026-09-03T11:00:00Z",
            }
        ]
        assert sync_media_library(transcript_context, history) == 1
        media_id = search_media_items(transcript_context, "Transcript API Demo", limit=1)[0]["id"]
        transcript_path(transcript_context, media_id).write_text(
            "1\n00:00:01,000 --> 00:00:02,000\n[Speaker 1] Hello API\n\n"
            "2\n00:00:03,000 --> 00:00:04,500\n[Speaker 2] Second line\n",
            encoding="utf-8",
        )

        media_context = HeadlessMediaContext(program, state, downloads)
        media_api = HeadlessMediaApi(downloads, context=media_context)
        transcript_api = HeadlessTranscriptApi(downloads, context=transcript_context)
        runtime = HeadlessRuntime(downloads, max_queue_size=2)
        server = GalaxyApiServer(
            ("127.0.0.1", 0),
            runtime,
            "",
            "127.0.0.1",
            media_api,
            transcript_api,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            base = f"http://127.0.0.1:{port}"

            code, indexed = _request_json(base + f"/v1/transcripts/{media_id}/index", method="POST")
            assert code == 200 and indexed["segmentCount"] == 2

            code, listed = _request_json(base + f"/v1/transcripts/{media_id}?limit=10")
            assert code == 200 and len(listed["segments"]) == 2
            assert listed["segments"][0]["speaker"] == "Speaker 1"

            query = urllib.parse.urlencode({"q": "hello", "mediaId": media_id, "limit": 10})
            code, searched = _request_json(base + "/v1/transcripts/search?" + query)
            assert code == 200 and len(searched["results"]) == 1
            assert searched["results"][0]["text"] == "Hello API"

            code, relabeled = _request_json(
                base + f"/v1/transcripts/{media_id}/speakers/relabel",
                method="POST",
                payload={"oldLabel": "Speaker 1", "newLabel": "Host"},
            )
            assert code == 200 and relabeled["updated"] == 1

            code, exported = _request_json(
                base + f"/v1/transcripts/{media_id}/export",
                method="POST",
                payload={"format": "json", "basename": "api-demo", "includeSpeaker": True},
            )
            assert code == 200 and exported["export"]["fileName"].endswith(".json")
            assert exported["export"]["segmentCount"] == 2
            assert "path" not in exported["export"] and "filePath" not in exported["export"]

            try:
                _request_json(base + f"/v1/transcripts/search?mediaId={media_id}&start=nan")
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
            else:
                raise AssertionError("non-finite transcript time filter did not return 400")

            try:
                _request_json(base + "/v1/transcripts/not-a-media-id")
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
            else:
                raise AssertionError("invalid transcript media id did not return 400")

            code, core = _request_json(base + "/v1/status")
            assert code == 200 and core["ok"] is True and core["protocol"] == 2
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()


if __name__ == "__main__":
    run()
    print("Headless transcript API self-test passed")
