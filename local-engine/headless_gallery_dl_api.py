from __future__ import annotations

import re
import sys
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
from platform_paths import resolve_platform_paths
from url_policy import PublicUrlError, validated_public_http_url

_ALLOWED_SUBMIT_FIELDS = frozenset({"sourceUrl", "maxFiles"})
_GALLERY_TASK_ID_RE = re.compile(r"^gdl-[a-f0-9]{16}$")
ToolProbe = Callable[[], tuple[bool, str | None]]


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


class HeadlessGalleryDlApi:
    """Authenticated Headless facade over the existing bounded gallery-dl executor."""

    def __init__(
        self,
        download_root: Path,
        *,
        tools_root: Path | None = None,
        executor: GalleryDlExecutor | None = None,
        tool_probe: ToolProbe | None = None,
    ) -> None:
        self.download_root = Path(download_root).resolve(strict=False)
        self._engine = _HeadlessGalleryDlEngine(tools_root or _default_tools_root())
        self.executor = executor or GalleryDlExecutor(self._engine)
        self._tool_probe = tool_probe or self._managed_tool_status
        self._registry = LocalTaskProviderRegistry()
        self._closed = False
        self._registry.register(
            "gallery-dl",
            label="gallery-dl",
            snapshot=self.executor.snapshots,
            action=self.executor.action,
        )

    def _managed_tool_status(self) -> tuple[bool, str | None]:
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
            "version": str(version)[:128] if version else None,
            "maxFilesPerJob": MAX_GALLERY_DL_FILES,
            "maxTrackedJobs": MAX_GALLERY_DL_TASKS,
            "supportedActions": ["cancel", "retry"],
            "managedOnly": True,
        }

    def _rows(self) -> list[dict[str, object]]:
        rows = self._registry.rows()
        return [row for row in rows if row.get("providerName") == "gallery-dl"]

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
            raise HeadlessGalleryDlApiError(
                f"maxFiles must be between 1 and {MAX_GALLERY_DL_FILES}"
            )

        try:
            task_id = self.executor.submit(
                source,
                output_root=self.download_root,
                max_files=max_files,
            )
        except (GalleryDlExecutorError, PublicUrlError) as exc:
            raise HeadlessGalleryDlApiError("gallery-dl request could not be queued") from exc
        return self.job(task_id)

    def action(self, task_id: object, action: object) -> dict[str, object]:
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
        return {
            "changed": bool(result.changed),
            "message": result.message,
            **self.job(clean_id),
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # The shared gallery-dl executor intentionally cancels only at safe file
        # boundaries. Request cancellation for every queued/active Headless task
        # so stopping the API cannot leave new gallery work queued behind it.
        for row in self._rows():
            actions = tuple(row.get("providerActions") or ())
            task_id = str(row.get("providerTaskId") or "")
            if task_id and "cancel" in actions:
                self._registry.perform_action("gallery-dl", task_id, "cancel")


def run_headless_gallery_dl_api_self_test() -> None:
    assert _GALLERY_TASK_ID_RE.fullmatch("gdl-0123456789abcdef")
    assert not _GALLERY_TASK_ID_RE.fullmatch("../gdl-0123456789abcdef")
    assert MAX_GALLERY_DL_FILES == 500
    assert MAX_GALLERY_DL_TASKS == 200
