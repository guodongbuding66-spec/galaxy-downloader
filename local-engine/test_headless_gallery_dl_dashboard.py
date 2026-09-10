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
        self.assertIn(b"archiveEnabled", script)
        self.assertIn(b"dateAfter", script)
        self.assertIn(b"dateBefore", script)
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
            b"archivePath",
            b"dateConfig",
            b"datePath",
            b"toolUrl",
            b"localStorage",
            b"https://cdn.",
        ):
            self.assertNotIn(forbidden, script)

    def test_gallery_archive_control_is_default_off_and_capability_gated(self) -> None:
        status, _, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        for marker in (
            b'id="galleryArchiveEnabled"',
            b'name="archiveEnabled"',
            b'type="checkbox"',
            b'aria-describedby="galleryArchiveHelp"',
            b'galleryArchiveEnabled" name="archiveEnabled" type="checkbox" aria-describedby="galleryArchiveHelp" disabled',
            b"state.engine?.archiveSupported === true",
            b"if (!archiveSupported) archiveControl.checked = false",
            b"archiveControl.disabled = state.submitPending || !installed || !acceptingJobs || !archiveSupported",
            b"const archiveEnabled = state.engine?.archiveSupported === true && $('galleryArchiveEnabled').checked",
            b"archiveEnabled: Boolean(archiveEnabled)",
        ):
            self.assertIn(marker, script)
        self.assertNotIn(b"galleryArchiveEnabled').checked = true", script)

    def test_gallery_date_controls_are_default_empty_capability_gated_and_bounded(self) -> None:
        status, _, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        for marker in (
            b'id="galleryDateRange" disabled',
            b'id="galleryDateAfter" name="dateAfter" type="date"',
            b'id="galleryDateBefore" name="dateBefore" type="date"',
            b'aria-describedby="galleryDateHelp"',
            b"state.engine?.dateFilterSupported === true",
            b"if (!dateFilterSupported)",
            b"$('galleryDateAfter').value = ''",
            b"$('galleryDateBefore').value = ''",
            b"dateRange.disabled = state.submitPending || !installed || !acceptingJobs || !dateFilterSupported",
            b"const dateAfter = dateFilterSupported ? $('galleryDateAfter').value.trim() : ''",
            b"const dateBefore = dateFilterSupported ? $('galleryDateBefore').value.trim() : ''",
            b"if (dateAfter && dateBefore && dateAfter >= dateBefore)",
            b"Date \xe2\x80\x9cAfter\xe2\x80\x9d must be earlier than Date \xe2\x80\x9cBefore\xe2\x80\x9d.",
            b"$('galleryDateAfter').focus()",
            b"if (dateAfter) payload.dateAfter = dateAfter",
            b"if (dateBefore) payload.dateBefore = dateBefore",
            b"pinned older posts",
        ):
            self.assertIn(marker, script)

        after_markup = script.split(b'id="galleryDateAfter"', 1)[1].split(b"></label>", 1)[0]
        before_markup = script.split(b'id="galleryDateBefore"', 1)[1].split(b"></label>", 1)[0]
        self.assertNotIn(b"value=", after_markup)
        self.assertNotIn(b"value=", before_markup)

        submit = script.split(b"async function submitGallery(event)", 1)[1].split(
            b"async function runJobAction", 1
        )[0]
        payload_start = submit.index(b"const payload = {")
        after_assignment = submit.index(b"if (dateAfter) payload.dateAfter = dateAfter")
        before_assignment = submit.index(b"if (dateBefore) payload.dateBefore = dateBefore")
        post_call = submit.index(b"postJson('/v1/gallery-dl/jobs', payload)")
        self.assertLess(payload_start, after_assignment)
        self.assertLess(after_assignment, post_call)
        self.assertLess(before_assignment, post_call)

    def test_gallery_task_refresh_keeps_tool_mutation_state_fresh(self) -> None:
        status, _, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        for marker in (
            b"function hasLiveJobs()",
            b"Boolean(tool.mutationBlocked) || hasLiveJobs()",
            b"api('/v1/gallery-dl/jobs?limit=100')",
            b"state.jobs = Array.isArray(result.jobs) ? result.jobs : []",
            b"state.tool = await api('/v1/gallery-dl/tool')",
            b"renderTool()",
        ):
            self.assertIn(marker, script)

        load_jobs = script.split(b"async function loadJobs()", 1)[1].split(b"async function loadGallery()", 1)[0]
        jobs_fetch = load_jobs.index(b"api('/v1/gallery-dl/jobs?limit=100')")
        jobs_state = load_jobs.index(b"state.jobs = Array.isArray(result.jobs) ? result.jobs : []")
        tool_fetch = load_jobs.index(b"state.tool = await api('/v1/gallery-dl/tool')")
        self.assertLess(jobs_fetch, jobs_state)
        self.assertLess(jobs_state, tool_fetch)

    def test_gallery_workspace_has_native_limits_accessibility_and_responsive_styles(self) -> None:
        status, _, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        for marker in (
            b'type="url"',
            b'type="number"',
            b'min="1"',
            b'max="500"',
            b'type="checkbox"',
            b'type="date"',
            b'<fieldset class="gallery-date-range"',
            b'<legend>Date filter <span>Optional</span></legend>',
            b'role="status"',
            b"active tasks refresh automatically",
        ):
            self.assertIn(marker, script)

        status, _, stylesheet = self.request("/dashboard/gallery-dl.css")
        self.assertEqual(status, 200)
        for marker in (
            b".gallery-grid",
            b".gallery-archive-option",
            b".gallery-date-range",
            b".gallery-date-controls",
            b".gallery-date-field",
            b"min-height:44px",
            b".gallery-archive-option:focus-within",
            b".gallery-date-range:focus-within",
            b".gallery-archive-option:has(input:disabled)",
            b".gallery-date-range:disabled",
            b"@media(max-width:900px)",
            b"@media(max-width:560px)",
            b"prefers-color-scheme:dark",
        ):
            self.assertIn(marker, stylesheet)


if __name__ == "__main__":
    unittest.main()
