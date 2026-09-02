from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from batch_input import parse_batch_input  # noqa: E402
from batch_submission import run_batch_submission_self_test, submit_batch_input_result  # noqa: E402
from bridge_submission_policy import JobSubmissionResult  # noqa: E402


class BatchSubmissionControllerTests(unittest.TestCase):
    def test_embedded_self_test(self):
        run_batch_submission_self_test()

    def test_duplicate_urls_are_submitted_in_original_order(self):
        batch = parse_batch_input(
            "https://example.com/a\nhttps://example.com/a\nhttps://example.com/b\n",
            format_hint="txt",
        )
        seen: list[str] = []

        def submit(payload):
            seen.append(payload["sourceUrl"])
            return JobSubmissionResult(True, "queued", 202, "QUEUED")

        result = submit_batch_input_result(batch, {}, submit)
        self.assertEqual(seen, [item.source_url for item in batch.items])
        self.assertEqual(result.accepted_count, 3)
        self.assertEqual(result.queued_count, 3)

    def test_row_title_overrides_stale_template_title(self):
        batch = parse_batch_input(
            "sourceUrl,displayTitle\nhttps://example.com/a, First   title \nhttps://example.com/b,\n",
            format_hint="csv",
        )
        seen: list[dict[str, object]] = []

        def submit(payload):
            seen.append(dict(payload))
            return JobSubmissionResult(True, "queued", 202, "QUEUED")

        submit_batch_input_result(
            batch,
            {
                "sourceUrl": "https://stale.invalid",
                "displayTitle": "stale title",
                "videoQuality": "720p",
                "includeAudio": True,
            },
            submit,
        )
        self.assertEqual(seen[0]["sourceUrl"], "https://example.com/a")
        self.assertEqual(seen[0]["displayTitle"], "First title")
        self.assertNotIn("displayTitle", seen[1])
        self.assertTrue(all(payload["videoQuality"] == "720p" for payload in seen))
        self.assertTrue(all(payload["includeAudio"] is True for payload in seen))

    def test_bad_request_rejects_one_row_and_continues(self):
        batch = parse_batch_input(
            "https://example.com/1\nhttps://example.com/2\nhttps://example.com/3\n",
            format_hint="txt",
        )
        calls = 0

        def submit(_payload):
            nonlocal calls
            calls += 1
            if calls == 2:
                return JobSubmissionResult(False, "bad", 400, "BAD_REQUEST")
            return JobSubmissionResult(True, "queued", 202, "QUEUED")

        result = submit_batch_input_result(batch, {}, submit)
        self.assertEqual(calls, 3)
        self.assertEqual(result.accepted_count, 2)
        self.assertEqual(result.rejected_count, 1)
        self.assertEqual(result.remaining_count, 0)
        self.assertFalse(result.stopped)
        self.assertEqual([outcome.row for outcome in result.outcomes], [1, 2, 3])

    def test_queue_full_stops_without_hammering_remaining_rows(self):
        batch = parse_batch_input(
            "https://example.com/1\nhttps://example.com/2\nhttps://example.com/3\n",
            format_hint="txt",
        )
        calls = 0

        def submit(_payload):
            nonlocal calls
            calls += 1
            if calls == 2:
                return JobSubmissionResult(False, "full", 409, "QUEUE_FULL")
            return JobSubmissionResult(True, "queued", 202, "QUEUED")

        result = submit_batch_input_result(batch, {}, submit)
        self.assertEqual(calls, 2)
        self.assertEqual(result.attempted_count, 2)
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.remaining_count, 1)
        self.assertEqual(result.stopped_code, "QUEUE_FULL")

    def test_shutdown_timeout_and_5xx_are_terminal(self):
        batch = parse_batch_input(
            "https://example.com/1\nhttps://example.com/2\n",
            format_hint="txt",
        )
        for submission in (
            JobSubmissionResult(False, "shutdown", 503, "ENGINE_SHUTTING_DOWN"),
            JobSubmissionResult(False, "timeout", 504, "ENGINE_HANDOFF_TIMEOUT"),
            JobSubmissionResult(False, "weird", 502, "UPSTREAM_FAILURE"),
        ):
            with self.subTest(code=submission.code):
                calls = 0

                def submit(_payload, value=submission):
                    nonlocal calls
                    calls += 1
                    return value

                result = submit_batch_input_result(batch, {}, submit)
                self.assertEqual(calls, 1)
                self.assertEqual(result.remaining_count, 1)
                self.assertTrue(result.stopped)

    def test_callback_exception_is_fail_closed_and_secret_free(self):
        batch = parse_batch_input(
            "https://example.com/a?token=super-secret\nhttps://example.com/b\n",
            format_hint="txt",
        )

        def submit(_payload):
            raise RuntimeError("failed on https://example.com/a?token=super-secret")

        result = submit_batch_input_result(batch, {}, submit)
        self.assertEqual(result.stopped_code, "INTERNAL_ERROR")
        self.assertEqual(result.remaining_count, 1)
        self.assertNotIn("super-secret", repr(result))

    def test_parse_issue_count_is_preserved_without_resubmitting_invalid_rows(self):
        batch = parse_batch_input(
            "not-a-url\nhttps://example.com/ok\n",
            format_hint="txt",
        )
        calls = 0

        def submit(_payload):
            nonlocal calls
            calls += 1
            return JobSubmissionResult(True, "accepted", 202, "ACCEPTED")

        result = submit_batch_input_result(batch, {}, submit)
        self.assertEqual(calls, 1)
        self.assertEqual(result.input_count, 1)
        self.assertEqual(result.input_issue_count, 1)
        self.assertEqual(result.started_count, 1)

    def test_invalid_arguments_fail_fast(self):
        batch = parse_batch_input("https://example.com/a\n", format_hint="txt")
        with self.assertRaises(TypeError):
            submit_batch_input_result(object(), {}, lambda _payload: None)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            submit_batch_input_result(batch, object(), lambda _payload: None)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            submit_batch_input_result(batch, {}, None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main(verbosity=2)
