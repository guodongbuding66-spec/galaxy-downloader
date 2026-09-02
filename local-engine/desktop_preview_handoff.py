from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import parse_qs, urlparse

import desktop_download_workbench as workbench
from bridge_submission_policy import JobSubmissionResult


def _preview_flag(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _focus_preview(window, source_url: str, engine_module) -> None:
    def apply() -> None:
        if getattr(window, "_galaxy_close_pending", False):
            return
        entry_var = getattr(window, "_quick_url_var", None)
        if entry_var is None:
            return
        window.deiconify()
        window.lift()
        try:
            window.focus_force()
        except Exception:
            pass
        entry_var.set(source_url)
        state_var = getattr(window, "_quick_state_var", None)
        if state_var is not None:
            state_var.set("已从浏览器接收链接，正在解析预览…")
        workbench._parse_quick_url_async(window, engine_module)

    window.after(0, apply)


def install_desktop_preview_handoff(engine_module):
    """Route explicit protocol preview handoffs into the desktop workbench.

    ``galaxy-downloader://download?...&preview=1`` intentionally reuses the
    existing protocol and single-instance bridge. The preview bit is carried in
    the Job/payload contract, but is intercepted before the queue or downloader
    can start. This avoids opening localhost CORS to arbitrary browser extension
    origins and keeps the public-URL policy as the final source boundary.
    """
    if getattr(engine_module, "_galaxy_desktop_preview_handoff_installed", False):
        return engine_module.Job

    base_job = engine_module.Job

    @dataclass(frozen=True)
    class PreviewHandoffJob(base_job):
        preview_only: bool = False

    PreviewHandoffJob.__name__ = "Job"
    PreviewHandoffJob.__qualname__ = "Job"
    engine_module.Job = PreviewHandoffJob

    original_parse_job = engine_module.parse_job
    original_job_from_payload = engine_module.job_from_payload
    original_job_to_payload = engine_module.job_to_payload

    def parse_job(raw: str):
        job = original_parse_job(raw)
        query = parse_qs(urlparse(raw).query)
        return replace(job, preview_only=_preview_flag(query.get("preview", ["0"])[0]))

    def job_from_payload(payload: dict[str, Any]):
        job = original_job_from_payload(payload)
        return replace(job, preview_only=bool(payload.get("previewOnly", False)))

    def job_to_payload(job) -> dict[str, Any]:
        payload = original_job_to_payload(job)
        payload["previewOnly"] = bool(getattr(job, "preview_only", False))
        return payload

    window_cls = engine_module.EngineWindow
    original_init = window_cls.__init__
    original_submit = window_cls.submit_bridge_job

    def init(window, job):
        preview_job = job if bool(getattr(job, "preview_only", False)) else None
        original_init(window, None if preview_job is not None else job)
        if preview_job is not None:
            _focus_preview(window, str(preview_job.source_url), engine_module)

    def submit_bridge_job(window, payload: dict[str, Any]):
        if not bool(payload.get("previewOnly", False)):
            return original_submit(window, payload)
        try:
            job = job_from_payload(payload)
        except ValueError as exc:
            return JobSubmissionResult(False, str(exc), 400, "BAD_REQUEST")
        if not bool(getattr(job, "preview_only", False)):
            return original_submit(window, payload)
        if getattr(window, "_galaxy_close_pending", False):
            return JobSubmissionResult(
                False,
                "Galaxy Local Engine is shutting down",
                503,
                "ENGINE_SHUTTING_DOWN",
            )
        _focus_preview(window, str(job.source_url), engine_module)
        return JobSubmissionResult(
            True,
            "Preview handoff accepted",
            202,
            "PREVIEW_ACCEPTED",
        )

    original_bridge_status = window_cls.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        payload["desktopPreviewHandoff"] = True
        return payload

    engine_module.parse_job = parse_job
    engine_module.job_from_payload = job_from_payload
    engine_module.job_to_payload = job_to_payload
    window_cls.__init__ = init
    window_cls.submit_bridge_job = submit_bridge_job
    window_cls.bridge_status = bridge_status
    window_cls._galaxy_desktop_preview_handoff_installed = True
    engine_module._galaxy_desktop_preview_handoff_installed = True
    return PreviewHandoffJob


def run_desktop_preview_handoff_self_test() -> None:
    assert _preview_flag("1") is True
    assert _preview_flag("true") is True
    assert _preview_flag("0") is False
    assert _preview_flag("") is False
