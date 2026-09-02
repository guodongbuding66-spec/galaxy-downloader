from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def update(path: str, transforms: list[tuple[str, str, str]]) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    for old, new, label in transforms:
        text = replace_once(text, old, new, f"{path}: {label}")
    target.write_text(text, encoding="utf-8")


def main() -> None:
    update(
        "local-engine/batch_submission.py",
        [
            (
                "from dataclasses import dataclass\n",
                "from dataclasses import dataclass\nimport uuid\n",
                "uuid import",
            ),
            (
                "    stopped_code: str | None = None\n\n    @property\n",
                "    stopped_code: str | None = None\n    batch_id: str = \"\"\n\n    @property\n",
                "result batch id",
            ),
            (
                "def _payload_for_item(base_payload: dict[str, Any], item: BatchInputItem) -> dict[str, Any]:\n",
                "def _payload_for_item(\n    base_payload: dict[str, Any],\n    item: BatchInputItem,\n    *,\n    batch_id: str,\n    batch_index: int,\n    batch_size: int,\n) -> dict[str, Any]:\n",
                "payload signature",
            ),
            (
                "    else:\n        payload.pop(\"displayTitle\", None)\n    return payload\n\n\ndef _safe_submit",
                "    else:\n        payload.pop(\"displayTitle\", None)\n    # Batch identity is generated inside the Local Engine and always overwrites\n    # stale/template values supplied by the caller.\n    payload[\"batchId\"] = batch_id\n    payload[\"batchIndex\"] = batch_index\n    payload[\"batchSize\"] = batch_size\n    return payload\n\n\ndef _safe_submit",
                "payload identity",
            ),
            (
                "    outcomes: list[BatchSubmissionItemResult] = []\n    stopped_code: str | None = None\n\n    for item in batch.items:\n        payload = _payload_for_item(base_payload, item)\n",
                "    batch_id = uuid.uuid4().hex\n    batch_size = len(batch.items)\n    outcomes: list[BatchSubmissionItemResult] = []\n    stopped_code: str | None = None\n\n    for batch_index, item in enumerate(batch.items, start=1):\n        payload = _payload_for_item(\n            base_payload,\n            item,\n            batch_id=batch_id,\n            batch_index=batch_index,\n            batch_size=batch_size,\n        )\n",
                "submission identity",
            ),
            (
                "        remaining_count=max(0, len(batch.items) - attempted),\n        stopped_code=stopped_code,\n    )\n",
                "        remaining_count=max(0, len(batch.items) - attempted),\n        stopped_code=stopped_code,\n        batch_id=batch_id,\n    )\n",
                "return identity",
            ),
        ],
    )

    update(
        "local-engine/batch_bridge.py",
        [
            (
                "    return {\n        \"format\": result.source_format,\n",
                "    return {\n        \"batchId\": result.batch_id or None,\n        \"format\": result.source_format,\n",
                "response batch id",
            ),
            (
                "    assert response.payload[\"acceptedCount\"] == 2\n",
                "    assert response.payload[\"acceptedCount\"] == 2\n    assert response.payload[\"batchId\"] == seen[0][\"batchId\"]\n",
                "bridge identity assertion",
            ),
        ],
    )

    update(
        "local-engine/job_queue.py",
        [
            (
                "from urllib.parse import urlparse\n\nfrom batch_input import BatchInputResult\n",
                "from urllib.parse import urlparse\n\nfrom batch_identity import batch_identity_from_job\nfrom batch_input import BatchInputResult\n",
                "batch identity import",
            ),
            (
                "def _queued_media_job(payload: dict[str, Any], job: Any) -> QueuedMediaJob:\n",
                "def _batch_queue_status_fields(job: Any) -> dict[str, Any]:\n    batch_id, batch_index, batch_size = batch_identity_from_job(job)\n    if batch_id is None:\n        return {}\n    return {\n        \"batchId\": batch_id,\n        \"batchIndex\": batch_index,\n        \"batchSize\": batch_size,\n    }\n\n\ndef _queued_media_job(payload: dict[str, Any], job: Any) -> QueuedMediaJob:\n",
                "queue status helper",
            ),
            (
                "                        \"sourceHost\": queued.source_host,\n                    }\n",
                "                        \"sourceHost\": queued.source_host,\n                        **_batch_queue_status_fields(queued.job),\n                    }\n",
                "queue status identity",
            ),
        ],
    )

    update(
        "local-engine/job_history.py",
        [
            (
                "from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit\n\nfrom failure_policy import classify_failure, sanitize_failure_detail\n",
                "from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit\n\nfrom batch_identity import batch_identity_from_payload\nfrom failure_policy import classify_failure, sanitize_failure_detail\n",
                "batch identity import",
            ),
            (
                "    \"concurrentFragments\",\n}\n",
                "    \"concurrentFragments\",\n    \"batchId\",\n    \"batchIndex\",\n    \"batchSize\",\n}\n",
                "retry payload keys",
            ),
            (
                "        result[key] = None if raw is None else _safe_text(raw, 120)\n    if not result.get(\"sourceUrl\"):\n",
                "        result[key] = None if raw is None else _safe_text(raw, 120)\n    batch_id, batch_index, batch_size = batch_identity_from_payload(result)\n    result.pop(\"batchId\", None)\n    result.pop(\"batchIndex\", None)\n    result.pop(\"batchSize\", None)\n    if batch_id is not None:\n        result[\"batchId\"] = batch_id\n        result[\"batchIndex\"] = batch_index\n        result[\"batchSize\"] = batch_size\n    if not result.get(\"sourceUrl\"):\n",
                "sanitize retry identity",
            ),
            (
                "    retry_payload = _safe_retry_payload(value.get(\"retryPayload\"))\n    detail = sanitize_failure_detail(value.get(\"detail\"), 360)\n",
                "    retry_payload = _safe_retry_payload(value.get(\"retryPayload\"))\n    batch_id, batch_index, batch_size = batch_identity_from_payload(retry_payload)\n    detail = sanitize_failure_detail(value.get(\"detail\"), 360)\n",
                "history identity extraction",
            ),
            (
                "        \"collectionMode\": _safe_text(value.get(\"collectionMode\"), 24),\n        \"durationSeconds\": round(duration, 1),\n",
                "        \"collectionMode\": _safe_text(value.get(\"collectionMode\"), 24),\n        \"batchId\": batch_id,\n        \"batchIndex\": batch_index,\n        \"batchSize\": batch_size,\n        \"durationSeconds\": round(duration, 1),\n",
                "history public identity",
            ),
        ],
    )

    update(
        "local-engine/pause_resume_policy.py",
        [
            (
                "from urllib.parse import urlparse\n\nRESUME_STATE_FILENAME",
                "from urllib.parse import urlparse\n\nfrom batch_identity import batch_identity_from_payload\n\nRESUME_STATE_FILENAME",
                "batch identity import",
            ),
            (
                "        source_url = str(payload.get(\"sourceUrl\") or \"\")\n        created_at = _bounded_text(value.get(\"createdAt\"), 40) or _utc_now()\n",
                "        source_url = str(payload.get(\"sourceUrl\") or \"\")\n        batch_id, batch_index, batch_size = batch_identity_from_payload(payload)\n        created_at = _bounded_text(value.get(\"createdAt\"), 40) or _utc_now()\n",
                "resume identity extraction",
            ),
            (
                "            \"videoQuality\": _bounded_text(value.get(\"videoQuality\"), 40),\n            \"progress\": _bounded_progress(value.get(\"progress\")),\n",
                "            \"videoQuality\": _bounded_text(value.get(\"videoQuality\"), 40),\n            \"batchId\": batch_id,\n            \"batchIndex\": batch_index,\n            \"batchSize\": batch_size,\n            \"progress\": _bounded_progress(value.get(\"progress\")),\n",
                "resume stored identity",
            ),
            (
                "                    \"videoQuality\": record[\"videoQuality\"],\n                    \"progress\": record[\"progress\"],\n",
                "                    \"videoQuality\": record[\"videoQuality\"],\n                    \"batchId\": record.get(\"batchId\"),\n                    \"batchIndex\": int(record.get(\"batchIndex\") or 0),\n                    \"batchSize\": int(record.get(\"batchSize\") or 0),\n                    \"progress\": record[\"progress\"],\n",
                "resume public identity",
            ),
        ],
    )

    update(
        "local-engine/entrypoint.py",
        [
            (
                "from batch_input import run_batch_input_self_test\nfrom batch_submission import run_batch_submission_self_test\n",
                "from batch_identity import install_batch_identity_policy, run_batch_identity_self_test\nfrom batch_input import run_batch_input_self_test\nfrom batch_submission import run_batch_submission_self_test\n",
                "identity imports",
            ),
            (
                "install_recovery_policy(engine)\ninstall_pause_resume_policy(engine)\n",
                "install_recovery_policy(engine)\ninstall_batch_identity_policy(engine)\ninstall_pause_resume_policy(engine)\n",
                "identity install order",
            ),
            (
                "    assert getattr(engine, \"_galaxy_recovery_policy_installed\", False) is True\n    assert getattr(engine, \"_galaxy_pause_resume_installed\", False) is True\n",
                "    assert getattr(engine, \"_galaxy_recovery_policy_installed\", False) is True\n    assert getattr(engine, \"_galaxy_batch_identity_installed\", False) is True\n    assert getattr(engine, \"_galaxy_pause_resume_installed\", False) is True\n",
                "identity install assertion",
            ),
            (
                "    run_batch_input_self_test()\n    run_batch_submission_self_test()\n",
                "    run_batch_input_self_test()\n    run_batch_identity_self_test(engine)\n    run_batch_submission_self_test()\n",
                "identity self test",
            ),
        ],
    )

    update(
        "scripts/test-local-job-queue.py",
        [
            (
                "        self.assertEqual(result.remaining_count, 0)\n        self.assertEqual(window.started[-1][\"sourceUrl\"], \"https://example.com/1\")\n",
                "        self.assertEqual(result.remaining_count, 0)\n        self.assertTrue(result.batch_id)\n        self.assertEqual(window.started[-1][\"batchId\"], result.batch_id)\n        self.assertEqual(window.started[-1][\"batchIndex\"], 1)\n        self.assertEqual(window.started[-1][\"batchSize\"], 3)\n        self.assertEqual(window.started[-1][\"sourceUrl\"], \"https://example.com/1\")\n",
                "active batch identity assertions",
            ),
            (
                "        self.assertTrue(all(queued.job[\"videoQuality\"] == \"720p\" for queued in window.pending_jobs))\n",
                "        self.assertTrue(all(queued.job[\"videoQuality\"] == \"720p\" for queued in window.pending_jobs))\n        self.assertEqual([queued.job[\"batchIndex\"] for queued in window.pending_jobs], [2, 3])\n        self.assertTrue(all(queued.job[\"batchId\"] == result.batch_id for queued in window.pending_jobs))\n        queued_status = window.bridge_status()[\"queuedJobs\"]\n        self.assertEqual([item[\"batchIndex\"] for item in queued_status], [2, 3])\n        self.assertTrue(all(item[\"batchId\"] == result.batch_id for item in queued_status))\n",
                "queued batch identity assertions",
            ),
        ],
    )

    update(
        ".github/workflows/ci.yml",
        [
            (
                "            local-engine/bridge_submission_policy.py \\\n            local-engine/archive_policy.py \\\n",
                "            local-engine/bridge_submission_policy.py \\\n            local-engine/batch_identity.py \\\n            local-engine/batch_input.py \\\n            local-engine/batch_submission.py \\\n            local-engine/batch_bridge.py \\\n            local-engine/archive_policy.py \\\n",
                "compile batch modules",
            ),
            (
                "          python3 scripts/test-local-image-bridge.py\n          python3 scripts/test-local-job-queue.py\n",
                "          python3 scripts/test-local-image-bridge.py\n          python3 scripts/test-local-batch-input.py\n          python3 scripts/test-local-batch-submission.py\n          python3 scripts/test-local-batch-bridge.py\n          python3 scripts/test-local-batch-identity.py\n          python3 scripts/test-local-job-queue.py\n",
                "run batch tests",
            ),
        ],
    )


if __name__ == "__main__":
    main()
