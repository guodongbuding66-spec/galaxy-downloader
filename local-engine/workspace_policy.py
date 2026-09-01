from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

PREFERENCES_FILENAME = "workspace-options.json"
OUTPUT_NAME_STYLES = {"title-id", "title", "id-title"}
HISTORY_LIMITS = {20, 50, 80, 150, 300}
_WORKSPACE_CONTEXT = threading.local()

DEFAULT_WORKSPACE_PREFERENCES: dict[str, Any] = {
    "outputNameStyle": "title-id",
    "organizeBySource": False,
    "historyEnabled": True,
    "historyLimit": 80,
}


def _state_path(engine_module) -> Path:
    target = engine_module.app_dir() / "state"
    target.mkdir(parents=True, exist_ok=True)
    return target / PREFERENCES_FILENAME


def _clean_preferences(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    style = str(raw.get("outputNameStyle") or "title-id").strip().lower()
    if style not in OUTPUT_NAME_STYLES:
        style = "title-id"
    try:
        limit = int(raw.get("historyLimit") or 80)
    except (TypeError, ValueError):
        limit = 80
    if limit not in HISTORY_LIMITS:
        limit = min(HISTORY_LIMITS, key=lambda candidate: abs(candidate - max(1, limit)))
    return {
        "outputNameStyle": style,
        "organizeBySource": bool(raw.get("organizeBySource", False)),
        "historyEnabled": bool(raw.get("historyEnabled", True)),
        "historyLimit": limit,
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


def install_workspace_policy(engine_module):
    """Apply safe, persistent output-layout preferences to future media jobs.

    Defaults intentionally reproduce the established output path and filename.
    Only the final yt-dlp output template changes; parser, authentication, format
    selection, retries, FFmpeg processing and queue semantics remain untouched.
    """
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_workspace_policy_installed", False):
        return window_cls

    original_build_options = window_cls.build_options

    def build_options(window) -> dict[str, Any]:
        options = original_build_options(window)
        options["outtmpl"] = output_template(engine_module, getattr(window, "job", None))
        return options

    window_cls.build_options = build_options

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
        payload["workspaceOptions"] = {
            "outputNameStyle": preferences["outputNameStyle"],
            "organizeBySource": bool(preferences["organizeBySource"]),
            "historyEnabled": bool(preferences["historyEnabled"]),
            "historyLimit": int(preferences["historyLimit"]),
        }
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
        saved = save_workspace_preferences(
            FakeEngine,
            {
                "outputNameStyle": "id-title",
                "organizeBySource": True,
                "historyEnabled": False,
                "historyLimit": 147,
            },
        )
        assert saved["outputNameStyle"] == "id-title"
        assert saved["organizeBySource"] is True
        assert saved["historyEnabled"] is False
        assert saved["historyLimit"] == 150
        template = output_template(FakeEngine)
        assert "%(extractor_key)s" in template
        assert "%(id)s - %(title).170B" in template
