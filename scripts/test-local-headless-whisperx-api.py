from __future__ import annotations

import json
import sys
import tempfile
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiServer
from headless_service import HeadlessRuntime
from headless_whisperx_api import HeadlessWhisperXApi

TOKEN = "headless-whisperx-contract-token-123"


def request(base: str, path: str, payload=None, token: str = TOKEN):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(base + path, data=data, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


class FakeWhisperX:
    def status(self):
        return {"whisperx": {"id": "whisperx", "runtimeAvailable": True, "tokenConfigured": False, "localFilesOnly": True}}

    def prepare(self, payload):
        return {"operation": {"success": True, "detail": "ready"}, **self.status()}

    def remove(self):
        return {"operation": {"success": True, "detail": "deleted"}, **self.status()}

    def diarize(self, payload):
        return {"diarization": {"mediaId": payload["mediaId"], "provider": "whisperx", "speakerCount": 2, "turnCount": 2}}


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime = HeadlessRuntime(root)
        server = GalaxyApiServer(("127.0.0.1", 0), runtime, TOKEN, "127.0.0.1", None, whisperx_api=FakeWhisperX())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            status, body = request(base, "/v1/asr/whisperx", token="bad")
            assert status == 401 and body["ok"] is False
            status, body = request(base, "/v1/asr/whisperx")
            assert status == 200 and body["whisperx"]["id"] == "whisperx"
            status, body = request(base, "/v1/asr/whisperx/prepare", {})
            assert status == 200 and body["operation"]["success"] is True
            status, body = request(base, "/v1/asr/whisperx/diarize", {"mediaId": "a" * 32})
            assert status == 200 and body["diarization"]["speakerCount"] == 2
            assert "path" not in json.dumps(body).lower()
            status, body = request(base, "/v1/status")
            assert status == 200 and body["ok"] is True
        finally:
            server.shutdown()
            server.server_close()
            runtime.stop()
            thread.join(timeout=2)

        api = HeadlessWhisperXApi(root)
        with patch("headless_whisperx_api.provider_status") as status_fn:
            status_fn.return_value.public_payload.return_value = {"id": "whisperx", "tokenConfigured": False}
            assert api.status()["whisperx"]["tokenConfigured"] is False


if __name__ == "__main__":
    main()
    print("Headless WhisperX contract passed")
