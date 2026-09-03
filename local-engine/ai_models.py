from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime_storage import state_dir as runtime_state_dir

SETTINGS_FILENAME = "ai-models.json"
WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3", "turbo")
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")


@dataclass(frozen=True)
class AiModelSettings:
    whisper_model: str = "base"
    summary_model: str = ""

    def public_payload(self) -> dict[str, str]:
        return {
            "whisperModel": self.whisper_model,
            "summaryModel": self.summary_model,
        }


def _settings_path(engine_module) -> Path:
    target = runtime_state_dir(engine_module)
    target.mkdir(parents=True, exist_ok=True)
    return target / SETTINGS_FILENAME


def normalize_whisper_model(value: object) -> str:
    model = str(value or "").strip().lower()
    return model if model in WHISPER_MODELS else "base"


def normalize_summary_model(value: object) -> str:
    model = str(value or "").strip()
    if not model:
        return ""
    return model if MODEL_ID_RE.fullmatch(model) else ""


def load_ai_model_settings(engine_module) -> AiModelSettings:
    try:
        raw = json.loads(_settings_path(engine_module).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return AiModelSettings()
    if not isinstance(raw, dict):
        return AiModelSettings()
    return AiModelSettings(
        whisper_model=normalize_whisper_model(raw.get("whisperModel")),
        summary_model=normalize_summary_model(raw.get("summaryModel")),
    )


def save_ai_model_settings(
    engine_module,
    *,
    whisper_model: object,
    summary_model: object,
) -> AiModelSettings:
    settings = AiModelSettings(
        whisper_model=normalize_whisper_model(whisper_model),
        summary_model=normalize_summary_model(summary_model),
    )
    path = _settings_path(engine_module)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(settings.public_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return settings


def _executable_names(name: str) -> tuple[str, ...]:
    if os.name == "nt":
        return (f"{name}.exe", name)
    return (name,)


def find_optional_tool(engine_module, name: str) -> Path | None:
    clean_name = str(name or "").strip().lower()
    if not clean_name or not re.fullmatch(r"[a-z0-9_-]{1,40}", clean_name):
        return None

    roots: list[Path] = []
    tools_accessor = getattr(engine_module, "tools_dir", None)
    if callable(tools_accessor):
        try:
            tools = Path(tools_accessor())
            roots.extend((tools / clean_name / "bin", tools / clean_name, tools / "bin", tools))
        except (OSError, RuntimeError, TypeError, ValueError):
            roots = list(roots)

    app_dir_accessor = getattr(engine_module, "app_dir", None)
    if callable(app_dir_accessor):
        try:
            app_root = Path(app_dir_accessor())
            roots.extend((app_root / "bin", app_root))
        except (OSError, RuntimeError, TypeError, ValueError):
            roots = list(roots)

    for root in roots:
        for executable_name in _executable_names(clean_name):
            candidate = root / executable_name
            if candidate.is_file() and not candidate.is_symlink():
                return candidate

    resolved = shutil.which(clean_name)
    if resolved:
        path = Path(resolved)
        if path.is_file():
            return path
    return None


def whisper_executable(engine_module) -> Path | None:
    return find_optional_tool(engine_module, "whisper")


def ollama_executable(engine_module) -> Path | None:
    return find_optional_tool(engine_module, "ollama")


def list_ollama_models(engine_module) -> tuple[str, ...]:
    executable = ollama_executable(engine_module)
    if executable is None:
        return ()
    try:
        result = subprocess.run(
            [str(executable), "list"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if result.returncode != 0:
        return ()

    models: list[str] = []
    for index, raw in enumerate((result.stdout or "").splitlines()):
        line = raw.strip()
        if not line or (index == 0 and line.upper().startswith("NAME")):
            continue
        name = line.split()[0].strip()
        normalized = normalize_summary_model(name)
        if normalized and normalized not in models:
            models.append(normalized)
        if len(models) >= 100:
            break
    return tuple(models)


def pull_ollama_model(engine_module, model: object, *, timeout_seconds: int = 1800) -> tuple[bool, str]:
    normalized = normalize_summary_model(model)
    if not normalized:
        return False, "模型名称无效"
    executable = ollama_executable(engine_module)
    if executable is None:
        return False, "未检测到 Ollama"
    try:
        result = subprocess.run(
            [str(executable), "pull", normalized],
            capture_output=True,
            text=True,
            timeout=max(30, min(int(timeout_seconds), 3600)),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        return False, "模型下载超时"
    except OSError as exc:
        return False, str(exc)
    detail = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        return False, detail[-1000:] or f"Ollama exited with {result.returncode}"
    return True, detail[-1000:] or "模型已就绪"


def ai_model_status(engine_module) -> dict[str, Any]:
    settings = load_ai_model_settings(engine_module)
    models = list_ollama_models(engine_module)
    return {
        "whisperReady": whisper_executable(engine_module) is not None,
        "ollamaReady": ollama_executable(engine_module) is not None,
        "whisperModel": settings.whisper_model,
        "summaryModel": settings.summary_model,
        "ollamaModels": list(models),
        "summaryModelReady": bool(settings.summary_model and settings.summary_model in models),
    }


def run_ai_models_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    assert normalize_whisper_model("turbo") == "turbo"
    assert normalize_whisper_model("../../bad") == "base"
    assert normalize_summary_model("qwen3:4b") == "qwen3:4b"
    assert normalize_summary_model("bad model") == ""

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

            @staticmethod
            def tools_dir() -> Path:
                return root / "tools"

        assert load_ai_model_settings(Engine) == AiModelSettings()
        saved = save_ai_model_settings(Engine, whisper_model="small", summary_model="qwen3:4b")
        assert saved.whisper_model == "small"
        assert saved.summary_model == "qwen3:4b"
        assert load_ai_model_settings(Engine) == saved
        with patch("ai_models.shutil.which", return_value=None):
            assert whisper_executable(Engine) is None
