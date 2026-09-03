from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ai_models import WHISPER_MODELS

PROVIDER_ID = "whisper"
MODEL_MANIFEST = "model.json"
MIN_MODEL_BYTES = 1024 * 1024

_MODEL_METADATA = {
    "tiny": {"sizeMb": 75, "languages": "multilingual", "precision": "fp32/fp16", "cpu": True, "gpu": True},
    "base": {"sizeMb": 142, "languages": "multilingual", "precision": "fp32/fp16", "cpu": True, "gpu": True},
    "small": {"sizeMb": 466, "languages": "multilingual", "precision": "fp32/fp16", "cpu": True, "gpu": True},
    "medium": {"sizeMb": 1500, "languages": "multilingual", "precision": "fp32/fp16", "cpu": True, "gpu": True},
    "large-v3": {"sizeMb": 3100, "languages": "multilingual", "precision": "fp16/fp32", "cpu": True, "gpu": True},
    "turbo": {"sizeMb": 1600, "languages": "multilingual", "precision": "fp16/fp32", "cpu": True, "gpu": True},
}


class AsrModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class AsrModelStatus:
    provider: str
    model: str
    installed: bool
    managed: bool
    path: str
    size_bytes: int
    size_mb: int
    languages: str
    precision: str
    cpu: bool
    gpu: bool

    def public_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["sizeBytes"] = data.pop("size_bytes")
        data["sizeMb"] = data.pop("size_mb")
        return data


@dataclass(frozen=True)
class AsrModelOperation:
    success: bool
    provider: str
    model: str
    detail: str
    path: str = ""

    def public_payload(self) -> dict[str, Any]:
        return asdict(self)


def _clean_model(value: object) -> str:
    model = str(value or "").strip().lower()
    if model not in WHISPER_MODELS:
        raise AsrModelError("Whisper 模型名称无效")
    return model


def _data_dir(engine_module) -> Path:
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir()) / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def whisper_model_root(engine_module) -> Path:
    root = _data_dir(engine_module) / "models" / "asr" / PROVIDER_ID
    root.mkdir(parents=True, exist_ok=True)
    return root


def whisper_model_dir(engine_module, model: object) -> Path:
    return whisper_model_root(engine_module) / _clean_model(model)


def _manifest_path(directory: Path) -> Path:
    return directory / MODEL_MANIFEST


def _load_manifest(directory: Path, model: str) -> dict[str, Any] | None:
    path = _manifest_path(directory)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("provider") != PROVIDER_ID or raw.get("model") != model:
        return None
    return raw


def _managed_checkpoint(directory: Path, model: str) -> Path | None:
    if directory.is_symlink() or not directory.is_dir():
        return None
    manifest = _load_manifest(directory, model)
    if manifest is None:
        return None
    filename = str(manifest.get("file") or "")
    if not filename or Path(filename).name != filename:
        return None
    checkpoint = directory / filename
    if checkpoint.is_symlink() or not checkpoint.is_file():
        return None
    try:
        size = checkpoint.stat().st_size
    except OSError:
        return None
    expected_size = manifest.get("sizeBytes")
    if not isinstance(expected_size, int) or expected_size < MIN_MODEL_BYTES or size != expected_size:
        return None
    if checkpoint.suffix.lower() != ".pt":
        return None
    return checkpoint


def whisper_model_status(engine_module, model: object) -> AsrModelStatus:
    clean = _clean_model(model)
    metadata = _MODEL_METADATA[clean]
    directory = whisper_model_dir(engine_module, clean)
    checkpoint = _managed_checkpoint(directory, clean)
    size = checkpoint.stat().st_size if checkpoint is not None else 0
    return AsrModelStatus(
        provider=PROVIDER_ID,
        model=clean,
        installed=checkpoint is not None,
        managed=checkpoint is not None,
        path=str(checkpoint) if checkpoint is not None else "",
        size_bytes=size,
        size_mb=int(metadata["sizeMb"]),
        languages=str(metadata["languages"]),
        precision=str(metadata["precision"]),
        cpu=bool(metadata["cpu"]),
        gpu=bool(metadata["gpu"]),
    )


def list_whisper_models(engine_module) -> list[dict[str, Any]]:
    return [whisper_model_status(engine_module, model).public_payload() for model in WHISPER_MODELS]


def require_whisper_model(engine_module, model: object) -> Path:
    status = whisper_model_status(engine_module, model)
    if not status.installed or not status.path:
        raise AsrModelError(
            f"Whisper 模型 {status.model} 尚未显式安装。请先在 ASR Model Manager 中执行 Download/Install。"
        )
    return Path(status.path)


def _bounded_timeout(value: object, *, default: int = 3600) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(60, min(parsed, 7200))


def _python_executable() -> Path | None:
    if not getattr(sys, "frozen", False):
        current = Path(sys.executable)
        if current.is_file():
            return current
    names = ("python.exe", "python", "python3") if os.name == "nt" else ("python3", "python")
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            path = Path(resolved)
            if path.is_file() and not path.is_symlink():
                return path
    return None


def _write_manifest(directory: Path, model: str, checkpoint: Path) -> None:
    manifest = _manifest_path(directory)
    temporary = manifest.with_suffix(".tmp")
    payload = {
        "version": 1,
        "provider": PROVIDER_ID,
        "model": model,
        "file": checkpoint.name,
        "sizeBytes": checkpoint.stat().st_size,
    }
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(manifest)
    except OSError:
        with suppress(OSError):
            temporary.unlink()
        raise


def install_whisper_model(
    engine_module,
    model: object,
    *,
    timeout_seconds: int = 3600,
    python_executable: object | None = None,
) -> AsrModelOperation:
    clean = _clean_model(model)
    existing = whisper_model_status(engine_module, clean)
    if existing.installed:
        return AsrModelOperation(True, PROVIDER_ID, clean, "模型已安装", existing.path)

    directory = whisper_model_dir(engine_module, clean)
    if directory.is_symlink():
        raise AsrModelError("ASR 模型目录不能是符号链接")
    directory.mkdir(parents=True, exist_ok=True)

    if python_executable is None:
        interpreter = _python_executable()
    else:
        try:
            interpreter = Path(str(python_executable)).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise AsrModelError("Python 解释器不可用") from exc
        if not interpreter.is_file() or interpreter.is_symlink():
            raise AsrModelError("Python 解释器不可用")
    if interpreter is None:
        return AsrModelOperation(False, PROVIDER_ID, clean, "未检测到可用于安装 openai-whisper 模型的 Python")

    script = (
        "import sys, whisper; "
        "whisper.load_model(sys.argv[1], device='cpu', download_root=sys.argv[2]); "
        "print('ready')"
    )
    try:
        result = subprocess.run(
            [str(interpreter), "-c", script, clean, str(directory)],
            capture_output=True,
            text=True,
            timeout=_bounded_timeout(timeout_seconds),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        return AsrModelOperation(False, PROVIDER_ID, clean, "Whisper 模型安装超时")
    except OSError as exc:
        return AsrModelOperation(False, PROVIDER_ID, clean, str(exc)[:1000])

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return AsrModelOperation(False, PROVIDER_ID, clean, detail[-1000:] or f"Python exited with {result.returncode}")

    candidates: list[Path] = []
    expected = directory / f"{clean}.pt"
    if expected.is_file() and not expected.is_symlink():
        candidates.append(expected)
    for candidate in sorted(directory.glob("*.pt")):
        if candidate not in candidates and candidate.is_file() and not candidate.is_symlink():
            candidates.append(candidate)
    checkpoint = next(
        (
            candidate
            for candidate in candidates
            if candidate.suffix.lower() == ".pt" and candidate.stat().st_size >= MIN_MODEL_BYTES
        ),
        None,
    )
    if checkpoint is None:
        return AsrModelOperation(False, PROVIDER_ID, clean, "Whisper 安装完成但未找到有效模型文件")
    try:
        _write_manifest(directory, clean, checkpoint)
    except OSError as exc:
        return AsrModelOperation(False, PROVIDER_ID, clean, f"模型已下载，但写入安装清单失败：{exc}")
    return AsrModelOperation(True, PROVIDER_ID, clean, "模型已安装", str(checkpoint))


def remove_whisper_model(engine_module, model: object) -> AsrModelOperation:
    clean = _clean_model(model)
    root = whisper_model_root(engine_module).resolve(strict=False)
    directory = whisper_model_dir(engine_module, clean)
    try:
        resolved = directory.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise AsrModelError("ASR 模型目录无效") from exc
    if directory.is_symlink():
        raise AsrModelError("拒绝删除符号链接模型目录")
    if not directory.exists():
        return AsrModelOperation(True, PROVIDER_ID, clean, "模型未安装")
    try:
        shutil.rmtree(directory)
    except OSError as exc:
        return AsrModelOperation(False, PROVIDER_ID, clean, str(exc)[:1000])
    return AsrModelOperation(True, PROVIDER_ID, clean, "模型已删除")


def recommend_whisper_model(
    hardware: dict[str, Any] | None = None,
    *,
    profile: object = "balanced",
) -> str:
    info = hardware if isinstance(hardware, dict) else {}
    mode = str(profile or "balanced").strip().lower()
    if mode not in {"fast", "balanced", "accurate"}:
        mode = "balanced"

    def number(key: str) -> float:
        try:
            return max(0.0, float(info.get(key) or 0))
        except (TypeError, ValueError):
            return 0.0

    ram = number("ramGb")
    vram = number("vramGb")
    gpu = bool(info.get("gpuAvailable")) or vram > 0

    if mode == "fast":
        if gpu and vram >= 4:
            return "turbo"
        return "small" if ram >= 8 else "base"
    if mode == "accurate":
        if gpu and vram >= 10:
            return "large-v3"
        if ram >= 16:
            return "medium"
        return "small" if ram >= 8 else "base"
    if gpu and vram >= 6:
        return "turbo"
    if ram >= 12:
        return "small"
    return "base"


def run_asr_model_manager_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def data_dir() -> Path:
                target = root / "data"
                target.mkdir(exist_ok=True)
                return target

        assert whisper_model_dir(Engine, "base") == root / "data" / "models" / "asr" / "whisper" / "base"
        assert not whisper_model_status(Engine, "base").installed
        try:
            require_whisper_model(Engine, "base")
        except AsrModelError:
            pass
        else:
            raise AssertionError("uninstalled Whisper model was accepted")

        model_dir = whisper_model_dir(Engine, "base")
        model_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = model_dir / "base.pt"
        checkpoint.write_bytes(b"x" * MIN_MODEL_BYTES)
        _write_manifest(model_dir, "base", checkpoint)
        status = whisper_model_status(Engine, "base")
        assert status.installed and Path(status.path) == checkpoint
        assert require_whisper_model(Engine, "base") == checkpoint

        manifest = json.loads((model_dir / MODEL_MANIFEST).read_text(encoding="utf-8"))
        manifest["sizeBytes"] += 1
        (model_dir / MODEL_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        assert not whisper_model_status(Engine, "base").installed
        _write_manifest(model_dir, "base", checkpoint)

        assert recommend_whisper_model({"ramGb": 4}, profile="fast") == "base"
        assert recommend_whisper_model({"ramGb": 16}, profile="accurate") == "medium"
        assert recommend_whisper_model({"gpuAvailable": True, "vramGb": 12}, profile="accurate") == "large-v3"
        assert recommend_whisper_model({"gpuAvailable": True, "vramGb": 8}, profile="balanced") == "turbo"

        with patch("asr_model_manager.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "ready"
            run.return_value.stderr = ""
            remove_whisper_model(Engine, "base")
            model_dir.mkdir(parents=True, exist_ok=True)
            checkpoint = model_dir / "base.pt"
            checkpoint.write_bytes(b"x" * MIN_MODEL_BYTES)
            operation = install_whisper_model(Engine, "base", python_executable=sys.executable)
            assert operation.success
            command = run.call_args.args[0]
            assert command[1] == "-c"
            assert command[-2:] == ["base", str(model_dir)]

        removed = remove_whisper_model(Engine, "base")
        assert removed.success and not model_dir.exists()

        try:
            whisper_model_dir(Engine, "../../bad")
        except AsrModelError:
            pass
        else:
            raise AssertionError("unsafe Whisper model was accepted")
