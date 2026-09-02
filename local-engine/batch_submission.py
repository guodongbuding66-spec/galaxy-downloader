from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from batch_input import BatchInputItem, BatchInputResult
from bridge_submission_policy import JobSubmissionResult, normalize_submission_result

_TERMINAL_SUBMISSION_CODES = {
    "ENGINE_BUSY",
    "ENGINE_HANDOFF_TIMEOUT",
    "ENGINE_SHUTTING_DOWN",
    "INTERNAL_ERROR",
    "QUEUE_FULL",
}


@dataclass(frozen=True)
class BatchSubmissionItemResult:
    row: int
    accepted: bool
    status: int
    code: str


@dataclass(frozen=True)
class BatchSubmissionResult:
    source_format: str
    input_count: int
    input_issue_count: int
    outcomes: tuple[BatchSubmissionItemResult, ...]
    remaining_count: int
    stopped_code: str | None = None

    @property
    def attempted_count(self) -> int:
        return len(self.outcomes)

    @property
    def accepted_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.accepted)

    @property
    def rejected_count(self) -> int:
        return self.attempted_count - self.accepted_count

    @property
    def started_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.accepted and outcome.code == "ACCEPTED")

    @property
    def queued_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.accepted and outcome.code == "QUEUED")

    @property
    def stopped(self) -> bool:
        return self.stopped_code is not None


def _payload_for_item(base_payload: dict[str, Any], item: BatchInputItem) -> dict[str, Any]:
    payload = dict(base_payload)
    # Never let a stale single-download URL/title from the template override the
    # exact row the user reviewed in the batch preview.
    payload["sourceUrl"] = item.source_url
    if item.display_title:
        payload["displayTitle"] = item.display_title
    else:
        payload.pop("displayTitle", None)
    return payload


def _safe_submit(submit_one: Callable[[dict[str, Any]], object], payload: dict[str, Any]) -> JobSubmissionResult:
    try:
        return normalize_submission_result(submit_one(payload))
    except Exception:
        # Batch summaries are intentionally URL-free. Do not copy exception text
        # because downstream libraries may include a signed URL in an error.
        return JobSubmissionResult(
            False,
            "Batch submission callback failed",
            500,
            "INTERNAL_ERROR",
        )


def _is_terminal_failure(submission: JobSubmissionResult) -> bool:
    if submission.accepted:
        return False
    return submission.code in _TERMINAL_SUBMISSION_CODES or submission.status >= 500


def submit_batch_input_result(
    batch: BatchInputResult,
    base_payload: dict[str, Any],
    submit_one: Callable[[dict[str, Any]], object],
) -> BatchSubmissionResult:
    """Submit reviewed batch items through the existing single-job contract.

    This controller owns no queue and starts no worker. Every item is converted
    into the same payload used by `/download` and handed to `submit_one`, so the
    existing Job normalization, DNS-aware public URL boundary and scheduler are
    still authoritative.

    Per-item BAD_REQUEST failures do not poison the batch. Capacity/shutdown/
    handoff failures stop further submissions because repeating those calls can
    only add load while the engine cannot accept more work.

    The returned result deliberately contains row numbers and stable status/code
    fields only. Full source URLs remain in the input object and callback payload,
    never in the batch summary.
    """
    if not isinstance(batch, BatchInputResult):
        raise TypeError("batch must be a BatchInputResult")
    if not isinstance(base_payload, dict):
        raise TypeError("base_payload must be a dict")
    if not callable(submit_one):
        raise TypeError("submit_one must be callable")

    outcomes: list[BatchSubmissionItemResult] = []
    stopped_code: str | None = None

    for item in batch.items:
        payload = _payload_for_item(base_payload, item)
        submission = _safe_submit(submit_one, payload)
        outcomes.append(
            BatchSubmissionItemResult(
                row=item.row,
                accepted=bool(submission.accepted),
                status=int(submission.status),
                code=str(submission.code or "INTERNAL_ERROR"),
            )
        )
        if _is_terminal_failure(submission):
            stopped_code = str(submission.code or "INTERNAL_ERROR")
            break

    attempted = len(outcomes)
    return BatchSubmissionResult(
        source_format=batch.format,
        input_count=len(batch.items),
        input_issue_count=len(batch.issues),
        outcomes=tuple(outcomes),
        remaining_count=max(0, len(batch.items) - attempted),
        stopped_code=stopped_code,
    )


def run_batch_submission_self_test() -> None:
    from batch_input import parse_batch_input

    batch = parse_batch_input(
        "https://example.com/a?token=private-token\n"
        "https://example.com/a?token=private-token\n"
        "https://example.com/c\n",
        format_hint="txt",
    )
    seen: list[dict[str, Any]] = []

    def accept(payload: dict[str, Any]) -> JobSubmissionResult:
        seen.append(dict(payload))
        if len(seen) == 1:
            return JobSubmissionResult(True, "accepted", 202, "ACCEPTED")
        if len(seen) == 2:
            return JobSubmissionResult(False, "bad request", 400, "BAD_REQUEST")
        return JobSubmissionResult(True, "queued", 202, "QUEUED")

    result = submit_batch_input_result(
        batch,
        {"videoQuality": "1080p", "sourceUrl": "https://stale.invalid", "displayTitle": "stale"},
        accept,
    )
    assert [payload["sourceUrl"] for payload in seen] == [item.source_url for item in batch.items]
    assert all(payload["videoQuality"] == "1080p" for payload in seen)
    assert all("displayTitle" not in payload for payload in seen)
    assert result.attempted_count == 3
    assert result.accepted_count == 2
    assert result.rejected_count == 1
    assert result.started_count == 1
    assert result.queued_count == 1
    assert result.remaining_count == 0
    assert result.stopped is False
    assert "private-token" not in repr(result)

    terminal_calls = 0

    def full(_payload: dict[str, Any]) -> JobSubmissionResult:
        nonlocal terminal_calls
        terminal_calls += 1
        return JobSubmissionResult(False, "queue full", 409, "QUEUE_FULL")

    stopped = submit_batch_input_result(batch, {}, full)
    assert terminal_calls == 1
    assert stopped.attempted_count == 1
    assert stopped.remaining_count == 2
    assert stopped.stopped_code == "QUEUE_FULL"
