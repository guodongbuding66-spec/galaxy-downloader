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
from headless_plugin_api import HeadlessPluginApiError
from headless_plugin_http import HeadlessPluginHttpMixin
from headless_service import HeadlessRuntime


class FakePluginApi:
    def status(self):
        return {"protocol": 2, "plugins": [{"id": "demo.plugin", "enabled": True}], "updatesAvailable": 1}

    def marketplace(self):
        return {"cached": True, "entries": [{"id": "demo.plugin", "version": "1.1.0"}]}

    def plugin_detail(self, plugin_id):
        if plugin_id != "demo.plugin":
            raise HeadlessPluginApiError("invalid plugin id", code="PLUGIN_ID_INVALID")
        return {"plugin": {"id": plugin_id, "enabled": True}}

    def refresh_marketplace(self):
        return {"refreshed": True, "count": 1, "entries": [{"id": "demo.plugin"}]}

    def set_enabled(self, plugin_id, enabled):
        return {"plugin": {"id": plugin_id, "enabled": bool(enabled)}}

    def install(self, plugin_id):
        return {"plugin": {"id": plugin_id, "version": "1.1.0"}}

    def update(self, plugin_id):
        return {"plugin": {"id": plugin_id, "version": "1.1.0"}, "updated": True}

    def remove(self, plugin_id):
        return {"pluginId": plugin_id, "removed": True}


if HeadlessPluginHttpMixin in GalaxyApiRequestHandler.__mro__:
    CombinedHandler = GalaxyApiRequestHandler
else:
    class CombinedHandler(HeadlessPluginHttpMixin, GalaxyApiRequestHandler):
        pass


class TestServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, runtime: HeadlessRuntime, auth_token: str, plugin_api):
        self.runtime = runtime
        self.auth_token = auth_token
        self.bound_host = "127.0.0.1"
        self.plugin_api = plugin_api
        self.ai_api = None
        self.asr_api = None
        self.media_api = None
        self.transcript_api = None
        self.subscription_api = None
        self.reader_api = None
        self.learning_api = None
        self.music_api = None
        super().__init__(address, CombinedHandler)


def _request(port: int, path: str, *, token: str = "", method: str = "GET", payload=None):
    headers = {"Host": f"127.0.0.1:{port}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
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
        token = "plugin-http-test-token-1234567890"
        server = TestServer(("127.0.0.1", 0), runtime, token, FakePluginApi())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = int(server.server_address[1])
        try:
            code, body = _request(port, "/v1/plugins/status")
            assert code == 401 and body["ok"] is False

            code, body = _request(port, "/v1/status", token=token)
            assert code == 200 and body["ok"] is True

            code, body = _request(port, "/v1/plugins/status", token=token)
            assert code == 200 and body["plugins"][0]["id"] == "demo.plugin"

            code, body = _request(port, "/v1/plugins/marketplace", token=token)
            assert code == 200 and body["cached"] is True

            code, body = _request(port, "/v1/plugins/demo.plugin", token=token)
            assert code == 200 and body["plugin"]["id"] == "demo.plugin"

            code, body = _request(port, "/v1/plugins/marketplace/refresh", token=token, method="POST")
            assert code == 200 and body["refreshed"] is True

            for action in ("enable", "disable", "install", "update", "remove"):
                code, body = _request(
                    port,
                    f"/v1/plugins/demo.plugin/{action}",
                    token=token,
                    method="POST",
                )
                assert code == 200 and body["ok"] is True

            code, body = _request(port, "/v1/plugins/bad%20id", token=token)
            assert code in {400, 404}

            server.plugin_api = None
            code, body = _request(port, "/v1/plugins/status", token=token)
            assert code == 503 and body["code"] == "PLUGIN_UNAVAILABLE"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()


if __name__ == "__main__":
    run_test()
    print("Headless plugin HTTP self-test passed")
