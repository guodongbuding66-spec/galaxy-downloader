from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiServer
from headless_service import HeadlessRuntime
from headless_transfer_api import HeadlessTransferApi


class FakeAiApi:
    def providers(self):
        return {"providers": [{"id": "fake-ai"}]}

    def shutdown(self):
        raise AssertionError("caller-owned AI API must not be shut down")


class FakeAsrApi:
    def providers(self):
        return {"providers": [{"id": "fake-asr"}]}


class FakePluginApi:
    def status(self):
        return {"protocol": 2, "plugins": [{"id": "fake.plugin"}], "updatesAvailable": 0}


class FakeTransferApi:
    def status(self):
        return {"torrentReady": True, "p2pLan": True, "activeSenders": 0}

    def shutdown(self):
        raise AssertionError("caller-owned Transfer API must not be shut down")


def _get(port: int, path: str, token: str = ""):
    headers = {"Host": f"127.0.0.1:{port}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def run_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime = HeadlessRuntime(root)
        token = "transfer-production-test-token-1234567"
        server = GalaxyApiServer(
            ("127.0.0.1", 0), runtime, token, "127.0.0.1", None,
            ai_api=FakeAiApi(), asr_api=FakeAsrApi(), plugin_api=FakePluginApi(), transfer_api=FakeTransferApi(),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = int(server.server_address[1])
        try:
            code, _ = _get(port, "/v1/transfers/status")
            assert code == 401
            for path in ("/v1/status", "/v1/ai/providers", "/v1/asr/providers", "/v1/plugins/status", "/v1/transfers/status"):
                code, body = _get(port, path, token)
                assert code == 200 and body["ok"] is True
            code, body = _get(port, "/v1/transfers/status", token)
            assert body["torrentReady"] is True
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3); runtime.stop()

        runtime = HeadlessRuntime(root / "auto")
        auto_server = GalaxyApiServer(
            ("127.0.0.1", 0), runtime, "", "127.0.0.1", None,
            ai_api=FakeAiApi(), asr_api=FakeAsrApi(), plugin_api=FakePluginApi(),
        )
        try:
            assert isinstance(auto_server.transfer_api, HeadlessTransferApi)
        finally:
            auto_server.server_close(); runtime.stop()


if __name__ == "__main__":
    run_test()
    print("Headless transfer production self-test passed")
