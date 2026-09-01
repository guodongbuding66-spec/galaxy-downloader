from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterator

import bridge as base_bridge


@dataclass(frozen=True)
class JobSubmissionResult:
    accepted: bool
    message: str
    status: int
    code: str

    def __iter__(self) -> Iterator[object]:
        # Keep compatibility with older callers/tests that unpacked the original
        # two-item ``(accepted, message)`` callback result.
        yield self.accepted
        yield self.message


@dataclass(frozen=True)
class QueueCancellationResult:
    cancelled: bool
    message: str
    status: int
    code: str


def normalize_submission_result(value: object) -> JobSubmissionResult:
    if isinstance(value, JobSubmissionResult):
        return value

    if isinstance(value, tuple) and len(value) >= 2:
        accepted = bool(value[0])
        message = str(value[1])
        if len(value) >= 4:
            try:
                status = int(value[2])
            except (TypeError, ValueError):
                status = 202 if accepted else 409
            code = str(value[3]) or ("ACCEPTED" if accepted else "ENGINE_BUSY")
            return JobSubmissionResult(accepted, message, status, code)
        return JobSubmissionResult(
            accepted,
            message,
            202 if accepted else 409,
            "ACCEPTED" if accepted else "ENGINE_BUSY",
        )

    return JobSubmissionResult(
        False,
        "Local engine returned an invalid job submission result",
        500,
        "INTERNAL_ERROR",
    )


class StructuredLocalBridge(base_bridge.LocalBridge):
    """Local bridge variant with stable HTTP status/code semantics.

    Queue cancellation is discovered from the bound status provider when the
    queue-enabled EngineWindow is installed. This keeps the legacy LocalBridge
    constructor compatible while allowing 0.8.0 to add queue controls without
    changing older non-queue callers.
    """

    def __init__(
        self,
        *,
        status_provider: Callable[[], dict[str, Any]],
        submit_job: Callable[[dict[str, Any]], object],
        cancel_job: Callable[[], None],
        open_folder: Callable[[], None],
        cancel_queued_job: Callable[[str], QueueCancellationResult] | None = None,
    ) -> None:
        super().__init__(
            status_provider=status_provider,
            submit_job=submit_job,
            cancel_job=cancel_job,
            open_folder=open_folder,
        )
        owner = getattr(status_provider, "__self__", None)
        discovered = getattr(owner, "cancel_queued_job_from_bridge", None)
        self._cancel_queued_job = cancel_queued_job or (discovered if callable(discovered) else None)

    def start(self) -> None:
        if self._server is not None:
            return

        local_bridge = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "GalaxyLocalBridge/4"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _origin(self) -> str | None:
                return self.headers.get("Origin")

            def _write_cors_headers(self) -> None:
                origin = self._origin()
                if origin and base_bridge._origin_allowed(origin):
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Cache-Control", "no-store")

            def _json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self._write_cors_headers()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _reject_origin(self) -> bool:
                if base_bridge._origin_allowed(self._origin()):
                    return False
                self._json(403, {"ok": False, "code": "ORIGIN_NOT_ALLOWED", "error": "Origin is not allowed"})
                return True

            def do_OPTIONS(self) -> None:  # noqa: N802
                if self._reject_origin():
                    return
                self.send_response(204)
                self._write_cors_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self._reject_origin():
                    return
                if self.path not in {"/health", "/status"}:
                    self._json(404, {"ok": False, "code": "NOT_FOUND", "error": "Not found"})
                    return
                payload = local_bridge._status_provider()
                self._json(
                    200,
                    {
                        "ok": True,
                        "bridgeProtocol": base_bridge.BRIDGE_PROTOCOL_VERSION,
                        **payload,
                    },
                )

            def _read_json(self) -> dict[str, Any] | None:
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

            def _cancel_queued(self) -> None:
                payload = self._read_json()
                if payload is None:
                    return
                job_id = str(payload.get("jobId") or "").strip()
                if not job_id or len(job_id) > 128 or not job_id.isalnum():
                    self._json(400, {"ok": False, "code": "BAD_REQUEST", "error": "Valid queue jobId required"})
                    return
                if local_bridge._cancel_queued_job is None:
                    self._json(
                        501,
                        {
                            "ok": False,
                            "code": "QUEUE_CONTROL_UNAVAILABLE",
                            "error": "This local engine does not expose queue item controls",
                        },
                    )
                    return
                result = local_bridge._cancel_queued_job(job_id)
                self._json(
                    result.status,
                    {
                        "ok": result.cancelled,
                        "cancelled": result.cancelled,
                        "code": result.code,
                        "message": result.message,
                        "jobId": job_id,
                    },
                )

            def do_POST(self) -> None:  # noqa: N802
                if self._reject_origin():
                    return
                if self.path == "/parse":
                    payload = self._read_json()
                    if payload is None:
                        return
                    source_url = str(payload.get("url") or "").strip()
                    browser = base_bridge._validated_browser(payload.get("browser"))
                    result = base_bridge.parse_with_bundled_ytdlp(source_url, browser)
                    self._json(
                        int(result.get("status") or (200 if result.get("success") else 502)),
                        result,
                    )
                    return
                if self.path == "/download":
                    payload = self._read_json()
                    if payload is None:
                        return
                    submission = normalize_submission_result(local_bridge._submit_job(payload))
                    self._json(
                        submission.status,
                        {
                            "ok": submission.accepted,
                            "accepted": submission.accepted,
                            "code": submission.code,
                            "message": submission.message,
                        },
                    )
                    return
                if self.path == "/queue/cancel":
                    self._cancel_queued()
                    return
                if self.path == "/cancel":
                    local_bridge._cancel_job()
                    self._json(200, {"ok": True})
                    return
                if self.path == "/open-folder":
                    local_bridge._open_folder()
                    self._json(200, {"ok": True})
                    return
                self._json(404, {"ok": False, "code": "NOT_FOUND", "error": "Not found"})

        self._server = ThreadingHTTPServer((base_bridge.BRIDGE_HOST, base_bridge.BRIDGE_PORT), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="GalaxyLocalBridge",
            daemon=True,
        )
        self._thread.start()
