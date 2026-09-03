from __future__ import annotations

import json
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import external_ytdlp
from runtime_storage import state_dir as runtime_state_dir

MAX_BANDWIDTH_KBPS = 10_000_000
PREFERENCES_FILENAME = "bandwidth-options.json"
_BANDWIDTH_CONTEXT = threading.local()


def normalize_bandwidth_kbps(value: object) -> int:
    """Normalize a user-visible KiB/s limit; zero means unlimited."""
    if value in (None, "", False):
        return 0
    try:
        limit = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0
    if limit <= 0:
        return 0
    return min(limit, MAX_BANDWIDTH_KBPS)


def _preferences_path(engine_module) -> Path:
    target = runtime_state_dir(engine_module)
    target.mkdir(parents=True, exist_ok=True)
    return target / PREFERENCES_FILENAME


def load_bandwidth_preference(engine_module) -> int:
    try:
        payload = json.loads(_preferences_path(engine_module).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0
    return normalize_bandwidth_kbps(payload.get("bandwidthLimitKbps"))


def save_bandwidth_preference(engine_module, value: object) -> int:
    limit = normalize_bandwidth_kbps(value)
    path = _preferences_path(engine_module)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"bandwidthLimitKbps": limit}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return limit


def _insert_before_source(command: list[str], values: list[str]) -> None:
    try:
        index = command.index("--")
    except ValueError:
        index = len(command)
    command[index:index] = values


def install_bandwidth_policy(engine_module):
    """Add a cross-platform, opt-in bandwidth cap to media jobs.

    The value is stored in KiB/s because that maps cleanly to yt-dlp's CLI and
    Python API. A value of zero preserves historical unlimited behavior. The
    desktop preference is applied only when a protocol/bridge request does not
    explicitly provide a per-job limit.
    """
    if getattr(engine_module, "_galaxy_bandwidth_policy_installed", False):
        return engine_module.Job

    base_job = engine_module.Job

    @dataclass(frozen=True)
    class BandwidthJob(base_job):
        bandwidth_limit_kbps: int = 0

    BandwidthJob.__name__ = "Job"
    BandwidthJob.__qualname__ = "Job"
    engine_module.Job = BandwidthJob

    original_parse_job = engine_module.parse_job
    original_job_from_payload = engine_module.job_from_payload
    original_job_to_payload = engine_module.job_to_payload

    def parse_job(raw: str):
        job = original_parse_job(raw)
        query = parse_qs(urlparse(raw).query)
        default = str(load_bandwidth_preference(engine_module))
        value = query.get("limit_kbps", [default])[0]
        return replace(job, bandwidth_limit_kbps=normalize_bandwidth_kbps(value))

    def job_from_payload(payload: dict[str, Any]):
        job = original_job_from_payload(payload)
        value = (
            payload.get("bandwidthLimitKbps")
            if "bandwidthLimitKbps" in payload
            else load_bandwidth_preference(engine_module)
        )
        return replace(job, bandwidth_limit_kbps=normalize_bandwidth_kbps(value))

    def job_to_payload(job) -> dict[str, Any]:
        payload = original_job_to_payload(job)
        payload["bandwidthLimitKbps"] = normalize_bandwidth_kbps(
            getattr(job, "bandwidth_limit_kbps", 0)
        )
        return payload

    engine_module.parse_job = parse_job
    engine_module.job_from_payload = job_from_payload
    engine_module.job_to_payload = job_to_payload

    original_build_options = engine_module.EngineWindow.build_options

    def build_options(window) -> dict[str, Any]:
        options = original_build_options(window)
        limit = normalize_bandwidth_kbps(
            getattr(getattr(window, "job", None), "bandwidth_limit_kbps", 0)
        )
        if limit:
            options["ratelimit"] = limit * 1024
        return options

    engine_module.EngineWindow.build_options = build_options

    original_external_command = external_ytdlp.build_external_command

    def build_external_command(*args, **kwargs):
        command = original_external_command(*args, **kwargs)
        job = getattr(_BANDWIDTH_CONTEXT, "job", None)
        limit = normalize_bandwidth_kbps(getattr(job, "bandwidth_limit_kbps", 0))
        if limit:
            _insert_before_source(command, ["--limit-rate", f"{limit}K"])
        return command

    external_ytdlp.build_external_command = build_external_command

    original_run_external_job = engine_module.EngineWindow._run_external_job

    def run_external_job(window, executable: Path):
        _BANDWIDTH_CONTEXT.job = window.job
        try:
            return original_run_external_job(window, executable)
        finally:
            _BANDWIDTH_CONTEXT.job = None

    engine_module.EngineWindow._run_external_job = run_external_job

    original_bridge_status = engine_module.EngineWindow.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        payload["bandwidthLimit"] = True
        payload["bandwidthLimitKbps"] = load_bandwidth_preference(engine_module)
        return payload

    engine_module.EngineWindow.bridge_status = bridge_status
    engine_module._galaxy_bandwidth_policy_installed = True
    return BandwidthJob


def run_bandwidth_policy_self_test() -> None:
    import tempfile

    assert normalize_bandwidth_kbps(None) == 0
    assert normalize_bandwidth_kbps("0") == 0
    assert normalize_bandwidth_kbps("512") == 512
    assert normalize_bandwidth_kbps("12.9") == 12
    assert normalize_bandwidth_kbps("bad") == 0
    assert normalize_bandwidth_kbps(MAX_BANDWIDTH_KBPS + 1) == MAX_BANDWIDTH_KBPS

    command = ["yt-dlp", "--", "https://example.com/video"]
    _insert_before_source(command, ["--limit-rate", "512K"])
    assert command == [
        "yt-dlp",
        "--limit-rate",
        "512K",
        "--",
        "https://example.com/video",
    ]

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                target = root / "state"
                target.mkdir(parents=True, exist_ok=True)
                return target

        assert load_bandwidth_preference(Engine) == 0
        assert save_bandwidth_preference(Engine, "2048") == 2048
        assert load_bandwidth_preference(Engine) == 2048
