from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from batch_input import MAX_BATCH_INPUT_CHARS, BatchInputIssue, parse_batch_input
from batch_submission import BatchSubmissionResult

# JSON is UTF-8 on the wire while Batch Input's canonical bound is measured in
# Python characters. Allow the worst-case four-byte UTF-8 representation plus a
# small envelope for JSON keys and download options. Ordinary bridge routes keep
# their existing 32 KiB limit.
MAX_BATCH_BRIDGE_REQUEST_BYTES = MAX_BATCH_INPUT_CHARS * 4 + 64 * 1024


@dataclass(frozen=True)
class BatchBridgeResponse:
    status: int
    payload: dict[str, Any]


def _issue_payload(issue: BatchInputIssue) -> dict[str, Any]:
    return {
        "row": int(issue.row),
        "code": str(issue.code),
        "message": str(issue.message),
    }


def _submission_payload(result: BatchSubmissionResult) -> dict[str, Any]:
    return {
        "format": result.source_format,
        "inputCount": result.input_count,
        "inputIssueCount": result.input_issue_count,
        "attemptedCount": result.attempted_count,
        "acceptedCount": result.accepted_count,
        "rejectedCount": result.rejected_count,
        "startedCount": result.started_count,
        "queuedCount": result.queued_count,
        "remainingCount": result.remaining_count,
        "stoppedCode": result.stopped_code,
        "outcomes": [
            {
                "row": outcome.row,
                "accepted": outcome.accepted,
                "status": outcome.status,
                "code": outcome.code,
            }
            for outcome in result.outcomes
        ],
    }


def _terminal_http_status(result: BatchSubmissionResult) -> int:
    if not result.outcomes:
        return 400
    last = result.outcomes[-1]
    if last.accepted:
        return 202
    status = int(last.status)
    if 400 <= status <= 599:
        return status
    return 500


def handle_batch_download_request(
    request: object,
    submit_batch: Callable[[Any, dict[str, Any]], BatchSubmissionResult] | None,
) -> BatchBridgeResponse:
    """Validate one loopback batch request and project a URL-free response.

    The request carries raw TXT/CSV input plus a base single-download options
    object. Parsing is canonicalized in Python; final DNS-aware URL validation
    and queue admission remain inside the existing batch submission callback.
    """
    if not isinstance(request, dict):
        return BatchBridgeResponse(
            400,
            {"ok": False, "code": "BAD_REQUEST", "error": "JSON object required"},
        )

    raw_input = request.get("input")
    if not isinstance(raw_input, str):
        return BatchBridgeResponse(
            400,
            {"ok": False, "code": "BAD_REQUEST", "error": "Batch input must be a string"},
        )

    raw_format = request.get("format", "auto")
    if not isinstance(raw_format, str):
        return BatchBridgeResponse(
            400,
            {"ok": False, "code": "BAD_REQUEST", "error": "Batch format must be auto, txt or csv"},
        )
    format_hint = raw_format.strip().lower() or "auto"
    if format_hint not in {"auto", "txt", "csv"}:
        return BatchBridgeResponse(
            400,
            {"ok": False, "code": "BAD_REQUEST", "error": "Batch format must be auto, txt or csv"},
        )

    options = request.get("options", {})
    if not isinstance(options, dict):
        return BatchBridgeResponse(
            400,
            {"ok": False, "code": "BAD_REQUEST", "error": "Batch options must be a JSON object"},
        )

    batch = parse_batch_input(raw_input, format_hint=format_hint)
    issues = [_issue_payload(issue) for issue in batch.issues]
    if not batch.items:
        code = "BATCH_INVALID_INPUT" if issues else "BATCH_EMPTY"
        return BatchBridgeResponse(
            400,
            {
                "ok": False,
                "code": code,
                "format": batch.format,
                "inputCount": 0,
                "inputIssueCount": len(issues),
                "attemptedCount": 0,
                "acceptedCount": 0,
                "rejectedCount": 0,
                "startedCount": 0,
                "queuedCount": 0,
                "remainingCount": 0,
                "stoppedCode": None,
                "issues": issues,
                "outcomes": [],
            },
        )

    if not callable(submit_batch):
        return BatchBridgeResponse(
            501,
            {
                "ok": False,
                "code": "BATCH_CONTROL_UNAVAILABLE",
                "error": "This local engine does not expose batch submission controls",
                "format": batch.format,
                "inputCount": len(batch.items),
                "inputIssueCount": len(issues),
                "issues": issues,
            },
        )

    try:
        submission = submit_batch(batch, dict(options))
    except Exception:
        # Never copy exception text: downstream validation/download code may put
        # a signed source URL into its exception message.
        return BatchBridgeResponse(
            500,
            {
                "ok": False,
                "code": "BATCH_CONTROL_FAILED",
                "error": "Batch submission failed inside the local engine",
                "format": batch.format,
                "inputCount": len(batch.items),
                "inputIssueCount": len(issues),
                "issues": issues,
            },
        )

    if not isinstance(submission, BatchSubmissionResult):
        return BatchBridgeResponse(
            500,
            {
                "ok": False,
                "code": "BATCH_CONTROL_FAILED",
                "error": "Batch submission returned an invalid result",
                "format": batch.format,
                "inputCount": len(batch.items),
                "inputIssueCount": len(issues),
                "issues": issues,
            },
        )

    projected = _submission_payload(submission)
    projected["issues"] = issues

    if submission.accepted_count > 0:
        partial = bool(
            issues
            or submission.rejected_count
            or submission.remaining_count
            or submission.stopped_code
        )
        return BatchBridgeResponse(
            202,
            {
                "ok": True,
                "code": "BATCH_PARTIAL" if partial else "BATCH_ACCEPTED",
                **projected,
            },
        )

    if submission.stopped:
        return BatchBridgeResponse(
            _terminal_http_status(submission),
            {"ok": False, "code": "BATCH_STOPPED", **projected},
        )

    return BatchBridgeResponse(
        400,
        {"ok": False, "code": "BATCH_REJECTED", **projected},
    )


def run_batch_bridge_self_test() -> None:
    from batch_submission import submit_batch_input_result
    from bridge_submission_policy import JobSubmissionResult

    request = {
        "input": (
            "https://example.com/one?token=private-token\n"
            "not-a-url\n"
            "https://example.com/two\n"
        ),
        "format": "txt",
        "options": {"videoQuality": "1080p"},
    }
    seen: list[dict[str, Any]] = []

    def submit_batch(batch, options):
        def submit_one(payload):
            seen.append(dict(payload))
            return JobSubmissionResult(
                True,
                "accepted" if len(seen) == 1 else "queued",
                202,
                "ACCEPTED" if len(seen) == 1 else "QUEUED",
            )

        return submit_batch_input_result(batch, options, submit_one)

    response = handle_batch_download_request(request, submit_batch)
    assert response.status == 202
    assert response.payload["ok"] is True
    assert response.payload["code"] == "BATCH_PARTIAL"
    assert response.payload["acceptedCount"] == 2
    assert response.payload["inputIssueCount"] == 1
    assert [item["code"] for item in response.payload["outcomes"]] == ["ACCEPTED", "QUEUED"]
    assert seen[0]["videoQuality"] == "1080p"
    assert "private-token" not in repr(response.payload)
    assert "sourceUrl" not in repr(response.payload)

    full_calls = 0

    def queue_full(batch, options):
        nonlocal full_calls

        def submit_one(_payload):
            nonlocal full_calls
            full_calls += 1
            return JobSubmissionResult(False, "full", 409, "QUEUE_FULL")

        return submit_batch_input_result(batch, options, submit_one)

    stopped = handle_batch_download_request(
        {"input": "https://example.com/a\nhttps://example.com/b\n"},
        queue_full,
    )
    assert stopped.status == 409
    assert stopped.payload["code"] == "BATCH_STOPPED"
    assert stopped.payload["stoppedCode"] == "QUEUE_FULL"
    assert stopped.payload["remainingCount"] == 1
    assert full_calls == 1
