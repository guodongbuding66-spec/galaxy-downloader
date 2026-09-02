from __future__ import annotations

from runtime_storage import state_dir as runtime_state_dir

import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ARCHIVE_FILENAME = "download-archive.txt"
_ARCHIVE_CONTEXT = threading.local()


def download_archive_path(engine_module) -> Path:
    state_dir = runtime_state_dir(engine_module)
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / ARCHIVE_FILENAME


def install_archive_policy(engine_module):
    """Add an opt-in yt-dlp download archive without changing default behavior.

    The archive is kept in Galaxy Local Engine's private ``state`` directory,
    not alongside downloaded media. When disabled (the default), neither the
    external yt-dlp command nor the embedded YoutubeDL fallback receives archive
    options, so repeated downloads behave exactly as before.
    """
    if getattr(engine_module, "_galaxy_archive_policy_installed", False):
        return engine_module.Job

    base_job = engine_module.Job

    @dataclass(frozen=True)
    class ArchiveJob(base_job):
        skip_previously_downloaded: bool = False

    ArchiveJob.__name__ = "Job"
    ArchiveJob.__qualname__ = "Job"
    engine_module.Job = ArchiveJob

    original_parse_job = engine_module.parse_job
    original_job_from_payload = engine_module.job_from_payload
    original_job_to_payload = engine_module.job_to_payload

    def parse_job(raw: str):
        job = original_parse_job(raw)
        query = parse_qs(urlparse(raw).query)
        enabled = engine_module._bool(query.get("archive", ["0"])[0])
        return replace(job, skip_previously_downloaded=enabled)

    def job_from_payload(payload: dict[str, Any]):
        job = original_job_from_payload(payload)
        enabled = bool(payload.get("skipPreviouslyDownloaded", False))
        return replace(job, skip_previously_downloaded=enabled)

    def job_to_payload(job) -> dict[str, Any]:
        payload = original_job_to_payload(job)
        payload["skipPreviouslyDownloaded"] = bool(
            getattr(job, "skip_previously_downloaded", False)
        )
        return payload

    engine_module.parse_job = parse_job
    engine_module.job_from_payload = job_from_payload
    engine_module.job_to_payload = job_to_payload

    original_build_options = engine_module.EngineWindow.build_options

    def build_options(window) -> dict[str, Any]:
        options = original_build_options(window)
        job = window.job
        if job is not None and getattr(job, "skip_previously_downloaded", False):
            options["download_archive"] = str(download_archive_path(engine_module))
        return options

    engine_module.EngineWindow.build_options = build_options

    original_external_download = engine_module.download_with_external_ytdlp

    def external_download(*args, **kwargs):
        archive = getattr(_ARCHIVE_CONTEXT, "path", None)
        if archive is not None and kwargs.get("download_archive") is None:
            kwargs["download_archive"] = archive
        return original_external_download(*args, **kwargs)

    engine_module.download_with_external_ytdlp = external_download

    original_run_external_job = engine_module.EngineWindow._run_external_job

    def run_external_job(window, executable):
        job = window.job
        _ARCHIVE_CONTEXT.path = (
            download_archive_path(engine_module)
            if job is not None and getattr(job, "skip_previously_downloaded", False)
            else None
        )
        try:
            return original_run_external_job(window, executable)
        finally:
            _ARCHIVE_CONTEXT.path = None

    engine_module.EngineWindow._run_external_job = run_external_job
    engine_module._galaxy_archive_policy_installed = True
    return ArchiveJob
