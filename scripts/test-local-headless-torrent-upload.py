from __future__ import annotations

import io
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiRequestHandler  # noqa: E402
from headless_service import HeadlessRuntime  # noqa: E402
from headless_torrent_upload import (  # noqa: E402
    MAX_TORRENT_UPLOAD_BYTES,
    run_headless_torrent_upload_self_test,
)
from headless_transfer_http import HeadlessTransferHttpMixin, _read_torrent_upload  # noqa: E402


class FakeTransferApi:
    context = None


if HeadlessTransferHttpMixin in GalaxyApiRequestHandler.__mro__:
    CombinedHandler = GalaxyApiRequestHandler
else:
    class CombinedHandler(HeadlessTransferHttpMixin, GalaxyApiRequestHandler):
        pass


class TestServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, runtime: HeadlessRuntime, auth_token: str):
        self.runtime = runtime
        self.auth_token = auth_token
        self.bound_host = "127.0.0.1"
        self.transfer_api = FakeTransferApi()
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
    *,
    token: str = "",
    body: bytes = b"d4:infode",
    content_type: str = "application/x-bittorrent",
    content_encoding: str = "",
    query: str = "",
) -> tuple[int, dict]:
    headers = {
        "Host": f"127.0.0.1:{port}",
        "Content-Type": content_type,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if content_encoding:
        headers["Content-Encoding"] = content_encoding
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/transfers/torrent{query}",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _test_reader_bounds() -> None:
    class FakeHeaders(dict):
        def get(self, key, default=None):  # noqa: ANN001
            return super().get(key, default)

    class Handler:
        pass

    handler = Handler()
    handler.headers = FakeHeaders(
        {
            "Content-Type": "application/x-bittorrent",
            "Content-Length": str(MAX_TORRENT_UPLOAD_BYTES + 1),
        }
    )
    handler.rfile = io.BytesIO(b"")
    try:
        _read_torrent_upload(handler)
    except Exception as exc:
        assert "10 MB" in str(exc)
    else:
        raise AssertionError("oversized torrent upload was accepted")

    handler.headers = FakeHeaders(
        {
            "Content-Type": "text/plain",
            "Content-Length": "3",
        }
    )
    handler.rfile = io.BytesIO(b"abc")
    try:
        _read_torrent_upload(handler)
    except Exception as exc:
        assert "Content-Type" in str(exc)
    else:
        raise AssertionError("wrong torrent content type was accepted")

    handler.headers = FakeHeaders(
        {
            "Content-Type": "application/x-bittorrent",
            "Content-Length": "5",
            "Content-Encoding": "gzip",
        }
    )
    handler.rfile = io.BytesIO(b"abcde")
    try:
        _read_torrent_upload(handler)
    except Exception as exc:
        assert "compressed" in str(exc)
    else:
        raise AssertionError("compressed torrent upload was accepted")


def run_test() -> None:
    import tempfile

    run_headless_torrent_upload_self_test()
    _test_reader_bounds()

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        runtime = HeadlessRuntime(root / "downloads")
        token = "torrent-upload-test-token-123456789"
        server = TestServer(("127.0.0.1", 0), runtime, token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = int(server.server_address[1])
        try:
            code, body = _request(port)
            assert code == 401 and body["error"] == "unauthorized"

            code, body = _request(port, query=f"?token={token}")
            assert code == 401 and body["error"] == "unauthorized"

            code, body = _request(port, token=token, content_type="text/plain")
            assert code == 400 and body["code"] == "TRANSFER_INVALID_REQUEST"

            observed: dict[str, object] = {}

            def fake_upload(api, raw):  # noqa: ANN001
                observed["api"] = api
                observed["raw"] = raw
                return {
                    "completed": True,
                    "collection": "torrents",
                    "message": "done",
                    "sourceType": "torrent-file",
                }

            with patch("headless_transfer_http.download_uploaded_torrent", fake_upload):
                code, body = _request(port, token=token, body=b"d4:infode")
            assert code == 200 and body["ok"] is True
            assert body["collection"] == "torrents"
            assert body["sourceType"] == "torrent-file"
            assert observed["raw"] == b"d4:infode"
            assert observed["api"] is server.transfer_api
            assert "path" not in json.dumps(body).lower()

            secret = str(root / "state" / "private.torrent")
            with patch(
                "headless_transfer_http.download_uploaded_torrent",
                side_effect=RuntimeError(f"internal failure at {secret}"),
            ):
                code, body = _request(port, token=token)
            assert code == 502
            serialized = json.dumps(body)
            assert body["error"] == "transfer request failed"
            assert secret not in serialized and str(root) not in serialized
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()


if __name__ == "__main__":
    run_test()
    print("Headless torrent upload tests passed")
