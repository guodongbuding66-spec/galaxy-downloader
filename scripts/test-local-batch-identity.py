from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

from batch_identity import install_batch_identity_policy, run_batch_identity_self_test  # noqa: E402
from batch_input import parse_batch_input  # noqa: E402
from batch_submission import submit_batch_input_result  # noqa: E402
from bridge_submission_policy import JobSubmissionResult  # noqa: E402
from job_history import _safe_retry_payload  # noqa: E402


@dataclass(frozen=True)
class _FakeJob:
    source_url: str
    video_quality: str = "best"


class _FakeWindow:
    def __init__(self, job=None):
        self.job = job
        self.running = False

    def bridge_status(self):
        return {"busy": self.running}


def _fake_engine():
    def job_from_payload(payload):
        source_url = str(payload.get("sourceUrl") or "").strip()
        if not source_url:
            raise ValueError("sourceUrl is required")
        return _FakeJob(
            source_url=source_url,
            video_quality=str(payload.get("videoQuality") or "best"),
        )

    def job_to_payload(job):
        return {
            "sourceUrl": job.source_url,
            "videoQuality": job.video_quality,
        }

    return types.SimpleNamespace(
        Job=_FakeJob,
        EngineWindow=_FakeWindow,
        job_from_payload=job_from_payload,
        job_to_payload=job_to_payload,
    )


def main() -> int:
    engine = _fake_engine()
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

    window = engine.EngineWindow(jobs[0])
    window.running = True
    status = window.bridge_status()
    assert status["activeBatchId"] == result.batch_id
    assert status["activeBatchIndex"] == 1
    assert status["activeBatchSize"] == 3

    print("local batch identity tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
