from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from batch_bridge import (  # noqa: E402
    MAX_BATCH_BRIDGE_REQUEST_BYTES,
    handle_batch_download_request,
    run_batch_bridge_self_test,
)
from batch_submission import submit_batch_input_result  # noqa: E402
from bridge_submission_policy import JobSubmissionResult  # noqa: E402


class BatchBridgePolicyTests(unittest.TestCase):
    def test_embedded_self_test(self):
        run_batch_bridge_self_test()

    def test_empty_input_is_bad_request(self):
        response = handle_batch_download_request({"input": "   \n\n"}, lambda _batch, _options: None)
        self.assertEqual(response.status, 400)
        self.assertEqual(response.payload["code"], "BATCH_EMPTY")
        self.assertEqual(response.payload["acceptedCount"], 0)

    def test_parse_only_failures_are_url_free(self):
        response = handle_batch_download_request(
            {"input": "http://user:super-secret@127.0.0.1/private\n", "format": "txt"},
            lambda _batch, _options: None,
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(response.payload["code"], "BATCH_INVALID_INPUT")
        self.assertEqual(response.payload["inputIssueCount"], 1)
        rendered = repr(response.payload)
        self.assertNotIn("super-secret", rendered)
        self.assertNotIn("127.0.0.1/private", rendered)

    def test_invalid_request_shapes_fail_before_submission(self):
        cases = (
            (None, "BAD_REQUEST"),
            ({}, "BAD_REQUEST"),
            ({"input": []}, "BAD_REQUEST"),
            ({"input": "https://example.com/a", "format": 5}, "BAD_REQUEST"),
            ({"input": "https://example.com/a", "format": "yaml"}, "BAD_REQUEST"),
            ({"input": "https://example.com/a", "options": []}, "BAD_REQUEST"),
        )
        for request, code in cases:
            with self.subTest(request=request):
                response = handle_batch_download_request(request, lambda _batch, _options: None)
                self.assertEqual(response.status, 400)
                self.assertEqual(response.payload["code"], code)

    def test_unavailable_controller_is_501_without_urls(self):
        response = handle_batch_download_request(
            {"input": "https://example.com/a?token=private-token"},
            None,
        )
        self.assertEqual(response.status, 501)
        self.assertEqual(response.payload["code"], "BATCH_CONTROL_UNAVAILABLE")
        self.assertNotIn("private-token", repr(response.payload))

    def test_partial_acceptance_keeps_http_202_and_terminal_reason(self):
        calls = 0

        def submit_batch(batch, options):
            def submit_one(_payload):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return JobSubmissionResult(True, "accepted", 202, "ACCEPTED")
                return JobSubmissionResult(False, "full", 409, "QUEUE_FULL")

            return submit_batch_input_result(batch, options, submit_one)

        response = handle_batch_download_request(
            {
                "input": "https://example.com/a\nhttps://example.com/b\nhttps://example.com/c\n",
                "options": {"videoQuality": "720p"},
            },
            submit_batch,
        )
        self.assertEqual(response.status, 202)
        self.assertTrue(response.payload["ok"])
        self.assertEqual(response.payload["code"], "BATCH_PARTIAL")
        self.assertEqual(response.payload["acceptedCount"], 1)
        self.assertEqual(response.payload["rejectedCount"], 1)
        self.assertEqual(response.payload["remainingCount"], 1)
        self.assertEqual(response.payload["stoppedCode"], "QUEUE_FULL")
        self.assertEqual(calls, 2)

    def test_all_bad_request_submissions_are_400_not_terminal(self):
        def submit_batch(batch, options):
            return submit_batch_input_result(
                batch,
                options,
                lambda _payload: JobSubmissionResult(False, "bad", 400, "BAD_REQUEST"),
            )

        response = handle_batch_download_request(
            {"input": "https://example.com/a\nhttps://example.com/b\n"},
            submit_batch,
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(response.payload["code"], "BATCH_REJECTED")
        self.assertEqual(response.payload["rejectedCount"], 2)
        self.assertEqual(response.payload["remainingCount"], 0)

    def test_callback_exception_is_generic_and_secret_free(self):
        def broken(_batch, _options):
            raise RuntimeError("failed for https://example.com/a?token=very-secret")

        response = handle_batch_download_request(
            {"input": "https://example.com/a?token=very-secret"},
            broken,
        )
        self.assertEqual(response.status, 500)
        self.assertEqual(response.payload["code"], "BATCH_CONTROL_FAILED")
        self.assertNotIn("very-secret", repr(response.payload))

    def test_request_byte_limit_covers_worst_case_utf8_input_envelope(self):
        self.assertGreater(MAX_BATCH_BRIDGE_REQUEST_BYTES, 4_000_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
