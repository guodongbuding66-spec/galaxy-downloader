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


class HeadlessGalleryDlOutputDirectoryUiTest(unittest.TestCase):
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

    def test_output_directory_control_is_optional_relative_and_capability_gated(self) -> None:
        status, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        for marker in (
            b'id="galleryOutputDirectory"',
            b'name="outputDirectory"',
            b'type="text"',
            b'placeholder="Gallery/Artist"',
            b'autocomplete="off"',
            b'aria-describedby="galleryOutputDirectoryHelp"',
            b"state.engine?.outputDirectorySupported === true",
            b"state.engine?.outputDirectoryMaxLength",
            b"state.engine?.outputDirectoryMaxDepth",
            b"if (!outputDirectorySupported) outputControl.value = ''",
            b"outputControl.disabled = state.submitPending || !installed || !acceptingJobs || !outputDirectorySupported",
        ):
            self.assertIn(marker, script)

        markup = script.split(b'id="galleryOutputDirectory"', 1)[1].split(b"></label>", 1)[0]
        self.assertNotIn(b"required", markup)
        self.assertNotIn(b"value=", markup)
        self.assertIn(b"Relative to the configured download root", script)

    def test_output_directory_submission_is_bounded_and_opt_in_only(self) -> None:
        status, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        submit = script.split(b"async function submitGallery(event)", 1)[1].split(
            b"async function runJobAction", 1
        )[0]

        for marker in (
            b"const outputDirectorySupported = state.engine?.outputDirectorySupported === true",
            b"const outputDirectory = outputDirectorySupported ? $('galleryOutputDirectory').value.trim() : ''",
            b"const { maxLength: outputMaxLength, maxDepth: outputMaxDepth } = outputDirectoryBounds()",
            b"const outputParts = outputDirectory.split('/')",
            b"outputDirectory.length > outputMaxLength",
            b"outputParts.length > outputMaxDepth",
            b"outputDirectory.includes('\\\\')",
            b"/^[A-Za-z]:/.test(outputDirectory)",
            b"part === '.' || part === '..'",
            b"$('galleryOutputDirectory').focus()",
            b"if (outputDirectory) payload.outputDirectory = outputDirectory",
        ):
            self.assertIn(marker, submit)

        payload_start = submit.index(b"const payload = {")
        output_assignment = submit.index(b"if (outputDirectory) payload.outputDirectory = outputDirectory")
        post_call = submit.index(b"postJson('/v1/gallery-dl/jobs', payload)")
        self.assertLess(payload_start, output_assignment)
        self.assertLess(output_assignment, post_call)
        self.assertNotIn(b"outputDirectory: ''", submit)

    def test_output_directory_composes_without_absolute_path_escape_surface(self) -> None:
        status, script = self.request("/dashboard/gallery-dl.js")
        self.assertEqual(status, 200)
        for marker in (
            b"archiveEnabled: Boolean(archiveEnabled)",
            b"if (resumeEnabled) payload.resumeEnabled = true",
            b"if (dateAfter) payload.dateAfter = dateAfter",
            b"if (dateBefore) payload.dateBefore = dateBefore",
            b"if (rateLimitMiB !== null) payload.rateLimitMiB = rateLimitMiB",
            b"if (outputDirectory) payload.outputDirectory = outputDirectory",
        ):
            self.assertIn(marker, script)

        for forbidden in (
            b"outputRoot",
            b"outputPath",
            b"directoryPath",
            b"file://",
            b"localStorage",
            b"cookieFile",
            b"httpHeaders",
        ):
            self.assertNotIn(forbidden, script)

    def test_output_directory_control_follows_existing_accessible_responsive_visual_system(self) -> None:
        status, stylesheet = self.request("/dashboard/gallery-dl.css")
        self.assertEqual(status, 200)
        for marker in (
            b".gallery-output-field",
            b"min-width:260px",
            b"flex:1 1 280px",
            b".gallery-form .field input{height:44px",
            b".gallery-output-field>small",
            b".gallery-limit-field,.gallery-rate-field,.gallery-output-field{width:auto;min-width:160px;flex:1}",
            b".gallery-limit-field,.gallery-rate-field,.gallery-output-field,.gallery-archive-option,.gallery-resume-option{min-width:100%}",
            b".gallery-output-field>small{color:#9aa6b2}",
            b"@media(max-width:900px)",
            b"@media(max-width:560px)",
            b"prefers-color-scheme:dark",
        ):
            self.assertIn(marker, stylesheet)


if __name__ == "__main__":
    unittest.main()
