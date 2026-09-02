from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

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


def _self_test_engine():
    @dataclass(frozen=True)
    class BaseJob:
        source_url: str

    engine = SimpleNamespace(Job=BaseJob)

    def parse_job(raw: str):
        query = parse_qs(urlparse(raw).query)
        return engine.Job(unquote(query.get("url", [""])[0]))

    def job_from_payload(payload: dict[str, Any]):
        source = str(payload.get("sourceUrl") or "").strip()
        if not source.startswith(("http://", "https://")):
            raise ValueError("invalid source")
        return engine.Job(source)

    def job_to_payload(job):
        return {"sourceUrl": job.source_url}

    engine.parse_job = parse_job
    engine.job_from_payload = job_from_payload
    engine.job_to_payload = job_to_payload

    class Var:
        def __init__(self):
            self.value = ""

        def set(self, value):
            self.value = value

    class Window:
        def __init__(self, job):
            self.job = job
            self._galaxy_close_pending = False
            self._quick_url_var = Var()
            self._quick_state_var = Var()
            self.focused = False

        def after(self, _delay, fn):
            fn()

        def deiconify(self):
            self.focused = True

        def lift(self):
            self.focused = True

        def focus_force(self):
            self.focused = True

        def submit_bridge_job(self, payload):
            return (False, f"legacy:{payload.get('sourceUrl', '')}")

        def bridge_status(self):
            return {"ok": True}

    engine.EngineWindow = Window
    return engine


def run_desktop_preview_handoff_self_test() -> None:
    assert _preview_flag("1") is True
    assert _preview_flag("true") is True
    assert _preview_flag("0") is False
    assert _preview_flag("") is False

    engine = _self_test_engine()
    calls: list[str] = []
    original_parse = workbench._parse_quick_url_async
    workbench._parse_quick_url_async = lambda window, _engine: calls.append(window._quick_url_var.value)
    try:
        install_desktop_preview_handoff(engine)
        raw = "galaxy-downloader://download?url=https%3A%2F%2Fexample.test%2Fwatch&preview=1"
        preview_job = engine.parse_job(raw)
        assert preview_job.preview_only is True
        payload = engine.job_to_payload(preview_job)
        assert payload["previewOnly"] is True
        rebuilt = engine.job_from_payload(payload)
        assert rebuilt.preview_only is True

        resident = engine.EngineWindow(None)
        result = resident.submit_bridge_job(payload)
        assert result.accepted is True
        assert result.code == "PREVIEW_ACCEPTED"
        assert resident.job is None
        assert calls == ["https://example.test/watch"]

        cold = engine.EngineWindow(preview_job)
        assert cold.job is None
        assert calls == ["https://example.test/watch", "https://example.test/watch"]
        assert cold.bridge_status()["desktopPreviewHandoff"] is True

        normal = engine.parse_job(
            "galaxy-downloader://download?url=https%3A%2F%2Fexample.test%2Fother"
        )
        assert normal.preview_only is False
        normal_result = resident.submit_bridge_job(engine.job_to_payload(normal))
        assert normal_result == (False, "legacy:https://example.test/other")
    finally:
        workbench._parse_quick_url_async = original_parse
