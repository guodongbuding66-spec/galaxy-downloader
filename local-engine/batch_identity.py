from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

MAX_BATCH_SIZE = 500
_BATCH_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def normalize_batch_identity(
    batch_id_value: object,
    batch_index_value: object,
    batch_size_value: object,
) -> tuple[str | None, int, int]:
    batch_id = str(batch_id_value or "").strip().lower()
    if not _BATCH_ID_RE.fullmatch(batch_id):
        return None, 0, 0
    try:
        batch_index = int(batch_index_value)
        batch_size = int(batch_size_value)
    except (TypeError, ValueError):
        return None, 0, 0
    if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
        return None, 0, 0
    if batch_index < 1 or batch_index > batch_size:
        return None, 0, 0
    return batch_id, batch_index, batch_size


def batch_identity_from_payload(payload: object) -> tuple[str | None, int, int]:
    if not isinstance(payload, dict):
        return None, 0, 0
    return normalize_batch_identity(
        payload.get("batchId"),
        payload.get("batchIndex"),
        payload.get("batchSize"),
    )


def batch_identity_from_job(job: object) -> tuple[str | None, int, int]:
    if job is None:
        return None, 0, 0
    return normalize_batch_identity(
        getattr(job, "batch_id", None),
        getattr(job, "batch_index", 0),
        getattr(job, "batch_size", 0),
    )


def install_batch_identity_policy(engine_module):
    """Attach validated Batch identity metadata to the canonical media Job.

    Batch identity is descriptive scheduling metadata only. It never changes URL
    validation, output paths, download selectors or queue admission. Batch
    submission generates the identity; this policy validates and preserves it
    through Job serialization so queue, history and restart recovery can agree on
    which jobs belong to the same user-reviewed batch.
    """
    if getattr(engine_module, "_galaxy_batch_identity_installed", False):
        return engine_module.Job

    base_job = engine_module.Job

    @dataclass(frozen=True)
    class BatchIdentityJob(base_job):
        batch_id: str | None = None
        batch_index: int = 0
        batch_size: int = 0

    BatchIdentityJob.__name__ = "Job"
    BatchIdentityJob.__qualname__ = "Job"
    engine_module.Job = BatchIdentityJob

    original_job_from_payload = engine_module.job_from_payload
    original_job_to_payload = engine_module.job_to_payload

    def job_from_payload(payload: dict[str, Any]):
        job = original_job_from_payload(payload)
        batch_id, batch_index, batch_size = batch_identity_from_payload(payload)
        return replace(
            job,
            batch_id=batch_id,
            batch_index=batch_index,
            batch_size=batch_size,
        )

    def job_to_payload(job) -> dict[str, Any]:
        payload = original_job_to_payload(job)
        batch_id, batch_index, batch_size = batch_identity_from_job(job)
        if batch_id is not None:
            payload.update(
                batchId=batch_id,
                batchIndex=batch_index,
                batchSize=batch_size,
            )
        else:
            payload.pop("batchId", None)
            payload.pop("batchIndex", None)
            payload.pop("batchSize", None)
        return payload

    engine_module.job_from_payload = job_from_payload
    engine_module.job_to_payload = job_to_payload

    original_bridge_status = engine_module.EngineWindow.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        batch_id, batch_index, batch_size = batch_identity_from_job(
            getattr(window, "job", None) if bool(getattr(window, "running", False)) else None
        )
        payload["batchIdentity"] = True
        payload["activeBatchId"] = batch_id
        payload["activeBatchIndex"] = batch_index
        payload["activeBatchSize"] = batch_size
        return payload

    engine_module.EngineWindow.bridge_status = bridge_status
    engine_module._galaxy_batch_identity_installed = True
    return BatchIdentityJob


def run_batch_identity_self_test(engine_module) -> None:
    single = engine_module.job_from_payload({"sourceUrl": "https://example.com/single"})
    assert getattr(single, "batch_id", None) is None
    assert getattr(single, "batch_index", 0) == 0
    assert getattr(single, "batch_size", 0) == 0
    single_payload = engine_module.job_to_payload(single)
    assert "batchId" not in single_payload
    assert "batchIndex" not in single_payload
    assert "batchSize" not in single_payload

    batch_id = "0123456789abcdef0123456789abcdef"
    grouped = engine_module.job_from_payload(
        {
            "sourceUrl": "https://example.com/grouped",
            "batchId": batch_id,
            "batchIndex": 2,
            "batchSize": 4,
        }
    )
    assert getattr(grouped, "batch_id", None) == batch_id
    assert getattr(grouped, "batch_index", 0) == 2
    assert getattr(grouped, "batch_size", 0) == 4
    grouped_payload = engine_module.job_to_payload(grouped)
    assert grouped_payload["batchId"] == batch_id
    assert grouped_payload["batchIndex"] == 2
    assert grouped_payload["batchSize"] == 4

    malformed = engine_module.job_from_payload(
        {
            "sourceUrl": "https://example.com/malformed",
            "batchId": batch_id,
            "batchIndex": 5,
            "batchSize": 4,
        }
    )
    assert getattr(malformed, "batch_id", None) is None
    assert "batchId" not in engine_module.job_to_payload(malformed)
