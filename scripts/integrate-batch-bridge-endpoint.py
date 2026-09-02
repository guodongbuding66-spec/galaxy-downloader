from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, got {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


resume = ROOT / "local-engine" / "resume_bridge.py"
replace_once(
    resume,
    "import bridge as base_bridge\nfrom bridge_submission_policy import StructuredLocalBridge, normalize_submission_result\n",
    "import bridge as base_bridge\nfrom batch_bridge import MAX_BATCH_BRIDGE_REQUEST_BYTES, handle_batch_download_request, run_batch_bridge_self_test\nfrom bridge_submission_policy import StructuredLocalBridge, normalize_submission_result\n",
)
replace_once(
    resume,
    "        self._discard_resume_job = getattr(owner, \"discard_resume_job\", None)\n",
    "        self._discard_resume_job = getattr(owner, \"discard_resume_job\", None)\n        self._submit_batch_jobs = getattr(owner, \"submit_batch_jobs_from_bridge\", None)\n",
)
replace_once(
    resume,
    '''            def _read_json(self) -> dict[str, Any] | None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length <= 0 or length > base_bridge.MAX_REQUEST_BYTES:
                    self._json(400, {"ok": False, "code": "BAD_REQUEST", "error": "Invalid request body"})
                    return None
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._json(400, {"ok": False, "code": "BAD_REQUEST", "error": "Invalid JSON"})
                    return None
                if not isinstance(payload, dict):
                    self._json(400, {"ok": False, "code": "BAD_REQUEST", "error": "JSON object required"})
                    return None
                return payload
''',
    '''            def _read_json(
                self,
                *,
                max_bytes: int = base_bridge.MAX_REQUEST_BYTES,
                oversize_status: int = 400,
                oversize_code: str = "BAD_REQUEST",
                oversize_error: str = "Invalid request body",
            ) -> dict[str, Any] | None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length <= 0:
                    self._json(400, {"ok": False, "code": "BAD_REQUEST", "error": "Invalid request body"})
                    return None
                if length > max_bytes:
                    self._json(oversize_status, {"ok": False, "code": oversize_code, "error": oversize_error})
                    return None
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._json(400, {"ok": False, "code": "BAD_REQUEST", "error": "Invalid JSON"})
                    return None
                if not isinstance(payload, dict):
                    self._json(400, {"ok": False, "code": "BAD_REQUEST", "error": "JSON object required"})
                    return None
                return payload

            def _batch_download(self) -> None:
                payload = self._read_json(
                    max_bytes=MAX_BATCH_BRIDGE_REQUEST_BYTES,
                    oversize_status=413,
                    oversize_code="BATCH_REQUEST_TOO_LARGE",
                    oversize_error="Batch request body is too large",
                )
                if payload is None:
                    return
                result = handle_batch_download_request(payload, local_bridge._submit_batch_jobs)
                self._json(result.status, result.payload)
''',
)
replace_once(
    resume,
    '''                if self.path == "/download":
                    payload = self._read_json()
                    if payload is None:
                        return
                    submission = normalize_submission_result(local_bridge._submit_job(payload))
                    self._json(
                        submission.status,
                        {"ok": submission.accepted, "accepted": submission.accepted, "code": submission.code, "message": submission.message},
                    )
                    return
''',
    '''                if self.path == "/batch/download":
                    self._batch_download()
                    return
                if self.path == "/download":
                    payload = self._read_json()
                    if payload is None:
                        return
                    submission = normalize_submission_result(local_bridge._submit_job(payload))
                    self._json(
                        submission.status,
                        {"ok": submission.accepted, "accepted": submission.accepted, "code": submission.code, "message": submission.message},
                    )
                    return
''',
)
replace_once(
    resume,
    '''            self.discarded = ""

        def after(self, _delay: int, callback) -> None:
''',
    '''            self.discarded = ""
            self.batch_calls = 0

        def after(self, _delay: int, callback) -> None:
''',
)
replace_once(
    resume,
    '''        def discard_resume_job(self, job_id: str) -> bool:
            if job_id not in self.records:
                return False
            self.records.remove(job_id)
            self.discarded = job_id
            return True
''',
    '''        def discard_resume_job(self, job_id: str) -> bool:
            if job_id not in self.records:
                return False
            self.records.remove(job_id)
            self.discarded = job_id
            return True

        def submit_batch_jobs_from_bridge(self, _batch, _options):
            self.batch_calls += 1
            raise AssertionError("route callback is not exercised by this embedded discovery test")
''',
)
replace_once(
    resume,
    '''    assert bridge._resume_result("missing")[1:3] == (404, "RESUME_JOB_NOT_FOUND")
''',
    '''    assert bridge._resume_result("missing")[1:3] == (404, "RESUME_JOB_NOT_FOUND")
    assert bridge._submit_batch_jobs is not None
    run_batch_bridge_self_test()
''',
)

bridge_test = ROOT / "scripts" / "test-local-bridge-submission.py"
replace_once(
    bridge_test,
    '''from bridge_submission_policy import (  # noqa: E402
    JobSubmissionResult,
    QueueCancellationResult,
    StructuredLocalBridge,
)
''',
    '''from batch_submission import submit_batch_input_result  # noqa: E402
from bridge_submission_policy import (  # noqa: E402
    JobSubmissionResult,
    QueueCancellationResult,
    StructuredLocalBridge,
)
from resume_bridge import PauseResumeLocalBridge  # noqa: E402
''',
)
replace_once(
    bridge_test,
    '''

if __name__ == "__main__":
    unittest.main(verbosity=2)
''',
    '''

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
                    "https://example.com/one?token=private-token\\n"
                    "not-a-url\\n"
                    "https://example.com/two\\n"
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
            {"input": large_comment + "\\nhttps://example.com/large", "format": "txt"},
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
''',
)

print("batch bridge endpoint integration applied")
