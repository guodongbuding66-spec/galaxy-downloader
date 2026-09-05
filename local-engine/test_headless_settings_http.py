from __future__ import annotations

import http.client
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from headless_settings_http import HeadlessSettingsHttpMixin, build_runtime_settings  # noqa: E402


class _Runtime:
    def status(self) -> dict:
        return {"protocol": 2, "capacity": 12, "active": 1, "queued": 2, "paused": 0, "jobs": []}


class _FallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    @property
    def runtime(self):
        return self.server.runtime  # type: ignore[attr-defined]

    @property
    def auth_token(self) -> str:
        return self.server.auth_token  # type: ignore[attr-defined]

    @property
    def bound_host(self) -> str:
        return self.server.bound_host  # type: ignore[attr-defined]

    def _authorized(self) -> bool:
        if not self.auth_token:
            return True
        return self.headers.get("Authorization") == f"Bearer {self.auth_token}"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _Handler(HeadlessSettingsHttpMixin, _FallbackHandler):
    pass


class HeadlessSettingsContractTest(unittest.TestCase):
    def test_builder_exposes_only_safe_runtime_configuration(self) -> None:
        settings = build_runtime_settings(
            bound_host="0.0.0.0",
            auth_token_configured=True,
            queue_capacity=64,
            features={"downloads": True, "plugins": True, "ai": False},
        )
        self.assertEqual(settings["bindingMode"], "remote")
        self.assertTrue(settings["remoteAccess"])
        self.assertEqual(settings["authentication"], {"mode": "bearer", "configured": True})
        self.assertEqual(settings["queue"]["capacity"], 64)
        self.assertFalse(settings["configuration"]["writable"])
        self.assertEqual(settings["configuration"]["mode"], "environment-or-cli")
        self.assertEqual(settings["features"], {"ai": False, "downloads": True, "plugins": True})
        environment = settings["configuration"]["environment"]
        self.assertEqual({item["name"] for item in environment}, {
            "GALAXY_HEADLESS_HOST",
            "GALAXY_HEADLESS_PORT",
            "GALAXY_DOWNLOAD_DIR",
            "GALAXY_HEADLESS_TOKEN",
        })
        self.assertTrue(all("value" not in item for item in environment))

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.server.runtime = _Runtime()
        cls.server.auth_token = "settings-test-token-that-must-never-leak"
        cls.server.bound_host = "127.0.0.1"
        cls.server.media_api = object()
        cls.server.transcript_api = object()
        cls.server.subscription_api = object()
        cls.server.reader_api = None
        cls.server.learning_api = None
        cls.server.music_api = None
        cls.server.ai_api = object()
        cls.server.asr_api = object()
        cls.server.whisperx_api = object()
        cls.server.plugin_api = object()
        cls.server.transfer_api = object()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path: str, *, authorized: bool = False):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        headers = {"Authorization": f"Bearer {self.server.auth_token}"} if authorized else {}
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        result = (response.status, body)
        connection.close()
        return result

    def test_settings_route_requires_existing_bearer_authorization(self) -> None:
        status, _ = self.request("/v1/settings")
        self.assertEqual(status, 401)

    def test_settings_route_returns_safe_feature_and_runtime_status(self) -> None:
        status, body = self.request("/v1/settings?view=runtime", authorized=True)
        self.assertEqual(status, 200)
        payload = json.loads(body)
        settings = payload["settings"]
        self.assertEqual(settings["bindingMode"], "loopback")
        self.assertFalse(settings["remoteAccess"])
        self.assertEqual(settings["queue"]["capacity"], 12)
        self.assertTrue(settings["features"]["media"])
        self.assertTrue(settings["features"]["plugins"])
        self.assertFalse(settings["features"]["reader"])

        rendered = body.decode("utf-8")
        self.assertNotIn(self.server.auth_token, rendered)
        self.assertNotIn(self.server.bound_host, rendered)
        self.assertNotIn("download_root", rendered)
        self.assertNotIn("/downloads", rendered)
        self.assertNotIn("API_KEY=", rendered)

    def test_other_routes_delegate_to_existing_handler_chain(self) -> None:
        status, _ = self.request("/v1/not-settings", authorized=True)
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
