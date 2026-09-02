from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

import bridge as base_bridge
from batch_bridge import MAX_BATCH_BRIDGE_REQUEST_BYTES, handle_batch_download_request, run_batch_bridge_self_test
from bridge_submission_policy import StructuredLocalBridge, normalize_submission_result

RESUME_BRIDGE_PROTOCOL_VERSION = 5


class PauseResumeLocalBridge(StructuredLocalBridge):
    """Structured bridge with thread-safe active pause/restart recovery controls.

    HTTP handlers run on ThreadingHTTPServer worker threads. Tk must only be
    touched by the desktop main thread, so every pause/resume/discard operation
    is marshalled through the EngineWindow ``after`` queue before returning an
    HTTP result.
    """

    def __init__(
        self,
        *,
        status_provider: Callable[[], dict[str, Any]],
        submit_job: Callable[[dict[str, Any]], object],
        cancel_job: Callable[[], None],
        open_folder: Callable[[], None],
        cancel_queued_job=None,
    ) -> None:
        super().__init__(
            status_provider=status_provider,
            submit_job=submit_job,
            cancel_job=cancel_job,
            open_folder=open_folder,
            cancel_queued_job=cancel_queued_job,
        )
        owner = getattr(status_provider, "__self__", None)
        self._control_owner = owner
        self._pause_active_job = getattr(owner, "pause_active_job", None)
        self._resume_job = getattr(owner, "resume_job", None)
        self._discard_resume_job = getattr(owner, "discard_resume_job", None)
        self._submit_batch_jobs = getattr(owner, "submit_batch_jobs_from_bridge", None)

    def _invoke_owner(self, callback, *args: object) -> tuple[bool, int, str, str]:
        if not callable(callback) or self._control_owner is None:
            return False, 501, "RESUME_CONTROL_UNAVAILABLE", "This local engine does not expose pause/resume controls"

        completed = threading.Event()
        result: dict[str, object] = {
            "ok": False,
            "status": 409,
            "code": "CONTROL_REJECTED",
            "message": "The requested local engine control was rejected",
        }

        def invoke() -> None:
            try:
                result["ok"] = bool(callback(*args))
            except Exception as exc:  # noqa: BLE001
                result.update(
                    ok=False,
                    status=500,
                    code="CONTROL_FAILED",
                    message=f"Local engine control failed: {exc}",
                )
            finally:
                completed.set()

        try:
            self._control_owner.after(0, invoke)
        except Exception as exc:  # noqa: BLE001
            return False, 503, "ENGINE_SHUTTING_DOWN", f"Desktop window is unavailable: {exc}"

        if not completed.wait(timeout=2.0):
            return False, 504, "ENGINE_HANDOFF_TIMEOUT", "Timed out while handing the control to the desktop window"
        return (
            bool(result["ok"]),
            int(result["status"]),
            str(result["code"]),
            str(result["message"]),
        )

    @staticmethod
    def _valid_job_id(value: object) -> str | None:
        job_id = str(value or "").strip()
        if not job_id or len(job_id) > 128 or not job_id.isalnum():
            return None
        return job_id

    def _pause_result(self) -> tuple[bool, int, str, str]:
        status = self._status_provider()
        if not bool(status.get("busy")) or not bool(status.get("canPause", False)):
            return False, 409, "NO_PAUSABLE_JOB", "There is no active download that can be paused"
        ok, raw_status, raw_code, raw_message = self._invoke_owner(self._pause_active_job)
        if not ok:
            return ok, raw_status, raw_code, raw_message
        return True, 202, "PAUSE_REQUESTED", "Active download is stopping at a resumable checkpoint"

    def _resume_result(self, job_id: str) -> tuple[bool, int, str, str]:
        status = self._status_provider()
        if bool(status.get("busy")):
            return False, 409, "ENGINE_BUSY", "Another download is already active"
        known = {
            str(item.get("id") or "")
            for item in status.get("resumeJobs", [])
            if isinstance(item, dict)
        }
        if job_id not in known:
            return False, 404, "RESUME_JOB_NOT_FOUND", "Recoverable download was not found"
        ok, raw_status, raw_code, raw_message = self._invoke_owner(self._resume_job, job_id)
        if not ok:
            return ok, raw_status, raw_code, raw_message
        return True, 202, "RESUME_STARTED", "Recoverable download has been started"

    def _discard_result(self, job_id: str) -> tuple[bool, int, str, str]:
        status = self._status_provider()
        active_id = str(status.get("activeJobId") or "")
        if active_id == job_id and bool(status.get("busy")):
            return False, 409, "RESUME_JOB_ACTIVE", "The active download cannot be discarded while it is running"
        known = {
            str(item.get("id") or "")
            for item in status.get("resumeJobs", [])
            if isinstance(item, dict)
        }
        if job_id not in known:
            return False, 404, "RESUME_JOB_NOT_FOUND", "Recoverable download was not found"
        ok, raw_status, raw_code, raw_message = self._invoke_owner(self._discard_resume_job, job_id)
        if not ok:
            return ok, raw_status, raw_code, raw_message
        return True, 200, "RESUME_JOB_DISCARDED", "Recoverable download state was discarded"

    def start(self) -> None:
        if self._server is not None:
            return

        local_bridge = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "GalaxyLocalBridge/5"

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
                self._json(200, {"ok": True, "bridgeProtocol": RESUME_BRIDGE_PROTOCOL_VERSION, **payload, "batchDownloadReady": callable(local_bridge._submit_batch_jobs)})

            def _read_json(
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

            def _job_id_payload(self) -> str | None:
                payload = self._read_json()
                if payload is None:
                    return None
                job_id = local_bridge._valid_job_id(payload.get("jobId"))
                if job_id is None:
                    self._json(400, {"ok": False, "code": "BAD_REQUEST", "error": "Valid jobId required"})
                    return None
                return job_id

            def _write_control(self, result: tuple[bool, int, str, str], *, job_id: str | None = None) -> None:
                ok, status, code, message = result
                payload: dict[str, Any] = {"ok": ok, "code": code, "message": message}
                if job_id:
                    payload["jobId"] = job_id
                self._json(status, payload)

            def _cancel_queued(self) -> None:
                payload = self._read_json()
                if payload is None:
                    return
                job_id = local_bridge._valid_job_id(payload.get("jobId"))
                if job_id is None:
                    self._json(400, {"ok": False, "code": "BAD_REQUEST", "error": "Valid queue jobId required"})
                    return
                if local_bridge._cancel_queued_job is None:
                    self._json(501, {"ok": False, "code": "QUEUE_CONTROL_UNAVAILABLE", "error": "This local engine does not expose queue item controls"})
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
                    self._json(int(result.get("status") or (200 if result.get("success") else 502)), result)
                    return
                if self.path == "/batch/download":
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
                if self.path == "/queue/cancel":
                    self._cancel_queued()
                    return
                if self.path == "/pause":
                    self._write_control(local_bridge._pause_result())
                    return
                if self.path == "/resume":
                    job_id = self._job_id_payload()
                    if job_id is not None:
                        self._write_control(local_bridge._resume_result(job_id), job_id=job_id)
                    return
                if self.path == "/resume/discard":
                    job_id = self._job_id_payload()
                    if job_id is not None:
                        self._write_control(local_bridge._discard_result(job_id), job_id=job_id)
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
        self._thread = threading.Thread(target=self._server.serve_forever, name="GalaxyLocalBridge", daemon=True)
        self._thread.start()


def install_resume_bridge(engine_module):
    """Install the 0.15 control bridge after the queue selected its bridge type."""
    engine_module.LocalBridge = PauseResumeLocalBridge
    engine_module._galaxy_resume_bridge_installed = True
    return PauseResumeLocalBridge


def run_resume_bridge_self_test() -> None:
    class Owner:
        def __init__(self) -> None:
            self.running = True
            self.records = {"abc123"}
            self.paused = 0
            self.resumed = ""
            self.discarded = ""
            self.batch_calls = 0

        def after(self, _delay: int, callback) -> None:
            callback()

        def status(self) -> dict[str, Any]:
            return {
                "busy": self.running,
                "canPause": self.running,
                "activeJobId": "active" if self.running else None,
                "resumeJobs": [{"id": value} for value in sorted(self.records)],
            }

        def pause_active_job(self) -> bool:
            self.paused += 1
            self.running = False
            return True

        def resume_job(self, job_id: str) -> bool:
            if self.running or job_id not in self.records:
                return False
            self.resumed = job_id
            self.running = True
            return True

        def discard_resume_job(self, job_id: str) -> bool:
            if job_id not in self.records:
                return False
            self.records.remove(job_id)
            self.discarded = job_id
            return True

        def submit_batch_jobs_from_bridge(self, _batch, _options):
            self.batch_calls += 1
            raise AssertionError("route callback is not exercised by this embedded discovery test")

    assert RESUME_BRIDGE_PROTOCOL_VERSION > base_bridge.BRIDGE_PROTOCOL_VERSION
    owner = Owner()
    bridge = PauseResumeLocalBridge(
        status_provider=owner.status,
        submit_job=lambda _payload: (True, "ok"),
        cancel_job=lambda: None,
        open_folder=lambda: None,
    )
    paused = bridge._pause_result()
    assert paused[:3] == (True, 202, "PAUSE_REQUESTED")
    resumed = bridge._resume_result("abc123")
    assert resumed[:3] == (True, 202, "RESUME_STARTED")
    owner.running = False
    discarded = bridge._discard_result("abc123")
    assert discarded[:3] == (True, 200, "RESUME_JOB_DISCARDED")
    assert bridge._resume_result("missing")[1:3] == (404, "RESUME_JOB_NOT_FOUND")
    assert bridge._submit_batch_jobs is not None
    run_batch_bridge_self_test()
