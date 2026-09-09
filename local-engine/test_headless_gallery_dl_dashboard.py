from __future__ import annotations

import http.client
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from headless_web_dashboard import HeadlessWebDashboardMixin


class _FallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _valid_host_header(self) -> bool:
        return bool(self.headers.get("Host"))

    def _browser_origin_allowed(self) -> bool:
        return not str(self.headers.get("Origin") or "").strip()

    def _json(self, status: int, payload: dict) -> None:
        body = str(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _Handler(HeadlessWebDashboardMixin, _FallbackHandler):
    pass


class HeadlessGalleryDlDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = int(cls.server.server_address[1])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path: str) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        result = (response.status, dict(response.getheaders()), body)
        connection.close()
        return result

    def test_gallery_assets_are_strictly_served_and_injected(self) -> None:
        status, headers, html = self.request("/dashboard/")
        self.assertEqual(status, 200)
        self.assertIn(b'/dashboard/gallery-dl.css', html)
        self.assertIn(b'/dashboard/gallery-dl.js', html)
        self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))

        status, headers, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", headers.get("Content-Type", ""))
        self.assertTrue(script)

        status, headers, stylesheet = self.request("/dashboard/gallery-dl.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("Content-Type", ""))
        self.assertTrue(stylesheet)

        status, _, _ = self.request("/dashboard/gallery-dl/secret")
        self.assertEqual(status, 404)

    def test_gallery_workspace_uses_only_bounded_headless_contracts(self) -> None:
        status, _, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        for route in (
            b"/v1/gallery-dl/status",
            b"/v1/gallery-dl/tool",
            b"/v1/gallery-dl/jobs?limit=100",
            b"/v1/gallery-dl/jobs",
            b"/v1/gallery-dl/tool/${action}",
        ):
            self.assertIn(route, script)
        for action in (
            b"runToolAction('check')",
            b"runToolAction('install')",
            b"runToolAction('update')",
            b"runToolAction('remove')",
        ):
            self.assertIn(action, script)
        self.assertIn(b"removeConfirmation", script)
        self.assertIn(b"sourceUrl", script)
        self.assertIn(b"maxFiles", script)
        self.assertIn(b"sessionStorage", script)
        self.assertIn(b"window.confirm", script)
        self.assertIn(b"setTimeout", script)
        self.assertNotIn(b"setInterval", script)

        for forbidden in (
            b"localPath",
            b"filePath",
            b"cookieFile",
            b"httpHeaders",
            b"outputRoot",
            b"toolUrl",
            b"localStorage",
            b"https://cdn.",
        ):
            self.assertNotIn(forbidden, script)

    def test_gallery_task_refresh_keeps_tool_mutation_state_fresh(self) -> None:
        status, _, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        for marker in (
            b"function hasLiveJobs()",
            b"Boolean(tool.mutationBlocked) || hasLiveJobs()",
            b"const [result, tool] = await Promise.all([",
            b"api('/v1/gallery-dl/jobs?limit=100')",
            b"api('/v1/gallery-dl/tool')",
            b"state.tool = tool",
            b"renderTool()",
        ):
            self.assertIn(marker, script)

    def test_gallery_workspace_has_native_limits_and_responsive_styles(self) -> None:
        status, _, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        for marker in (
            b'type="url"',
            b'type="number"',
            b'min="1"',
            b'max="500"',
            b'role="status"',
            b"active tasks refresh automatically",
        ):
            self.assertIn(marker, script)

        status, _, stylesheet = self.request("/dashboard/gallery-dl.css")
        self.assertEqual(status, 200)
        self.assertIn(b".gallery-grid", stylesheet)
        self.assertIn(b"@media(max-width:900px)", stylesheet)
        self.assertIn(b"@media(max-width:560px)", stylesheet)
        self.assertIn(b"prefers-color-scheme:dark", stylesheet)


if __name__ == "__main__":
    unittest.main()
