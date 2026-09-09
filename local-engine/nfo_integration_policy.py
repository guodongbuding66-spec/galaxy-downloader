from __future__ import annotations

import shutil
import tempfile
import threading
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import external_ytdlp
from nfo_sidecar import NfoSidecarError, convert_info_json_file

MAX_NFO_SIDECARS_PER_JOB = 500
MAX_WARNING_CHARS = 500
_NFO_CONTEXT = threading.local()


@dataclass(frozen=True)
class NfoPromotionResult:
    saved: tuple[Path, ...]
    failures: tuple[str, ...]
    truncated: bool = False


def _nfo_requested(job: Any) -> bool:
    return bool(job is not None and getattr(job, "include_nfo", False))


def _context_template() -> str | None:
    value = getattr(_NFO_CONTEXT, "info_template", None)
    return str(value) if value else None


def _insert_before_source(command: list[str], values: list[str]) -> None:
    try:
        index = command.index("--")
    except ValueError:
        index = len(command)
    command[index:index] = values


def _apply_external_nfo_command(job: Any, command: list[str]) -> list[str]:
    template = _context_template()
    if not _nfo_requested(job) or not template:
        return command
    command = [
        value
        for value in command
        if value not in {"--write-info-json", "--no-write-info-json"}
    ]
    _insert_before_source(command, ["--write-info-json", "-o", f"infojson:{template}"])
    return command


def _apply_embedded_nfo_options(job: Any, options: dict[str, Any]) -> dict[str, Any]:
    template = _context_template()
    if not _nfo_requested(job) or not template:
        return options
    current = options.get("outtmpl")
    if isinstance(current, dict):
        outtmpl = dict(current)
    else:
        outtmpl = {"default": str(current or "%(title)s [%(id)s].%(ext)s")}
    outtmpl["infojson"] = template
    options["outtmpl"] = outtmpl
    options["writeinfojson"] = True
    return options


def _discover_info_json_files(directory: Path) -> tuple[tuple[Path, ...], bool]:
    try:
        candidates = sorted(directory.glob("*.info.json"), key=lambda path: path.name.casefold())
    except OSError:
        return (), False

    result: list[Path] = []
    truncated = False
    for path in candidates:
        if len(result) >= MAX_NFO_SIDECARS_PER_JOB:
            truncated = True
            break
        try:
            if path.is_symlink() or not path.is_file():
                continue
        except OSError:
            continue
        result.append(path)
    return tuple(result), truncated


def _safe_failure_text(path: Path, exc: Exception) -> str:
    detail = str(exc).strip().replace("\n", " ")[:240] or exc.__class__.__name__
    return f"{path.name[:180]}: {detail}"


def _promote_nfo_sidecars(temp_dir: Path, output_dir: Path) -> NfoPromotionResult:
    info_paths, truncated = _discover_info_json_files(temp_dir)
    saved: list[Path] = []
    failures: list[str] = []
    for info_path in info_paths:
        try:
            temporary_nfo = convert_info_json_file(info_path, remove_source=True)
            target = output_dir / temporary_nfo.name
            if target.is_symlink():
                raise NfoSidecarError("refusing to replace a symlinked NFO output")
            temporary_nfo.replace(target)
            saved.append(target)
        except (NfoSidecarError, OSError) as exc:
            failures.append(_safe_failure_text(info_path, exc))
    return NfoPromotionResult(tuple(saved), tuple(failures), truncated)


def _warning_from_result(result: NfoPromotionResult) -> str | None:
    parts: list[str] = []
    if result.failures:
        parts.append("; ".join(result.failures[:3]))
    if result.truncated:
        parts.append(f"NFO output was capped at {MAX_NFO_SIDECARS_PER_JOB} items for this job")
    text = "; ".join(part for part in parts if part).strip()
    return text[:MAX_WARNING_CHARS] or None


def _record_result(window: Any, result: NfoPromotionResult) -> None:
    warning = _warning_from_result(result)
    if result.saved and warning:
        status = "partial"
    elif result.saved:
        status = "saved"
    else:
        status = "failed"
        warning = warning or "yt-dlp completed but no NFO metadata sidecar could be produced"
    window._update_bridge(
        nfoSidecarStatus=status,
        nfoSidecarWarning=warning,
        nfoSidecarSavedCount=len(result.saved),
    )


def _create_job_temp_dir(engine_module) -> Path:
    output_dir = Path(engine_module.default_download_dir())
    output_dir.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=".galaxy-nfo-", dir=output_dir))


def _job_info_template(temp_dir: Path) -> str:
    return str(temp_dir / "%(title).180B [%(id)s].%(ext)s")


def install_nfo_sidecar_policy(engine_module):
    """Add opt-in NFO sidecars without changing default media output.

    Metadata JSON is written only into a per-job hidden temporary directory. The
    main yt-dlp request keeps the same URL, cookies, collection selection and
    retries as the media download. Only after the media path succeeds are those
    bounded JSON files converted and atomically promoted into the download
    directory. Failed/cancelled jobs remove the temporary directory and never
    replace an existing user metadata JSON file.
    """
    if getattr(engine_module, "_galaxy_nfo_sidecar_policy_installed", False):
        return engine_module.Job

    base_job = engine_module.Job

    @dataclass(frozen=True)
    class NfoJob(base_job):
        include_nfo: bool = False

    NfoJob.__name__ = "Job"
    NfoJob.__qualname__ = "Job"
    engine_module.Job = NfoJob

    original_parse_job = engine_module.parse_job
    original_job_from_payload = engine_module.job_from_payload
    original_job_to_payload = engine_module.job_to_payload

    def parse_job(raw: str):
        job = original_parse_job(raw)
        query = parse_qs(urlparse(raw).query)
        return replace(
            job,
            include_nfo=engine_module._bool(query.get("nfo", ["0"])[0]),
        )

    def job_from_payload(payload: dict[str, Any]):
        job = original_job_from_payload(payload)
        return replace(job, include_nfo=bool(payload.get("includeNfo", False)))

    def job_to_payload(job) -> dict[str, Any]:
        payload = original_job_to_payload(job)
        payload["includeNfo"] = bool(getattr(job, "include_nfo", False))
        return payload

    engine_module.parse_job = parse_job
    engine_module.job_from_payload = job_from_payload
    engine_module.job_to_payload = job_to_payload

    original_external_command = external_ytdlp.build_external_command

    def build_external_command(*args, **kwargs):
        command = original_external_command(*args, **kwargs)
        return _apply_external_nfo_command(getattr(_NFO_CONTEXT, "job", None), command)

    external_ytdlp.build_external_command = build_external_command

    original_build_options = engine_module.EngineWindow.build_options

    def build_options(window) -> dict[str, Any]:
        options = original_build_options(window)
        return _apply_embedded_nfo_options(window.job, options)

    engine_module.EngineWindow.build_options = build_options

    original_run_external_job = engine_module.EngineWindow._run_external_job

    def run_external_job(window, executable):
        completed = original_run_external_job(window, executable)
        if not _nfo_requested(window.job):
            return completed
        temp_dir = getattr(_NFO_CONTEXT, "temp_dir", None)
        if not completed:
            window._update_bridge(
                nfoSidecarStatus="deferred",
                nfoSidecarWarning=(
                    "Bundled yt-dlp did not finish the media job; NFO creation will follow the embedded fallback."
                ),
                nfoSidecarSavedCount=0,
            )
            if temp_dir:
                for path in _discover_info_json_files(Path(temp_dir))[0]:
                    with suppress(OSError):
                        path.unlink()
            return completed
        if not temp_dir:
            window._update_bridge(
                nfoSidecarStatus="failed",
                nfoSidecarWarning="NFO temporary workspace was unavailable",
                nfoSidecarSavedCount=0,
            )
            return completed
        result = _promote_nfo_sidecars(Path(temp_dir), Path(engine_module.default_download_dir()))
        _record_result(window, result)
        return completed

    engine_module.EngineWindow._run_external_job = run_external_job

    original_run_job = engine_module.EngineWindow._run_job

    def run_job(window) -> None:
        job = window.job
        if not _nfo_requested(job):
            original_run_job(window)
            return

        temp_dir = _create_job_temp_dir(engine_module)
        _NFO_CONTEXT.job = job
        _NFO_CONTEXT.temp_dir = temp_dir
        _NFO_CONTEXT.info_template = _job_info_template(temp_dir)
        window._update_bridge(
            nfoSidecarStatus="preparing",
            nfoSidecarWarning=None,
            nfoSidecarSavedCount=0,
        )
        try:
            original_run_job(window)
            status = str(window.bridge_status().get("state") or "").lower()
            remaining, _ = _discover_info_json_files(temp_dir)
            if status == "completed" and remaining:
                result = _promote_nfo_sidecars(temp_dir, Path(engine_module.default_download_dir()))
                _record_result(window, result)
            elif status != "completed" and remaining:
                window._update_bridge(
                    nfoSidecarStatus="cancelled" if status == "cancelled" else "failed",
                    nfoSidecarWarning=(
                        "Media did not complete; temporary NFO metadata was discarded without touching existing sidecars."
                    ),
                    nfoSidecarSavedCount=0,
                )
        finally:
            _NFO_CONTEXT.job = None
            _NFO_CONTEXT.temp_dir = None
            _NFO_CONTEXT.info_template = None
            with suppress(OSError):
                shutil.rmtree(temp_dir)

    engine_module.EngineWindow._run_job = run_job

    original_bridge_status = engine_module.EngineWindow.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        payload["nfoSidecar"] = True
        payload["nfoSidecarDefault"] = False
        return payload

    engine_module.EngineWindow.bridge_status = bridge_status
    engine_module._galaxy_nfo_sidecar_policy_installed = True
    return NfoJob


def run_nfo_integration_self_test() -> None:
    command = [
        "yt-dlp",
        "--no-write-info-json",
        "-o",
        "%(title)s.%(ext)s",
        "--",
        "https://example.com/video",
    ]
    _NFO_CONTEXT.info_template = ".galaxy-nfo/%(title)s.%(ext)s"
    try:
        updated = _apply_external_nfo_command(
            type("Job", (), {"include_nfo": True})(),
            command,
        )
    finally:
        _NFO_CONTEXT.info_template = None
    assert "--write-info-json" in updated
    assert "--no-write-info-json" not in updated
    info_index = updated.index("-o", updated.index("-o") + 1)
    assert updated[info_index + 1].startswith("infojson:")
    assert updated[-2:] == ["--", "https://example.com/video"]
