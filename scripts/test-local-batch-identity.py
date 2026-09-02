from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import engine  # noqa: E402
from batch_identity import install_batch_identity_policy, run_batch_identity_self_test  # noqa: E402
from batch_input import parse_batch_input  # noqa: E402
from batch_submission import submit_batch_input_result  # noqa: E402
from bridge_submission_policy import JobSubmissionResult  # noqa: E402
from job_history import _safe_retry_payload  # noqa: E402


def main() -> int:
    install_batch_identity_policy(engine)
    run_batch_identity_self_test(engine)

    batch = parse_batch_input(
        "https://example.com/one\nhttps://example.com/two\nhttps://example.com/three\n",
        format_hint="txt",
    )
    seen: list[dict[str, object]] = []

    def submit_one(payload: dict[str, object]) -> JobSubmissionResult:
        seen.append(dict(payload))
        return JobSubmissionResult(
            True,
            "accepted" if len(seen) == 1 else "queued",
            202,
            "ACCEPTED" if len(seen) == 1 else "QUEUED",
        )

    result = submit_batch_input_result(
        batch,
        {
            "videoQuality": "1080p",
            "batchId": "ffffffffffffffffffffffffffffffff",
            "batchIndex": 99,
            "batchSize": 99,
        },
        submit_one,
    )

    assert result.batch_id
    assert len(result.batch_id) == 32
    assert result.batch_id != "ffffffffffffffffffffffffffffffff"
    assert {payload["batchId"] for payload in seen} == {result.batch_id}
    assert [payload["batchIndex"] for payload in seen] == [1, 2, 3]
    assert [payload["batchSize"] for payload in seen] == [3, 3, 3]

    jobs = [engine.job_from_payload(payload) for payload in seen]
    assert [job.batch_index for job in jobs] == [1, 2, 3]
    assert all(job.batch_id == result.batch_id for job in jobs)
    assert all(job.batch_size == 3 for job in jobs)

    retry = _safe_retry_payload(engine.job_to_payload(jobs[1]))
    assert retry["batchId"] == result.batch_id
    assert retry["batchIndex"] == 2
    assert retry["batchSize"] == 3

    print("local batch identity tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
