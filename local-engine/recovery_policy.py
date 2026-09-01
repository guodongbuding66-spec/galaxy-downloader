from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import external_ytdlp
from workspace_policy import (
    CONCURRENT_FRAGMENTS,
    NETWORK_RETRY_PROFILES,
    RATE_LIMIT_MBPS,
    apply_external_network_options,
    load_workspace_preferences,
    rate_limit_bytes,
    retry_profile_settings,
)

_RECOVERY_CONTEXT = threading.local()

SMART_RETRY_RECIPES: dict[str, dict[str, Any]] = {
    # A weaker connection usually benefits from fewer simultaneous fragments and
    # the resilient retry profile. Keep unlimited bandwidth unless the source is
    # actively rate-limiting the user.
    "network": {
        "networkRetryProfile": "resilient",
        "concurrentFragments": 2,
        "rateLimitMbps": 0,
    },
    # 429/explicit throttling: reduce request fan-out and avoid immediately
    # returning to the source at full line rate.
    "rate-limit": {
        "networkRetryProfile": "resilient",
        "concurrentFragments": 1,
        "rateLimitMbps": 5,
    },
    # Unknown transient failures get one conservative recovery attempt. This is
    # intentionally not used for authentication, disk, geo or extractor errors.
    "unknown": {
        "networkRetryProfile": "resilient",
        "concurrentFragments": 2,
        "rateLimitMbps": 0,
    },
}


def _clean_profile(value: object) -> str | None:
    text = str(value or "").strip().lower()
    return text if text in NETWORK_RETRY_PROFILES else None


def _clean_allowed_int(value: object, allowed: set[int]) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number in allowed else None


def smart_retry_recipe(category: object) -> dict[str, Any] | None:
    recipe = SMART_RETRY_RECIPES.get(str(category or "").strip().lower())
    return dict(recipe) if recipe else None


def effective_network_preferences(engine_module, job: Any | None = None) -> dict[str, Any]:
    preferences = load_workspace_preferences(engine_module)
    if job is None:
        return preferences

    profile = _clean_profile(getattr(job, "network_retry_profile", None))
    rate = _clean_allowed_int(getattr(job, "rate_limit_mbps", None), RATE_LIMIT_MBPS)
    fragments = _clean_allowed_int(getattr(job, "concurrent_fragments", None), CONCURRENT_FRAGMENTS)
    if profile is not None:
        preferences["networkRetryProfile"] = profile
    if rate is not None:
        preferences["rateLimitMbps"] = rate
    if fragments is not None:
        preferences["concurrentFragments"] = fragments
    return preferences


def install_recovery_policy(engine_module):
    """Add optional per-job transport overrides for safe failure recovery.

    Normal website/protocol jobs do not send these fields, so 0.13 behavior is
    byte-for-byte unchanged at the policy boundary. Smart retry can attach a
    retry profile, fragment count and rate cap to one queued Job without changing
    the user's persistent workspace settings or affecting neighboring tasks.
    """
    if getattr(engine_module, "_galaxy_recovery_policy_installed", False):
        return engine_module.Job

    base_job = engine_module.Job

    @dataclass(frozen=True)
    class RecoveryJob(base_job):
        network_retry_profile: str | None = None
        rate_limit_mbps: int | None = None
        concurrent_fragments: int | None = None

    RecoveryJob.__name__ = "Job"
    RecoveryJob.__qualname__ = "Job"
    engine_module.Job = RecoveryJob

    original_parse_job = engine_module.parse_job
    original_job_from_payload = engine_module.job_from_payload
    original_job_to_payload = engine_module.job_to_payload

    def parse_job(raw: str):
        job = original_parse_job(raw)
        query = parse_qs(urlparse(raw).query)
        return replace(
            job,
            network_retry_profile=_clean_profile(query.get("retry_profile", [""])[0]),
            rate_limit_mbps=_clean_allowed_int(query.get("rate_mbps", [""])[0], RATE_LIMIT_MBPS),
            concurrent_fragments=_clean_allowed_int(query.get("fragments", [""])[0], CONCURRENT_FRAGMENTS),
        )

    def job_from_payload(payload: dict[str, Any]):
        job = original_job_from_payload(payload)
        return replace(
            job,
            network_retry_profile=_clean_profile(payload.get("networkRetryProfile")),
            rate_limit_mbps=_clean_allowed_int(payload.get("rateLimitMbps"), RATE_LIMIT_MBPS),
            concurrent_fragments=_clean_allowed_int(payload.get("concurrentFragments"), CONCURRENT_FRAGMENTS),
        )

    def job_to_payload(job) -> dict[str, Any]:
        payload = original_job_to_payload(job)
        profile = _clean_profile(getattr(job, "network_retry_profile", None))
        rate = _clean_allowed_int(getattr(job, "rate_limit_mbps", None), RATE_LIMIT_MBPS)
        fragments = _clean_allowed_int(getattr(job, "concurrent_fragments", None), CONCURRENT_FRAGMENTS)
        if profile is not None:
            payload["networkRetryProfile"] = profile
        if rate is not None:
            payload["rateLimitMbps"] = rate
        if fragments is not None:
            payload["concurrentFragments"] = fragments
        return payload

    engine_module.parse_job = parse_job
    engine_module.job_from_payload = job_from_payload
    engine_module.job_to_payload = job_to_payload

    original_build_options = engine_module.EngineWindow.build_options

    def build_options(window) -> dict[str, Any]:
        options = original_build_options(window)
        job = getattr(window, "job", None)
        if job is None:
            return options
        has_override = any(
            value is not None
            for value in (
                getattr(job, "network_retry_profile", None),
                getattr(job, "rate_limit_mbps", None),
                getattr(job, "concurrent_fragments", None),
            )
        )
        if not has_override:
            return options

        preferences = effective_network_preferences(engine_module, job)
        retry = retry_profile_settings(preferences["networkRetryProfile"])
        options["concurrent_fragment_downloads"] = int(preferences["concurrentFragments"])
        options["retries"] = retry["retries"]
        options["fragment_retries"] = retry["fragmentRetries"]
        options["extractor_retries"] = retry["extractorRetries"]
        options["socket_timeout"] = retry["socketTimeout"]
        limit = rate_limit_bytes(preferences)
        if limit is None:
            options.pop("ratelimit", None)
        else:
            options["ratelimit"] = limit
        return options

    engine_module.EngineWindow.build_options = build_options

    # workspace_policy already wrapped external_ytdlp.build_external_command.
    # Apply the per-job override after that wrapper so only this job changes.
    original_external_builder = external_ytdlp.build_external_command

    def build_external_command(*args, **kwargs):
        command = original_external_builder(*args, **kwargs)
        job = getattr(_RECOVERY_CONTEXT, "job", None)
        if job is None:
            return command
        has_override = any(
            value is not None
            for value in (
                getattr(job, "network_retry_profile", None),
                getattr(job, "rate_limit_mbps", None),
                getattr(job, "concurrent_fragments", None),
            )
        )
        if not has_override:
            return command
        preferences = effective_network_preferences(engine_module, job)
        return apply_external_network_options(command, preferences)

    external_ytdlp.build_external_command = build_external_command

    original_run_external_job = engine_module.EngineWindow._run_external_job

    def run_external_job(window, executable: Path):
        _RECOVERY_CONTEXT.job = getattr(window, "job", None)
        try:
            return original_run_external_job(window, executable)
        finally:
            _RECOVERY_CONTEXT.job = None

    engine_module.EngineWindow._run_external_job = run_external_job

    original_bridge_status = engine_module.EngineWindow.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        job = getattr(window, "job", None)
        effective = effective_network_preferences(engine_module, job)
        payload["smartRecovery"] = True
        payload["activeNetworkOptions"] = {
            "networkRetryProfile": effective["networkRetryProfile"],
            "rateLimitMbps": int(effective["rateLimitMbps"]),
            "concurrentFragments": int(effective["concurrentFragments"]),
            "perJobOverride": bool(
                job
                and any(
                    value is not None
                    for value in (
                        getattr(job, "network_retry_profile", None),
                        getattr(job, "rate_limit_mbps", None),
                        getattr(job, "concurrent_fragments", None),
                    )
                )
            ),
        }
        return payload

    engine_module.EngineWindow.bridge_status = bridge_status
    engine_module._galaxy_recovery_policy_installed = True
    return RecoveryJob


def run_recovery_self_test() -> None:
    import tempfile
    from types import SimpleNamespace

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        downloads = root / "downloads"
        downloads.mkdir()

        class FakeEngine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def default_download_dir() -> Path:
                return downloads

        base = effective_network_preferences(FakeEngine)
        assert base["networkRetryProfile"] == "standard"
        assert base["concurrentFragments"] == 4
        assert base["rateLimitMbps"] == 0

        job = SimpleNamespace(
            network_retry_profile="resilient",
            concurrent_fragments=2,
            rate_limit_mbps=5,
        )
        effective = effective_network_preferences(FakeEngine, job)
        assert effective["networkRetryProfile"] == "resilient"
        assert effective["concurrentFragments"] == 2
        assert effective["rateLimitMbps"] == 5
        assert smart_retry_recipe("network") == {
            "networkRetryProfile": "resilient",
            "concurrentFragments": 2,
            "rateLimitMbps": 0,
        }
        assert smart_retry_recipe("auth") is None
