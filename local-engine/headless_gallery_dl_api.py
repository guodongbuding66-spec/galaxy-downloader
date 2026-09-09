from __future__ import annotations

import re
import sys
import threading
from pathlib import Path
from typing import Callable

from gallery_dl_executor import (
    MAX_GALLERY_DL_FILES,
    MAX_GALLERY_DL_TASKS,
    GalleryDlExecutor,
    GalleryDlExecutorError,
)
from gallery_dl_manager import existing_managed_gallery_dl, gallery_dl_version
from local_task_provider import LocalTaskProviderRegistry
from managed_tool_actions import (
    ManagedToolActionRequest,
    ManagedToolActionResult,
    perform_managed_tool_action,
)
from platform_paths import PlatformPathError, resolve_platform_paths
from url_policy import PublicUrlError, validated_public_http_url

_ALLOWED_SUBMIT_FIELDS = frozenset({"sourceUrl", "maxFiles"})
_GALLERY_TASK_ID_RE = re.compile(r"^gdl-[a-f0-9]{16}$")
_SAFE_PUBLIC_VALUE_RE = re.compile(r"^[A-Za-z0-9._+!-]{1,128}$")
_TOOL_ACTIONS = frozenset({"check", "install", "update", "remove"})
_TOOL_MUTATIONS = frozenset({"install", "update", "remove"})
_REMOVE_CONFIRMATION = "remove-gallery-dl"
ToolProbe = Callable[[], tuple[bool, str | None]]
ToolActionRunner = Callable[[object, ManagedToolActionRequest], ManagedToolActionResult]


class HeadlessGalleryDlApiError(RuntimeError):
    def __init__(self, message: str, *, status: int = 400, code: str = "GALLERY_DL_INVALID_REQUEST") -> None:
        super().__init__(message)
        self.status = int(status)
        self.code = str(code)


class _HeadlessGalleryDlEngine:
    """Minimal engine/tool context required by the shared gallery-dl executor."""

    def __init__(self, tools_root: Path) -> None:
        self._tools_root = Path(tools_root).resolve(strict=False)

    def tools_dir(self) -> Path:
        return self._tools_root


def _program_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _default_tools_root() -> Path:
    return resolve_platform_paths(program_dir=_program_dir()).tools_dir


def _resolved_tools_root(explicit: Path | None) -> tuple[Path, bool]:
    if explicit is not None:
        return Path(explicit).resolve(strict=False), True
    try:
        return _default_tools_root(), True
    except PlatformPathError:
        return _program_dir(), False


def _public_task(row: dict[str, object]) -> dict[str, object]:
    return {
        "id": str(row.get("providerTaskId") or ""),
        "state": str(row.get("state") or ""),
        "title": str(row.get("label") or ""),
        "provider": "gallery-dl",
        "type": str(row.get("videoQuality") or ""),
        "summary": str(row.get("when") or ""),
        "detail": str(row.get("detail") or ""),
        "advice": str(row.get("advice") or ""),
        "failureLabel": str(row.get("failureLabel") or ""),
        "actions": list(row.get("providerActions") or ()),
    }


def _public_safe_value(value: object, *, fallback: str | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return fallback
    return text if _SAFE_PUBLIC_VALUE_RE.fullmatch(text) else fallback


def _public_tool_action_message(action: str, state: str, ok: bool) -> str:
    if state == "runtime-busy":
        return "gallery-dl tasks are active; stop them before changing the managed tool."
    if state in {"metadata_invalid", "integrity_changed"}:
        return "gallery-dl provenance or integrity requires local review before continuing."
    if ok:
        return {
            "check": "gallery-dl update check completed.",
            "install": "managed gallery-dl install completed.",
            "update": "managed gallery-dl update completed.",
            "remove": "managed gallery-dl removal completed.",
        }.get(action, "gallery-dl tool action completed.")
    return "gallery-dl tool action did not complete; no internal error details were exposed."


def _public_tool_action_result(result: ManagedToolActionResult) -> dict[str, object]:
    action = _public_safe_value(result.action, fallback="unknown") or "unknown"
    state = _public_safe_value(result.state, fallback="error") or "error"
    source = _public_safe_value(result.source, fallback="unknown") or "unknown"
    return {
        "tool": "gallery-dl",
        "action": action,
        "ok": bool(result.ok),
        "changed": bool(result.changed),
        "state": state,
        "source": source,
        "version": _public_safe_value(result.version),
        "availableVersion": _public_safe_value(result.available_version),
        "availableReleaseTag": _public_safe_value(result.available_release_tag),
        "updateAvailable": result.update_available if isinstance(result.update_available, bool) else None,
        "networkAction": bool(result.network_action),
        "message": _public_tool_action_message(action, state, bool(result.ok)),
    }


class HeadlessGalleryDlApi:
    """Authenticated Headless facade over the existing bounded gallery-dl executor."""

    def __init__(
        self,
        download_root: Path,
        *,
        tools_root: Path | None = None,
        executor: GalleryDlExecutor | None = None,
        tool_probe: ToolProbe | None = None,
        tool_action_runner: ToolActionRunner = perform_managed_tool_action,
    ) -> None:
        self.download_root = Path(download_root).resolve(strict=False)
        resolved_tools, self._tool_root_ready = _resolved_tools_root(tools_root)
        self._engine = _HeadlessGalleryDlEngine(resolved_tools)
        self.executor = executor or GalleryDlExecutor(self._engine)
        self._tool_probe = tool_probe or self._managed_tool_status
        self._tool_action_runner = tool_action_runner
        self._registry = LocalTaskProviderRegistry()
        self._closed = False
        self._operation_lock = threading.RLock()
        self._registry.register(
            "gallery-dl",
            label="gallery-dl",
            snapshot=self.executor.snapshots,
            action=self.executor.action,
        )

    def _managed_tool_status(self) -> tuple[bool, str | None]:
        if not self._tool_root_ready:
            return False, None
        root = existing_managed_gallery_dl(self._engine)
        return root is not None, gallery_dl_version(root)

    def _ensure_open(self) -> None:
        if self._closed:
            raise HeadlessGalleryDlApiError(
                "gallery-dl api is closed",
                status=503,
                code="GALLERY_DL_API_CLOSED",
            )

    def status(self) -> dict[str, object]:
        available, version = self._tool_probe()
        return {
            "available": bool(available),
            "acceptingJobs": not self._closed,
            "version": _public_safe_value(version),
            "maxFilesPerJob": MAX_GALLERY_DL_FILES,
            "maxTrackedJobs": MAX_GALLERY_DL_TASKS,
            "supportedActions": ["cancel", "retry"],
            "managedOnly": True,
        }

    def _rows(self) -> list[dict[str, object]]:
        rows = self._registry.rows()
        return [row for row in rows if row.get("providerName") == "gallery-dl"]

    def _tool_mutation_blocked(self) -> bool:
        return any(str(row.get("state") or "") in {"queued", "active"} for row in self._rows())

    def tool_status(self) -> dict[str, object]:
        available, version = self._tool_probe()
        return {
            "installed": bool(available),
            "version": _public_safe_value(version),
            "managedOnly": True,
            "toolRootReady": bool(self._tool_root_ready),
            "supportedActions": ["check", "install", "update", "remove"],
            "mutationBlocked": self._tool_mutation_blocked(),
            "removeConfirmation": _REMOVE_CONFIRMATION,
        }

    @staticmethod
    def _validate_task_id(task_id: object) -> str:
        value = str(task_id or "").strip()
        if not _GALLERY_TASK_ID_RE.fullmatch(value):
            raise HeadlessGalleryDlApiError("invalid gallery-dl job id")
        return value

    def jobs(self, *, limit: int = MAX_GALLERY_DL_TASKS) -> dict[str, object]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > MAX_GALLERY_DL_TASKS:
            raise HeadlessGalleryDlApiError(
                f"gallery-dl job limit must be between 1 and {MAX_GALLERY_DL_TASKS}"
            )
        rows = self._rows()
        selected = list(reversed(rows[-limit:]))
        return {"jobs": [_public_task(row) for row in selected], "count": len(selected)}

    def job(self, task_id: object) -> dict[str, object]:
        clean_id = self._validate_task_id(task_id)
        for row in self._rows():
            if row.get("providerTaskId") == clean_id:
                return {"job": _public_task(row)}
        raise HeadlessGalleryDlApiError(
            "gallery-dl job not found",
            status=404,
            code="GALLERY_DL_JOB_NOT_FOUND",
        )

    def submit(self, payload: object) -> dict[str, object]:
        with self._operation_lock:
            self._ensure_open()
            if not isinstance(payload, dict):
                raise HeadlessGalleryDlApiError("gallery-dl request must be a JSON object")
            unknown = sorted(str(key) for key in payload if key not in _ALLOWED_SUBMIT_FIELDS)
            if unknown:
                raise HeadlessGalleryDlApiError("gallery-dl request contains unsupported fields")
            available, _version = self._tool_probe()
            if not available:
                raise HeadlessGalleryDlApiError(
                    "managed gallery-dl is not installed",
                    status=503,
                    code="GALLERY_DL_UNAVAILABLE",
                )
            try:
                source = validated_public_http_url(str(payload.get("sourceUrl") or ""))
            except PublicUrlError as exc:
                raise HeadlessGalleryDlApiError("a public http(s) sourceUrl is required") from exc
            max_files = payload.get("maxFiles", MAX_GALLERY_DL_FILES)
            if isinstance(max_files, bool) or not isinstance(max_files, int):
                raise HeadlessGalleryDlApiError("maxFiles must be an integer")
            if max_files < 1 or max_files > MAX_GALLERY_DL_FILES:
                raise HeadlessGalleryDlApiError(f"maxFiles must be between 1 and {MAX_GALLERY_DL_FILES}")
            try:
                task_id = self.executor.submit(source, output_root=self.download_root, max_files=max_files)
            except (GalleryDlExecutorError, PublicUrlError) as exc:
                raise HeadlessGalleryDlApiError("gallery-dl request could not be queued") from exc
            return self.job(task_id)

    def action(self, task_id: object, action: object) -> dict[str, object]:
        with self._operation_lock:
            self._ensure_open()
            clean_id = self._validate_task_id(task_id)
            clean_action = str(action or "").strip().lower()
            if clean_action not in {"cancel", "retry"}:
                raise HeadlessGalleryDlApiError("unsupported gallery-dl action")
            current = self.job(clean_id)["job"]
            if clean_action not in current.get("actions", []):
                raise HeadlessGalleryDlApiError(
                    "gallery-dl action is not allowed in the current state",
                    status=409,
                    code="GALLERY_DL_ACTION_CONFLICT",
                )
            result = self._registry.perform_action("gallery-dl", clean_id, clean_action)
            if not result.ok:
                raise HeadlessGalleryDlApiError(
                    "gallery-dl action could not be applied",
                    status=409,
                    code="GALLERY_DL_ACTION_CONFLICT",
                )
            return {"changed": bool(result.changed), "message": result.message, **self.job(clean_id)}

    def _tool_action_impl(self, clean_action: str, payload: object) -> dict[str, object]:
        self._ensure_open()
        if not isinstance(payload, dict):
            raise HeadlessGalleryDlApiError("gallery-dl tool request must be a JSON object")
        allowed_fields = {"confirm"} if clean_action == "remove" else set()
        if any(str(key) not in allowed_fields for key in payload):
            raise HeadlessGalleryDlApiError("gallery-dl tool request contains unsupported fields")
        if clean_action == "remove" and payload.get("confirm") != _REMOVE_CONFIRMATION:
            raise HeadlessGalleryDlApiError(
                "gallery-dl removal requires explicit confirmation",
                status=409,
                code="GALLERY_DL_REMOVE_CONFIRMATION_REQUIRED",
            )
        if not self._tool_root_ready:
            raise HeadlessGalleryDlApiError(
                "gallery-dl tool root is unavailable",
                status=503,
                code="GALLERY_DL_TOOL_ROOT_UNAVAILABLE",
            )
        if clean_action in _TOOL_MUTATIONS and self._tool_mutation_blocked():
            raise HeadlessGalleryDlApiError(
                "gallery-dl tool mutation is blocked while jobs are queued or active",
                status=409,
                code="GALLERY_DL_TOOL_BUSY",
            )
        request = ManagedToolActionRequest(tool="gallery-dl", action=clean_action, user_initiated=True)
        try:
            result = self._tool_action_runner(self._engine, request)
        except Exception as exc:
            raise HeadlessGalleryDlApiError(
                "gallery-dl tool action failed",
                status=502,
                code="GALLERY_DL_TOOL_ACTION_FAILED",
            ) from exc
        if not isinstance(result, ManagedToolActionResult):
            raise HeadlessGalleryDlApiError(
                "gallery-dl tool action returned an invalid result",
                status=502,
                code="GALLERY_DL_TOOL_ACTION_FAILED",
            )
        if result.state == "runtime-busy":
            raise HeadlessGalleryDlApiError(
                "gallery-dl runtime is busy",
                status=409,
                code="GALLERY_DL_TOOL_BUSY",
            )
        return {"result": _public_tool_action_result(result), "tool": self.tool_status()}

    def tool_action(self, action: object, payload: object) -> dict[str, object]:
        clean_action = str(action or "").strip().lower()
        if clean_action not in _TOOL_ACTIONS:
            raise HeadlessGalleryDlApiError("unsupported gallery-dl tool action")
        if clean_action == "check":
            return self._tool_action_impl(clean_action, payload)
        with self._operation_lock:
            return self._tool_action_impl(clean_action, payload)

    def close(self) -> None:
        with self._operation_lock:
            if self._closed:
                return
            self._closed = True
            for row in self._rows():
                actions = tuple(row.get("providerActions") or ())
                task_id = str(row.get("providerTaskId") or "")
                if task_id and "cancel" in actions:
                    self._registry.perform_action("gallery-dl", task_id, "cancel")


def run_headless_gallery_dl_api_self_test() -> None:
    assert _GALLERY_TASK_ID_RE.fullmatch("gdl-0123456789abcdef")
    assert not _GALLERY_TASK_ID_RE.fullmatch("../gdl-0123456789abcdef")
    assert _public_safe_value("1.2.3+build") == "1.2.3+build"
    assert _public_safe_value("/tmp/private") is None
    assert MAX_GALLERY_DL_FILES == 500
    assert MAX_GALLERY_DL_TASKS == 200
