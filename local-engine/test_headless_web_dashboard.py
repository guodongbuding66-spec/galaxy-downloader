from __future__ import annotations

import http.client
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from headless_web_dashboard import HeadlessWebDashboardMixin  # noqa: E402


class _FallbackHandler(BaseHTTPRequestHandler):
    auth_token = "test-token"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _valid_host_header(self) -> bool:
        return bool(self.headers.get("Host"))

    def _browser_origin_allowed(self) -> bool:
        return not str(self.headers.get("Origin") or "").strip()

    def _authorized(self) -> bool:
        if not self._browser_origin_allowed():
            return False
        return self.headers.get("Authorization") == f"Bearer {self.auth_token}"

    def _json(self, status: int, payload: dict) -> None:
        body = str(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        status = 200 if self._authorized() else 401
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _Handler(HeadlessWebDashboardMixin, _FallbackHandler):
    pass


class HeadlessWebDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, method: str, path: str, *, headers: dict | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        result = (response.status, dict(response.getheaders()), body)
        connection.close()
        return result

    def test_root_redirects_to_dashboard(self) -> None:
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/dashboard/")
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_dashboard_serves_strict_static_assets(self) -> None:
        status, headers, body = self.request("GET", "/dashboard/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertIn(b"Galaxy Dashboard", body)

        for asset, content_type in (
            ("/dashboard/app.js", "text/javascript"),
            ("/dashboard/styles.css", "text/css"),
            ("/dashboard/ai-subscriptions.js", "text/javascript"),
            ("/dashboard/ai-subscriptions.css", "text/css"),
        ):
            status, asset_headers, asset_body = self.request("GET", asset)
            self.assertEqual(status, 200)
            self.assertIn(content_type, asset_headers.get("Content-Type", ""))
            self.assertTrue(asset_body)

        status, _, _ = self.request("GET", "/dashboard/not-a-file")
        self.assertEqual(status, 404)

    def test_dashboard_exposes_library_and_transcript_workflows(self) -> None:
        status, _, html = self.request("GET", "/dashboard/")
        self.assertEqual(status, 200)
        self.assertIn(b'data-view="library"', html)
        self.assertIn(b'data-view="transcript"', html)
        self.assertIn(b'id="librarySyncButton"', html)
        self.assertIn(b'id="transcriptIndexButton"', html)
        self.assertIn(b'id="speakerRelabelForm"', html)

        status, _, script = self.request("GET", "/dashboard/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b"/v1/media/summary", script)
        self.assertIn(b"/v1/media/sync", script)
        self.assertIn(b"/v1/transcripts/search", script)
        self.assertIn(b"/speakers/relabel", script)
        self.assertIn(b"/export", script)
        self.assertNotIn(b"https://cdn.", script)

    def test_dashboard_exposes_ai_and_subscription_workflows(self) -> None:
        status, _, html = self.request("GET", "/dashboard/")
        self.assertEqual(status, 200)
        self.assertIn(b'data-ops-view="ai"', html)
        self.assertIn(b'data-ops-view="subscriptions"', html)
        self.assertIn(b'id="aiProviderForm"', html)
        self.assertIn(b'id="aiTaskForm"', html)
        self.assertIn(b'id="subsRulesForm"', html)
        self.assertIn(b'id="subsReconcileButton"', html)

        status, _, script = self.request("GET", "/dashboard/ai-subscriptions.js")
        self.assertEqual(status, 200)
        for route in (
            b"/v1/ai/providers",
            b"/v1/ai/prompts",
            b"/v1/ai/queue",
            b"/v1/ai/history",
            b"/v1/subscriptions",
            b"/items/transition",
            b"/reconcile",
        ):
            self.assertIn(route, script)
        self.assertIn(b"env:OPENAI_API_KEY", html)
        self.assertNotIn(b"apiKey", script)
        self.assertNotIn(b"https://cdn.", script)

    def test_same_origin_browser_request_still_requires_bearer_token(self) -> None:
        origin = f"http://127.0.0.1:{self.port}"
        status, _, _ = self.request("POST", "/v1/test", headers={"Origin": origin})
        self.assertEqual(status, 401)
        status, _, _ = self.request("POST", "/v1/test", headers={"Origin": origin, "Authorization": "Bearer test-token"})
        self.assertEqual(status, 200)

    def test_cross_origin_request_is_rejected_even_with_token(self) -> None:
        status, _, _ = self.request("POST", "/v1/test", headers={"Origin": "http://evil.example", "Authorization": "Bearer test-token"})
        self.assertEqual(status, 401)

    def test_malformed_origin_is_rejected_without_handler_error(self) -> None:
        status, _, _ = self.request("POST", "/v1/test", headers={"Origin": "http://[broken", "Authorization": "Bearer test-token"})
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
