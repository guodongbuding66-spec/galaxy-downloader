from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, got {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


entrypoint = ROOT / "local-engine" / "entrypoint.py"
replace_once(
    entrypoint,
    "from batch_input import run_batch_input_self_test\n",
    "from batch_input import run_batch_input_self_test\nfrom batch_submission import run_batch_submission_self_test\n",
)
replace_once(
    entrypoint,
    "    run_batch_input_self_test()\n    run_job_scheduler_self_test()\n",
    "    run_batch_input_self_test()\n    run_batch_submission_self_test()\n    run_job_scheduler_self_test()\n",
)

queue_test = ROOT / "scripts" / "test-local-job-queue.py"
replace_once(
    queue_test,
    "import job_queue  # noqa: E402\nfrom bridge_submission_policy import StructuredLocalBridge  # noqa: E402\n",
    "import job_queue  # noqa: E402\nfrom batch_input import parse_batch_input  # noqa: E402\nfrom batch_submission import run_batch_submission_self_test  # noqa: E402\nfrom bridge_submission_policy import StructuredLocalBridge  # noqa: E402\n",
)
replace_once(
    queue_test,
    "    def test_scheduler_core_self_test(self):\n        run_job_scheduler_self_test()\n\n",
    "    def test_scheduler_core_self_test(self):\n        run_job_scheduler_self_test()\n\n    def test_batch_submission_controller_self_test(self):\n        run_batch_submission_self_test()\n\n",
)
replace_once(
    queue_test,
    "    def test_busy_job_is_queued_with_safe_visible_summary(self):\n",
    '''    def test_batch_submission_starts_first_and_queues_remaining_in_order(self):
        _engine, window = self.make_window()
        batch = parse_batch_input(
            "https://example.com/1\\nhttps://example.com/2\\nhttps://example.com/3\\n",
            format_hint="txt",
        )
        result = window.submit_batch_jobs_from_bridge(batch, {"videoQuality": "720p"})
        self.assertEqual(result.accepted_count, 3)
        self.assertEqual(result.started_count, 1)
        self.assertEqual(result.queued_count, 2)
        self.assertEqual(result.remaining_count, 0)
        self.assertEqual(window.started[-1]["sourceUrl"], "https://example.com/1")
        self.assertEqual(window.started[-1]["videoQuality"], "720p")
        self.assertEqual(
            [queued.job["sourceUrl"] for queued in window.pending_jobs],
            ["https://example.com/2", "https://example.com/3"],
        )
        self.assertTrue(all(queued.job["videoQuality"] == "720p" for queued in window.pending_jobs))

    def test_batch_submission_bad_request_isolated_to_one_row(self):
        fake_engine, window = self.make_window()

        def normalize(payload):
            if str(payload.get("sourceUrl") or "").endswith("/bad"):
                raise ValueError("A valid public HTTP URL is required")
            return dict(payload)

        fake_engine.job_from_payload = normalize
        batch = parse_batch_input(
            "https://example.com/1\\nhttps://example.com/bad\\nhttps://example.com/3\\n",
            format_hint="txt",
        )
        result = window.submit_batch_jobs_from_bridge(batch, {})
        self.assertEqual(result.accepted_count, 2)
        self.assertEqual(result.rejected_count, 1)
        self.assertEqual(result.remaining_count, 0)
        self.assertFalse(result.stopped)
        self.assertEqual([outcome.code for outcome in result.outcomes], ["ACCEPTED", "BAD_REQUEST", "QUEUED"])
        self.assertEqual(window.started[-1]["sourceUrl"], "https://example.com/1")
        self.assertEqual(
            [queued.job["sourceUrl"] for queued in window.pending_jobs],
            ["https://example.com/3"],
        )

    def test_busy_job_is_queued_with_safe_visible_summary(self):
''',
)

print("batch submission controller integration applied")
