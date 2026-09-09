from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from gallery_dl_executor import GalleryDlExecutorError, MAX_GALLERY_DL_FILES
from resume_bridge import PauseResumeLocalBridge, RESUME_BRIDGE_PROTOCOL_VERSION
from url_policy import PublicUrlError, validated_public_http_url

GALLERY_DL_BRIDGE_PROTOCOL_VERSION = 6
GALLERY_DL_DOWNLOAD_PATH = "/gallery-dl/download"
_ALLOWED_GALLERY_DL_FIELDS = frozenset({"sourceUrl", "maxFiles"})
_GALLERY_DL_TASK_ID_RE = re.compile(r"^gdl-[0-9a-f]{16}$")


@dataclass(frozen=True)
class GalleryDlBridgeResult:
    status: int
    payload: dict[str, Any]


def _error(status: int, code: str, message: str) -> GalleryDlBridgeResult:
    return GalleryDlBridgeResult(
        status,
        {
            "ok": False,
            "accepted": False,
            "code": code,
            "message": message,
        },
    )


def handle_gallery_dl_download_request(
    payload: object,
    submit_gallery_dl_task: Callable[..., str] | None,
    *,
    validator: Callable[[str], str] = validated_public_http_url,
) -> GalleryDlBridgeResult:
    """Validate and submit the browser-triggerable gallery-dl request.

    The bridge deliberately accepts only the public source URL and a bounded
    file-count limit. Output paths, cookies, headers, tool configuration and
    arbitrary gallery-dl arguments remain owned by the local engine.
    """
    if not isinstance(payload, dict):
        return _error(400, "BAD_REQUEST", "JSON object required")

    if any(key not in _ALLOWED_GALLERY_DL_FIELDS for key in payload):
        return _error(400, "BAD_REQUEST", "Unsupported gallery-dl request fields")

    source_value = payload.get("sourceUrl")
    if not isinstance(source_value, str):
        return _error(400, "BAD_REQUEST", "A public HTTP(S) sourceUrl is required")
    try:
        source_url = validator(source_value)
    except (PublicUrlError, ValueError):
        return _error(400, "BAD_SOURCE_URL", "A public HTTP(S) sourceUrl is required")

    raw_limit = payload.get("maxFiles", MAX_GALLERY_DL_FILES)
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
        return _error(400, "BAD_MAX_FILES", f"maxFiles must be an integer from 1 to {MAX_GALLERY_DL_FILES}")
    if raw_limit < 1 or raw_limit > MAX_GALLERY_DL_FILES:
        return _error(400, "BAD_MAX_FILES", f"maxFiles must be an integer from 1 to {MAX_GALLERY_DL_FILES}")

    if not callable(submit_gallery_dl_task):
        return _error(501, "GALLERY_DL_UNAVAILABLE", "This local engine does not expose gallery-dl downloads")

    try:
        task_id = str(submit_gallery_dl_task(source_url, max_files=raw_limit) or "").strip()
    except (PublicUrlError, ValueError):
        return _error(400, "GALLERY_DL_REJECTED", "The gallery-dl task was rejected by the local engine")
    except GalleryDlExecutorError:
        return _error(503, "GALLERY_DL_SUBMIT_FAILED", "The local gallery-dl executor could not prepare the task")
    except Exception:  # noqa: BLE001 - bridge must fail closed without exposing executor internals
        return _error(500, "GALLERY_DL_SUBMIT_FAILED", "The local gallery-dl executor failed to accept the task")

    if _GALLERY_DL_TASK_ID_RE.fullmatch(task_id) is None:
        return _error(500, "INVALID_TASK_ID", "The local gallery-dl executor returned an invalid task id")

    return GalleryDlBridgeResult(
        202,
        {
            "ok": True,
            "accepted": True,
            "code": "GALLERY_DL_ACCEPTED",
            "message": "gallery-dl task accepted",
            "taskId": task_id,
        },
    )


class GalleryDlLocalBridge(PauseResumeLocalBridge):
    """Pause/resume bridge plus one bounded, explicit gallery-dl submit route."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        owner = getattr(self._status_provider, "__self__", None)
        self._submit_gallery_dl_task = getattr(owner, "submit_gallery_dl_task", None)

    def _bridge_protocol_version(self) -> int:
        return GALLERY_DL_BRIDGE_PROTOCOL_VERSION

    def _extra_status_payload(self) -> dict[str, Any]:
        return {
            "galleryDlBridgeReady": callable(self._submit_gallery_dl_task),
            "galleryDlMaxFiles": MAX_GALLERY_DL_FILES,
        }

    def _handle_extension_post(self, handler: Any) -> bool:
        if getattr(handler, "path", "") != GALLERY_DL_DOWNLOAD_PATH:
            return False
        payload = handler._read_json()
        if payload is None:
            return True
        result = handle_gallery_dl_download_request(payload, self._submit_gallery_dl_task)
        handler._json(result.status, result.payload)
        return True


def install_gallery_dl_bridge(engine_module):
    engine_module.LocalBridge = GalleryDlLocalBridge
    engine_module._galaxy_gallery_dl_bridge_installed = True
    return GalleryDlLocalBridge


def run_gallery_dl_bridge_self_test() -> None:
    assert GALLERY_DL_BRIDGE_PROTOCOL_VERSION > RESUME_BRIDGE_PROTOCOL_VERSION

    calls: list[tuple[str, int]] = []

    def submit(source_url: str, *, max_files: int) -> str:
        calls.append((source_url, max_files))
        return "gdl-0123456789abcdef"

    ok = handle_gallery_dl_download_request(
        {"sourceUrl": "https://1.1.1.1/gallery", "maxFiles": 25},
        submit,
    )
    assert ok.status == 202
    assert ok.payload["taskId"] == "gdl-0123456789abcdef"
    assert calls == [("https://1.1.1.1/gallery", 25)]

    assert handle_gallery_dl_download_request(
        {"sourceUrl": "http://127.0.0.1/private"}, submit
    ).payload["code"] == "BAD_SOURCE_URL"
    assert handle_gallery_dl_download_request(
        {"sourceUrl": "https://1.1.1.1/gallery", "maxFiles": 0}, submit
    ).payload["code"] == "BAD_MAX_FILES"
    assert handle_gallery_dl_download_request(
        {"sourceUrl": "https://1.1.1.1/gallery", "maxFiles": 501}, submit
    ).payload["code"] == "BAD_MAX_FILES"
    assert handle_gallery_dl_download_request(
        {"sourceUrl": "https://1.1.1.1/gallery", "maxFiles": True}, submit
    ).payload["code"] == "BAD_MAX_FILES"
    assert handle_gallery_dl_download_request(
        {"sourceUrl": "https://1.1.1.1/gallery", "outputPath": "/tmp/escape"}, submit
    ).payload["code"] == "BAD_REQUEST"
    assert handle_gallery_dl_download_request(
        {"sourceUrl": "https://1.1.1.1/gallery", "headers": {"Cookie": "secret"}}, submit
    ).payload["code"] == "BAD_REQUEST"
    assert handle_gallery_dl_download_request(
        {"sourceUrl": "https://1.1.1.1/gallery"}, None
    ).payload["code"] == "GALLERY_DL_UNAVAILABLE"

    def unavailable_submit(_source_url: str, *, max_files: int) -> str:
        assert max_files == MAX_GALLERY_DL_FILES
        raise GalleryDlExecutorError("private local path detail must not escape")

    unavailable = handle_gallery_dl_download_request(
        {"sourceUrl": "https://1.1.1.1/gallery"}, unavailable_submit
    )
    assert unavailable.status == 503
    assert unavailable.payload["code"] == "GALLERY_DL_SUBMIT_FAILED"
    assert "private local path" not in unavailable.payload["message"]

    def invalid_submit(_source_url: str, *, max_files: int) -> str:
        assert max_files == MAX_GALLERY_DL_FILES
        return "bad\nvalue"

    invalid = handle_gallery_dl_download_request(
        {"sourceUrl": "https://1.1.1.1/gallery"}, invalid_submit
    )
    assert invalid.status == 500
    assert invalid.payload["code"] == "INVALID_TASK_ID"

    class Owner:
        def status(self) -> dict[str, Any]:
            return {"busy": False, "resumeJobs": []}

        def submit_gallery_dl_task(self, source_url: str, *, max_files: int = MAX_GALLERY_DL_FILES) -> str:
            return submit(source_url, max_files=max_files)

    owner = Owner()
    bridge = GalleryDlLocalBridge(
        status_provider=owner.status,
        submit_job=lambda _payload: (True, "ok"),
        cancel_job=lambda: None,
        open_folder=lambda: None,
    )
    assert bridge._bridge_protocol_version() == GALLERY_DL_BRIDGE_PROTOCOL_VERSION
    status = bridge._extra_status_payload()
    assert status == {"galleryDlBridgeReady": True, "galleryDlMaxFiles": MAX_GALLERY_DL_FILES}

    class Handler:
        path = GALLERY_DL_DOWNLOAD_PATH

        def __init__(self) -> None:
            self.response: tuple[int, dict[str, Any]] | None = None

        def _read_json(self) -> dict[str, Any]:
            return {"sourceUrl": "https://1.1.1.1/route", "maxFiles": 7}

        def _json(self, status_code: int, payload: dict[str, Any]) -> None:
            self.response = (status_code, payload)

    handler = Handler()
    assert bridge._handle_extension_post(handler) is True
    assert handler.response is not None
    assert handler.response[0] == 202
    assert handler.response[1]["code"] == "GALLERY_DL_ACCEPTED"

    handler.path = "/download"
    handler.response = None
    assert bridge._handle_extension_post(handler) is False
    assert handler.response is None
