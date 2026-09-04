from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiRequestHandler
from headless_service import HeadlessRuntime
from headless_transfer_api import HeadlessTransferApiError
from headless_transfer_http import HeadlessTransferHttpMixin


class FakeTransferApi:
    def status(self):
        return {"torrentReady": True, "p2pLan": True, "activeSenders": 1}

    def senders(self):
        return {"senders": [{"sessionId": "a" * 32, "active": True}]}

    def sender_detail(self, session_id):
        if session_id != "a" * 32:
            raise HeadlessTransferApiError("invalid sender session id", code="TRANSFER_SESSION_ID_INVALID")
        return {"sender": {"sessionId": session_id, "active": True}}

    def start_sender(self, payload):
        return {
            "sender": {
                "sessionId": "a" * 32,
                "mediaId": payload.get("mediaId"),
                "code": "ABCDEFGH2345",
                "active": True,
            }
        }

    def stop_sender(self, session_id):
        return {"sender": {"sessionId": session_id, "active": False}, "stopped": True}

    def receive(self, payload):
        return {
            "received": True,
            "fileName": "received.mp4",
            "sizeBytes": 4,
            "sha256": "b" * 64,
            "collection": "received",
        }

    def download_magnet(self, payload):
        if not str(payload.get("magnet") or "").startswith("magnet:?"):
            raise HeadlessTransferApiError("invalid magnet link", code="TRANSFER_MAGNET_INVALID")
        return {"completed": True, "collection": "torrents", "message": "done"}


if HeadlessTransferHttpMixin in GalaxyApiRequestHandler.__mro__:
    CombinedHandler = GalaxyApiRequestHandler
else:
    class CombinedHandler(HeadlessTransferHttpMixin, GalaxyApiRequestHandler):
        pass


class TestServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, runtime: HeadlessRuntime, auth_token: str, transfer_api):
        self.runtime = runtime
        self.auth_token = auth_token
        self.bound_host = "127.0.0.1"
        self.transfer_api = transfer_api
        self.plugin_api = None
        self.ai_api = None
        self.asr_api = None
        self.media_api = None
        self.transcript_api = None
        self.subscription_api = None
        self.reader_api = None
        self.learning_api = None
        self.music_api = None
        super().__init__(address, CombinedHandler)


def _request(
    port: int,
    path: str,
    *,
    token: str = "",
    method: str = "GET",
    payload=None,
    raw: bytes | None = None,
):
    headers = {"Host": f"127.0.0.1:{port}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = raw
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def run_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        runtime = HeadlessRuntime(Path(directory))
        token = "transfer-http-test-token-123456789"
        server = TestServer(("127.0.0.1", 0), runtime, token, FakeTransferApi())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = int(server.server_address[1])
        try:
            code, body = _request(port, "/v1/transfers/status")
            assert code == 401 and body["ok"] is False

            code, body = _request(port, "/v1/status", token=token)
            assert code == 200 and body["ok"] is True

            code, body = _request(port, "/v1/transfers/status", token=token)
            assert code == 200 and body["torrentReady"] is True

            code, body = _request(port, "/v1/transfers/senders", token=token)
            assert code == 200 and body["senders"][0]["sessionId"] == "a" * 32

            code, body = _request(port, f"/v1/transfers/senders/{'a' * 32}", token=token)
            assert code == 200 and body["sender"]["active"] is True

            code, body = _request(
                port,
                "/v1/transfers/senders",
                token=token,
                method="POST",
                payload={"mediaId": "b" * 32},
            )
            assert code == 201 and body["sender"]["code"] == "ABCDEFGH2345"

            code, body = _request(
                port,
                f"/v1/transfers/senders/{'a' * 32}/stop",
                token=token,
                method="POST",
            )
            assert code == 200 and body["stopped"] is True

            code, body = _request(
                port,
                "/v1/transfers/receive",
                token=token,
                method="POST",
                payload={"code": "ABCDEFGH2345"},
            )
            assert code == 200 and body["collection"] == "received"
            assert "path" not in json.dumps(body).lower()

            code, body = _request(
                port,
                "/v1/transfers/magnet",
                token=token,
                method="POST",
                payload={"magnet": "magnet:?xt=urn:btih:" + "0" * 40},
            )
            assert code == 200 and body["collection"] == "torrents"

            code, body = _request(
                port,
                "/v1/transfers/magnet",
                token=token,
                method="POST",
                raw=b"{bad-json",
            )
            assert code == 400 and body["code"] == "TRANSFER_INVALID_REQUEST"

            server.transfer_api = None
            code, body = _request(port, "/v1/transfers/status", token=token)
            assert code == 503 and body["code"] == "TRANSFER_UNAVAILABLE"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()


if __name__ == "__main__":
    run_test()
    print("Headless transfer HTTP self-test passed")
