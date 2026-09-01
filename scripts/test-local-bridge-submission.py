from __future__ import annotations

import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import bridge as base_bridge  # noqa: E402
from bridge_submission_policy import JobSubmissionResult, StructuredLocalBridge  # noqa: E402


class LocalBridgeSubmissionHttpTests(unittest.TestCase):
    def setUp(self):
        self.original_port = base_bridge.BRIDGE_PORT
        base_bridge.BRIDGE_PORT = 0

        def submit(payload):
            case = str(payload.get("case") or "accepted")
            mapping = {
                "accepted": JobSubmissionResult(True, "Download job accepted", 202, "ACCEPTED"),
                "queued": JobSubmissionResult(True, "Download queued at position 1", 202, "QUEUED"),
                "bad": JobSubmissionResult(False, "Invalid media URL", 400, "BAD_REQUEST"),
                "full": JobSubmissionResult(False, "Download queue is full", 409, "QUEUE_FULL"),
                "shutdown": JobSubmissionResult(False, "Engine is shutting down", 503, "ENGINE_SHUTTING_DOWN"),
                "timeout": JobSubmissionResult(False, "Desktop handoff timed out", 504, "ENGINE_HANDOFF_TIMEOUT"),
                "legacy": (False, "Legacy engine busy"),
            }
            return mapping[case]

        self.bridge = StructuredLocalBridge(
            status_provider=lambda: {"version": "0.8.0", "busy": False},
            submit_job=submit,
            cancel_job=lambda: None,
            open_folder=lambda: None,
        )
        self.bridge.start()
        assert self.bridge._server is not None
        self.port = int(self.bridge._server.server_address[1])

    def tearDown(self):
        self.bridge.stop()
        base_bridge.BRIDGE_PORT = self.original_port

    def post(self, case: str) -> tuple[int, dict]:
        body = json.dumps({"case": case}).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/download",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_accepted_and_queued_jobs_return_202(self):
        for case, code in (("accepted", "ACCEPTED"), ("queued", "QUEUED")):
            with self.subTest(case=case):
                status, payload = self.post(case)
                self.assertEqual(status, 202)
                self.assertTrue(payload["accepted"])
                self.assertEqual(payload["code"], code)

    def test_rejections_have_distinct_http_semantics(self):
        expected = {
            "bad": (400, "BAD_REQUEST"),
            "full": (409, "QUEUE_FULL"),
            "shutdown": (503, "ENGINE_SHUTTING_DOWN"),
            "timeout": (504, "ENGINE_HANDOFF_TIMEOUT"),
        }
        for case, (wanted_status, wanted_code) in expected.items():
            with self.subTest(case=case):
                status, payload = self.post(case)
                self.assertEqual(status, wanted_status)
                self.assertFalse(payload["accepted"])
                self.assertEqual(payload["code"], wanted_code)

    def test_legacy_two_tuple_callback_remains_compatible(self):
        status, payload = self.post("legacy")
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "ENGINE_BUSY")
        self.assertEqual(payload["message"], "Legacy engine busy")

    def test_invalid_json_is_400_bad_request(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/download",
            data=b"{not-json",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as captured:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(captured.exception.code, 400)
        payload = json.loads(captured.exception.read().decode("utf-8"))
        self.assertEqual(payload["code"], "BAD_REQUEST")


if __name__ == "__main__":
    unittest.main(verbosity=2)
