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

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _Handler(HeadlessWebDashboardMixin, _FallbackHandler):
    pass


class HeadlessGalleryDlRateUiTest(unittest.TestCase):
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
        assert not cls.thread.is_alive()

    def request(self, path: str) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        status = response.status
        connection.close()
        return status, body

    def test_rate_control_is_optional_numeric_and_capability_gated(self) -> None:
        status, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        for marker in (
            b'id="galleryRateLimit"',
            b'name="rateLimitMiB"',
            b'type="number"',
            b'min="0.1"',
            b'max="1024"',
            b'step="0.1"',
            b'inputmode="decimal"',
            b'placeholder="Unlimited"',
            b'aria-describedby="galleryRateHelp"',
            b"state.engine?.rateLimitSupported === true",
            b"state.engine?.rateLimitMinMiB",
            b"state.engine?.rateLimitMaxMiB",
            b"if (!rateSupported) rateControl.value = ''",
            b"rateControl.disabled = state.submitPending || !installed || !acceptingJobs || !rateSupported",
        ):
            self.assertIn(marker, script)

        markup = script.split(b'id="galleryRateLimit"', 1)[1].split(b"></label>", 1)[0]
        self.assertNotIn(b"value=", markup)
        self.assertNotIn(b"required", markup)
        self.assertIn(b"Blank = unlimited", script)

    def test_rate_submission_is_bounded_numeric_and_opt_in_only(self) -> None:
        status, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        submit = script.split(b"async function submitGallery(event)", 1)[1].split(
            b"async function runJobAction", 1
        )[0]

        for marker in (
            b"const rateText = rateSupported ? $('galleryRateLimit').value.trim() : ''",
            b"let rateLimitMiB = null",
            b"const parsedRate = Number(rateText)",
            b"Number.isFinite(parsedRate)",
            b"parsedRate < rateMin",
            b"parsedRate > rateMax",
            b"$('galleryRateLimit').focus()",
            b"if (rateLimitMiB !== null) payload.rateLimitMiB = rateLimitMiB",
        ):
            self.assertIn(marker, submit)

        payload_start = submit.index(b"const payload = {")
        rate_assignment = submit.index(b"if (rateLimitMiB !== null) payload.rateLimitMiB = rateLimitMiB")
        post_call = submit.index(b"postJson('/v1/gallery-dl/jobs', payload)")
        self.assertLess(payload_start, rate_assignment)
        self.assertLess(rate_assignment, post_call)
        self.assertNotIn(b"rateLimitMiB: null", submit)
        self.assertNotIn(b"rateLimitMiB: 0", submit)

    def test_rate_composes_without_raw_gallery_dl_escape_surface(self) -> None:
        status, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        for marker in (
            b"archiveEnabled: Boolean(archiveEnabled)",
            b"if (resumeEnabled) payload.resumeEnabled = true",
            b"if (dateAfter) payload.dateAfter = dateAfter",
            b"if (dateBefore) payload.dateBefore = dateBefore",
            b"if (rateLimitMiB !== null) payload.rateLimitMiB = rateLimitMiB",
        ):
            self.assertIn(marker, script)

        for forbidden in (
            b"ratePath",
            b"rateConfig",
            b"downloaderRate",
            b"rateString",
            b"outputRoot",
            b"cookieFile",
            b"httpHeaders",
            b"localStorage",
        ):
            self.assertNotIn(forbidden, script)

    def test_rate_control_follows_existing_accessible_responsive_visual_system(self) -> None:
        status, stylesheet = self.request("/dashboard/gallery-dl.css")
        self.assertEqual(status, 200)
        for marker in (
            b".gallery-rate-field",
            b"width:168px",
            b"min-width:168px",
            b".gallery-form .field input{height:44px",
            b".gallery-limit-field,.gallery-rate-field{width:auto;min-width:160px;flex:1}",
            b".gallery-limit-field,.gallery-rate-field,.gallery-archive-option,.gallery-resume-option{min-width:100%}",
            b".gallery-rate-field>span small,.gallery-rate-field>small{color:#9aa6b2}",
            b"@media(max-width:900px)",
            b"@media(max-width:560px)",
            b"prefers-color-scheme:dark",
        ):
            self.assertIn(marker, stylesheet)


if __name__ == "__main__":
    unittest.main()
