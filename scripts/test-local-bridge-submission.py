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
from batch_submission import submit_batch_input_result  # noqa: E402
from bridge_submission_policy import (  # noqa: E402
    JobSubmissionResult,
    QueueCancellationResult,
    StructuredLocalBridge,
)
from resume_bridge import PauseResumeLocalBridge  # noqa: E402


class _StatusOwner:
    def __init__(self):
        self.cancelled_ids: list[str] = []

    def status(self):
        return {
            "version": "0.8.0",
            "busy": True,
            "queueLength": 1,
            "queueCapacity": 25,
            "queuedJobs": [
                {
                    "id": "a" * 32,
                    "position": 1,
                    "label": "Example video",
                    "sourceHost": "example.com",
                }
            ],
        }

    def cancel_queued_job_from_bridge(self, job_id: str) -> QueueCancellationResult:
        if job_id == "a" * 32:
            self.cancelled_ids.append(job_id)
            return QueueCancellationResult(True, "Queued download cancelled", 200, "QUEUE_ITEM_CANCELLED")
        if job_id == "b" * 32:
            return QueueCancellationResult(
                False,
                "Timed out while handing queue cancellation to the desktop window",
                504,
                "ENGINE_HANDOFF_TIMEOUT",
            )
        return QueueCancellationResult(False, "Queued download not found", 404, "QUEUE_ITEM_NOT_FOUND")


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

        self.status_owner = _StatusOwner()
        self.bridge = StructuredLocalBridge(
            status_provider=self.status_owner.status,
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

    def post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def post(self, case: str) -> tuple[int, dict]:
        return self.post_json("/download", {"case": case})

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

    def test_status_exposes_queue_summary_without_source_url(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/status", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["queueLength"], 1)
        self.assertEqual(payload["queuedJobs"][0]["sourceHost"], "example.com")
        self.assertNotIn("sourceUrl", payload["queuedJobs"][0])

    def test_queue_item_can_be_cancelled_by_id(self):
        job_id = "a" * 32
        status, payload = self.post_json("/queue/cancel", {"jobId": job_id})
        self.assertEqual(status, 200)
        self.assertTrue(payload["cancelled"])
        self.assertEqual(payload["code"], "QUEUE_ITEM_CANCELLED")
        self.assertEqual(payload["jobId"], job_id)
        self.assertEqual(self.status_owner.cancelled_ids, [job_id])

    def test_unknown_queue_item_is_404(self):
        status, payload = self.post_json("/queue/cancel", {"jobId": "c" * 32})
        self.assertEqual(status, 404)
        self.assertFalse(payload["cancelled"])
        self.assertEqual(payload["code"], "QUEUE_ITEM_NOT_FOUND")

    def test_queue_cancellation_handoff_timeout_is_504(self):
        status, payload = self.post_json("/queue/cancel", {"jobId": "b" * 32})
        self.assertEqual(status, 504)
        self.assertEqual(payload["code"], "ENGINE_HANDOFF_TIMEOUT")

    def test_invalid_queue_job_id_is_400(self):
        status, payload = self.post_json("/queue/cancel", {"jobId": "../../secret"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "BAD_REQUEST")

    def test_queue_control_is_discovered_from_bound_status_owner(self):
        self.assertIsNotNone(self.bridge._cancel_queued_job)


class _BatchResumeOwner:
    def __init__(self):
        self.seen_payloads: list[dict] = []

    def after(self, _delay: int, callback, *args) -> None:
        callback(*args)

    def status(self):
        return {
            "version": "0.15.0",
            "busy": False,
            "canPause": False,
            "queueLength": 0,
            "queueCapacity": 25,
            "queuedJobs": [],
            "activeJobId": None,
            "resumeJobs": [],
        }

    def submit_batch_jobs_from_bridge(self, batch, options):
        calls = 0

        def submit_one(payload):
            nonlocal calls
            calls += 1
            self.seen_payloads.append(dict(payload))
            return JobSubmissionResult(
                True,
                "accepted" if calls == 1 else "queued",
                202,
                "ACCEPTED" if calls == 1 else "QUEUED",
            )

        return submit_batch_input_result(batch, options, submit_one)


class PauseResumeBatchBridgeHttpTests(unittest.TestCase):
    def setUp(self):
        self.original_port = base_bridge.BRIDGE_PORT
        base_bridge.BRIDGE_PORT = 0
        self.owner = _BatchResumeOwner()
        self.bridge = PauseResumeLocalBridge(
            status_provider=self.owner.status,
            submit_job=lambda _payload: JobSubmissionResult(True, "accepted", 202, "ACCEPTED"),
            cancel_job=lambda: None,
            open_folder=lambda: None,
        )
        self.bridge.start()
        assert self.bridge._server is not None
        self.port = int(self.bridge._server.server_address[1])

    def tearDown(self):
        self.bridge.stop()
        base_bridge.BRIDGE_PORT = self.original_port

    def post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_real_v5_handler_accepts_batch_download_without_url_leakage(self):
        status, payload = self.post_json(
            "/batch/download",
            {
                "input": (
                    "https://example.com/one?token=private-token\n"
                    "not-a-url\n"
                    "https://example.com/two\n"
                ),
                "format": "txt",
                "options": {"videoQuality": "1080p"},
            },
        )
        self.assertEqual(status, 202)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["code"], "BATCH_PARTIAL")
        self.assertEqual(payload["acceptedCount"], 2)
        self.assertEqual(payload["inputIssueCount"], 1)
        self.assertEqual([item["code"] for item in payload["outcomes"]], ["ACCEPTED", "QUEUED"])
        self.assertEqual([item["videoQuality"] for item in self.owner.seen_payloads], ["1080p", "1080p"])
        rendered = repr(payload)
        self.assertNotIn("private-token", rendered)
        self.assertNotIn("sourceUrl", rendered)

    def test_batch_route_has_large_body_limit_without_widening_normal_download(self):
        large_comment = "#" + ("x" * 40_000)
        batch_status, batch_payload = self.post_json(
            "/batch/download",
            {"input": large_comment + "\nhttps://example.com/large", "format": "txt"},
        )
        self.assertEqual(batch_status, 202)
        self.assertEqual(batch_payload["acceptedCount"], 1)

        normal_status, normal_payload = self.post_json(
            "/download",
            {"sourceUrl": "https://example.com/a", "padding": "x" * 40_000},
        )
        self.assertEqual(normal_status, 400)
        self.assertEqual(normal_payload["code"], "BAD_REQUEST")

    def test_batch_controller_is_discovered_from_bound_owner(self):
        self.assertIsNotNone(self.bridge._submit_batch_jobs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
