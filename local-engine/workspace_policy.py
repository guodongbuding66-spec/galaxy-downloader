from __future__ import annotations

from runtime_storage import state_dir as runtime_state_dir

import json
import threading
from pathlib import Path
from typing import Any

import external_ytdlp as external_runtime

PREFERENCES_FILENAME = "workspace-options.json"
OUTPUT_NAME_STYLES = {"title-id", "title", "id-title"}
HISTORY_LIMITS = {20, 50, 80, 150, 300}
NETWORK_RETRY_PROFILES = {"standard", "resilient", "fast-fail"}
RATE_LIMIT_MBPS = {0, 1, 2, 5, 10, 20, 50, 100}
CONCURRENT_FRAGMENTS = {1, 2, 4, 8, 16}
DIAGNOSTIC_LOG_LIMITS_KB = {128, 256, 512, 1024, 2048}
LOW_DISK_WARNING_GB = {0, 1, 2, 5, 10, 20, 50}
_WORKSPACE_CONTEXT = threading.local()

DEFAULT_WORKSPACE_PREFERENCES: dict[str, Any] = {
    "outputNameStyle": "title-id",
    "organizeBySource": False,
    "historyEnabled": True,
    "historyLimit": 80,
    # Keep the exact network behavior used by 0.12 unless the user changes it.
    "networkRetryProfile": "standard",
    "rateLimitMbps": 0,
    "concurrentFragments": 4,
    # Runtime extras are opt-in so an upgrade never adds noise or disk writes.
    "completionAlert": False,
    "diagnosticLogEnabled": False,
    "diagnosticLogLimitKb": 512,
    # Disk warning is also opt-in. Zero means no warning threshold.
    "lowDiskWarningGb": 0,
}

RETRY_PROFILE_SETTINGS: dict[str, dict[str, int]] = {
    "standard": {
        "retries": 10,
        "fragmentRetries": 10,
        "extractorRetries": 5,
        "socketTimeout": 30,
    },
    "resilient": {
        "retries": 20,
        "fragmentRetries": 20,
        "extractorRetries": 8,
        "socketTimeout": 45,
    },
    "fast-fail": {
        "retries": 5,
        "fragmentRetries": 5,
        "extractorRetries": 3,
        "socketTimeout": 20,
    },
}


def _state_path(engine_module) -> Path:
    target = runtime_state_dir(engine_module)
    target.mkdir(parents=True, exist_ok=True)
    return target / PREFERENCES_FILENAME


def _nearest_allowed(value: object, allowed: set[int], default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number in allowed else min(allowed, key=lambda candidate: abs(candidate - number))


def _clean_preferences(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    style = str(raw.get("outputNameStyle") or "title-id").strip().lower()
    if style not in OUTPUT_NAME_STYLES:
        style = "title-id"
    retry_profile = str(raw.get("networkRetryProfile") or "standard").strip().lower()
    if retry_profile not in NETWORK_RETRY_PROFILES:
        retry_profile = "standard"
    return {
        "outputNameStyle": style,
        "organizeBySource": bool(raw.get("organizeBySource", False)),
        "historyEnabled": bool(raw.get("historyEnabled", True)),
        "historyLimit": _nearest_allowed(raw.get("historyLimit", 80), HISTORY_LIMITS, 80),
        "networkRetryProfile": retry_profile,
        "rateLimitMbps": _nearest_allowed(raw.get("rateLimitMbps", 0), RATE_LIMIT_MBPS, 0),
        "concurrentFragments": _nearest_allowed(raw.get("concurrentFragments", 4), CONCURRENT_FRAGMENTS, 4),
        "completionAlert": bool(raw.get("completionAlert", False)),
        "diagnosticLogEnabled": bool(raw.get("diagnosticLogEnabled", False)),
        "diagnosticLogLimitKb": _nearest_allowed(
            raw.get("diagnosticLogLimitKb", 512),
            DIAGNOSTIC_LOG_LIMITS_KB,
            512,
        ),
        "lowDiskWarningGb": _nearest_allowed(raw.get("lowDiskWarningGb", 0), LOW_DISK_WARNING_GB, 0),
    }


def load_workspace_preferences(engine_module) -> dict[str, Any]:
    path = _state_path(engine_module)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return dict(DEFAULT_WORKSPACE_PREFERENCES)
    return _clean_preferences(raw)


def save_workspace_preferences(engine_module, preferences: dict[str, Any]) -> dict[str, Any]:
    cleaned = _clean_preferences(preferences)
    path = _state_path(engine_module)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return cleaned


def retry_profile_settings(profile: object) -> dict[str, int]:
    key = str(profile or "standard").strip().lower()
    return dict(RETRY_PROFILE_SETTINGS.get(key, RETRY_PROFILE_SETTINGS["standard"]))


def rate_limit_bytes(preferences: dict[str, Any]) -> int | None:
    try:
        mbps = int(preferences.get("rateLimitMbps") or 0)
    except (TypeError, ValueError):
        return None
    if mbps <= 0:
        return None
    # yt-dlp's embedded ratelimit is bytes/second. UI values are Mbit/s.
    return max(1, int(mbps * 1_000_000 / 8))


def output_filename_template(style: str) -> str:
    if style == "title":
        return "%(title).200B.%(ext)s"
    if style == "id-title":
        return "%(id)s - %(title).170B.%(ext)s"
    return "%(title).180B [%(id)s].%(ext)s"


def output_template(engine_module, job: Any | None = None) -> str:
    preferences = load_workspace_preferences(engine_module)
    filename = output_filename_template(str(preferences["outputNameStyle"]))
    target = engine_module.default_download_dir()
    if bool(preferences["organizeBySource"]):
        target = target / "%(extractor_key)s"
    return str(target / filename)


def _replace_flag_value(command: list[str], flag: str, value: str) -> None:
    try:
        index = command.index(flag)
    except ValueError:
        return
    if index + 1 < len(command):
        command[index + 1] = value


def _remove_flag_value(command: list[str], flag: str) -> None:
    while flag in command:
        index = command.index(flag)
        del command[index : min(index + 2, len(command))]


def _insert_before_source(command: list[str], values: list[str]) -> None:
    try:
        index = command.index("--")
    except ValueError:
        index = len(command)
    command[index:index] = values


def apply_external_network_options(command: list[str], preferences: dict[str, Any]) -> list[str]:
    profile = str(preferences.get("networkRetryProfile") or "standard").strip().lower()
    if profile not in NETWORK_RETRY_PROFILES:
        profile = "standard"
    retry = retry_profile_settings(profile)
    _replace_flag_value(command, "--retries", str(retry["retries"]))
    _replace_flag_value(command, "--fragment-retries", str(retry["fragmentRetries"]))
    _replace_flag_value(command, "--extractor-retries", str(retry["extractorRetries"]))
    _replace_flag_value(command, "--concurrent-fragments", str(preferences.get("concurrentFragments") or 4))

    # The 0.12 external yt-dlp command did not set --socket-timeout. Keep that
    # exact behavior in Standard; only explicit non-standard profiles override it.
    _remove_flag_value(command, "--socket-timeout")
    if profile != "standard":
        _insert_before_source(command, ["--socket-timeout", str(retry["socketTimeout"])])

    _remove_flag_value(command, "--limit-rate")
    limit = rate_limit_bytes(preferences)
    if limit is not None:
        _insert_before_source(command, ["--limit-rate", str(limit)])
    return command


def install_workspace_policy(engine_module):
    """Apply safe, persistent output and network preferences to future jobs.

    Defaults intentionally reproduce the established output path, filename,
    retry counts and four-fragment downloader. Rate limiting, notifications,
    disk warnings and diagnostic logging remain disabled until explicitly set.
    """
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_workspace_policy_installed", False):
        return window_cls

    original_build_options = window_cls.build_options

    def build_options(window) -> dict[str, Any]:
        options = original_build_options(window)
        preferences = load_workspace_preferences(engine_module)
        retry = retry_profile_settings(preferences["networkRetryProfile"])
        options["outtmpl"] = output_template(engine_module, getattr(window, "job", None))
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

    window_cls.build_options = build_options

    # media_policy installs its command wrapper before workspace_policy. Layer
    # network controls after it so segment/chapter/SponsorBlock/aria2 additions
    # remain intact, then only replace deterministic transport flags.
    original_external_builder = external_runtime.build_external_command

    def build_external_command(*args, **kwargs):
        command = original_external_builder(*args, **kwargs)
        preferences = load_workspace_preferences(engine_module)
        return apply_external_network_options(command, preferences)

    external_runtime.build_external_command = build_external_command

    original_external_download = engine_module.download_with_external_ytdlp

    def external_download(*args, **kwargs):
        job = getattr(_WORKSPACE_CONTEXT, "job", None)
        if job is not None:
            kwargs["output_template"] = output_template(engine_module, job)
        return original_external_download(*args, **kwargs)

    engine_module.download_with_external_ytdlp = external_download

    original_run_external_job = window_cls._run_external_job

    def run_external_job(window, executable):
        _WORKSPACE_CONTEXT.job = getattr(window, "job", None)
        try:
            return original_run_external_job(window, executable)
        finally:
            _WORKSPACE_CONTEXT.job = None

    window_cls._run_external_job = run_external_job

    original_bridge_status = window_cls.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        preferences = load_workspace_preferences(engine_module)
        payload["workspaceOptions"] = dict(preferences)
        return payload

    window_cls.bridge_status = bridge_status
    window_cls._galaxy_workspace_policy_installed = True
    engine_module._galaxy_workspace_policy_installed = True
    return window_cls


def run_workspace_self_test() -> None:
    import tempfile

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

        assert load_workspace_preferences(FakeEngine) == DEFAULT_WORKSPACE_PREFERENCES

        standard_command = [
            "yt-dlp",
            "--retries", "10",
            "--fragment-retries", "10",
            "--extractor-retries", "5",
            "--concurrent-fragments", "4",
            "--", "https://example.com/watch",
        ]
        unchanged = apply_external_network_options(
            standard_command,
            dict(DEFAULT_WORKSPACE_PREFERENCES),
        )
        assert "--socket-timeout" not in unchanged
        assert "--limit-rate" not in unchanged
        assert unchanged[unchanged.index("--concurrent-fragments") + 1] == "4"

        saved = save_workspace_preferences(
            FakeEngine,
            {
                "outputNameStyle": "id-title",
                "organizeBySource": True,
                "historyEnabled": False,
                "historyLimit": 147,
                "networkRetryProfile": "resilient",
                "rateLimitMbps": 19,
                "concurrentFragments": 7,
                "completionAlert": True,
                "diagnosticLogEnabled": True,
                "diagnosticLogLimitKb": 600,
                "lowDiskWarningGb": 9,
            },
        )
        assert saved["outputNameStyle"] == "id-title"
        assert saved["organizeBySource"] is True
        assert saved["historyEnabled"] is False
        assert saved["historyLimit"] == 150
        assert saved["networkRetryProfile"] == "resilient"
        assert saved["rateLimitMbps"] == 20
        assert saved["concurrentFragments"] == 8
        assert saved["completionAlert"] is True
        assert saved["diagnosticLogEnabled"] is True
        assert saved["diagnosticLogLimitKb"] == 512
        assert saved["lowDiskWarningGb"] == 10
        assert retry_profile_settings("resilient")["retries"] == 20
        assert rate_limit_bytes(saved) == 2_500_000
        command = [
            "yt-dlp",
            "--retries", "10",
            "--fragment-retries", "10",
            "--extractor-retries", "5",
            "--concurrent-fragments", "4",
            "--", "https://example.com/watch",
        ]
        controlled = apply_external_network_options(command, saved)
        assert controlled[controlled.index("--retries") + 1] == "20"
        assert controlled[controlled.index("--fragment-retries") + 1] == "20"
        assert controlled[controlled.index("--extractor-retries") + 1] == "8"
        assert controlled[controlled.index("--concurrent-fragments") + 1] == "8"
        assert controlled[controlled.index("--socket-timeout") + 1] == "45"
        assert controlled[controlled.index("--limit-rate") + 1] == "2500000"
        template = output_template(FakeEngine)
        assert "%(extractor_key)s" in template
        assert "%(id)s - %(title).170B" in template
