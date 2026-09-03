from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from ai_models import WHISPER_MODELS
from ai_workspace import AiArtifactResult, transcript_path
from media_library import resolve_media_item_path

PROVIDER_ID = "faster-whisper"
MIN_MODEL_BYTES = 1024 * 1024
REQUIRED_MODEL_FILES = ("config.json", "model.bin")
LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_-]{0,32}$")


class FasterWhisperError(RuntimeError):
    pass


@dataclass(frozen=True)
class FasterWhisperStatus:
    available: bool
    version: str
    installed_models: tuple[str, ...]

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": PROVIDER_ID,
            "available": self.available,
            "version": self.version,
            "models": list(WHISPER_MODELS),
            "installedModels": list(self.installed_models),
            "installExplicitlyRequired": True,
            "supportsLocalFilesOnly": True,
        }


def _data_dir(engine_module) -> Path:
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir()) / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def model_root(engine_module) -> Path:
    root = _data_dir(engine_module) / "models" / "asr" / PROVIDER_ID
    root.mkdir(parents=True, exist_ok=True)
    return root


def _clean_model(value: object) -> str:
    model = str(value or "").strip().lower()
    if model not in WHISPER_MODELS:
        raise FasterWhisperError("faster-whisper 模型名称无效")
    return model


def model_dir(engine_module, model: object) -> Path:
    return model_root(engine_module) / _clean_model(model)


def _safe_model_directory(engine_module, model: object) -> Path | None:
    directory = model_dir(engine_module, model)
    if directory.is_symlink() or not directory.is_dir():
        return None
    total = 0
    for name in REQUIRED_MODEL_FILES:
        candidate = directory / name
        if candidate.is_symlink() or not candidate.is_file():
            return None
        try:
            total += candidate.stat().st_size
        except OSError:
            return None
    try:
        total += sum(
            item.stat().st_size
            for item in directory.iterdir()
            if item.is_file() and not item.is_symlink() and item.name not in REQUIRED_MODEL_FILES
        )
    except OSError:
        return None
    return directory if total >= MIN_MODEL_BYTES else None


def provider_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def provider_version() -> str:
    if not provider_available():
        return ""
    try:
        return metadata.version("faster-whisper")[:80]
    except metadata.PackageNotFoundError:
        return "unknown"


def provider_status(engine_module) -> FasterWhisperStatus:
    installed = tuple(model for model in WHISPER_MODELS if _safe_model_directory(engine_module, model) is not None)
    return FasterWhisperStatus(provider_available(), provider_version(), installed)


def require_model(engine_module, model: object) -> Path:
    clean = _clean_model(model)
    directory = _safe_model_directory(engine_module, clean)
    if directory is None:
        raise FasterWhisperError(
            f"faster-whisper 模型 {clean} 尚未显式安装。请先执行 ASR Provider 的 install_model。"
        )
    return directory


def _python_executable() -> Path | None:
    if not getattr(sys, "frozen", False):
        current = Path(sys.executable)
        if current.is_file() and not current.is_symlink():
            return current
    names = ("python.exe", "python", "python3") if os.name == "nt" else ("python3", "python")
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            candidate = Path(resolved)
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
    return None


def _bounded_timeout(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(60, min(parsed, maximum))


def install_model(
    engine_module,
    model: object,
    *,
    timeout_seconds: int = 3600,
    python_executable: object | None = None,
) -> tuple[bool, str]:
    clean = _clean_model(model)
    existing = _safe_model_directory(engine_module, clean)
    if existing is not None:
        return True, "模型已安装"
    target = model_dir(engine_module, clean)
    if target.is_symlink():
        raise FasterWhisperError("模型目录不能是符号链接")
    target.mkdir(parents=True, exist_ok=True)

    if python_executable is None:
        interpreter = _python_executable()
    else:
        try:
            interpreter = Path(str(python_executable)).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise FasterWhisperError("Python 解释器不可用") from exc
        if not interpreter.is_file() or interpreter.is_symlink():
            raise FasterWhisperError("Python 解释器不可用")
    if interpreter is None:
        return False, "未检测到可运行 faster-whisper 的 Python"

    script = (
        "import sys; from faster_whisper.utils import download_model; "
        "download_model(sys.argv[1], output_dir=sys.argv[2], local_files_only=False); print('ready')"
    )
    try:
        result = subprocess.run(
            [str(interpreter), "-c", script, clean, str(target)],
            capture_output=True,
            text=True,
            timeout=_bounded_timeout(timeout_seconds, default=3600, maximum=7200),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        return False, "faster-whisper 模型安装超时"
    except OSError as exc:
        return False, str(exc)[:1000]
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail[-1200:] or f"Python exited with {result.returncode}"
    if _safe_model_directory(engine_module, clean) is None:
        return False, "模型下载完成但完整性检查失败"
    return True, "模型已安装"


def remove_model(engine_module, model: object) -> tuple[bool, str]:
    clean = _clean_model(model)
    root = model_root(engine_module).resolve(strict=False)
    target = model_dir(engine_module, clean)
    if target.is_symlink():
        raise FasterWhisperError("拒绝删除符号链接模型目录")
    try:
        target.resolve(strict=False).relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise FasterWhisperError("模型目录无效") from exc
    if not target.exists():
        return True, "模型未安装"
    try:
        shutil.rmtree(target)
    except OSError as exc:
        return False, str(exc)[:1000]
    return True, "模型已删除"


def recommend(hardware: dict[str, Any] | None = None, *, profile: object = "balanced") -> dict[str, str]:
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
    if gpu and vram >= 10 and mode == "accurate":
        return {"model": "large-v3", "device": "cuda", "computeType": "float16"}
    if gpu and vram >= 5:
        return {"model": "turbo", "device": "cuda", "computeType": "float16"}
    if mode == "accurate" and ram >= 16:
        return {"model": "medium", "device": "cpu", "computeType": "int8"}
    if mode == "fast":
        return {"model": "small" if ram >= 8 else "base", "device": "cpu", "computeType": "int8"}
    return {"model": "small" if ram >= 10 else "base", "device": "cpu", "computeType": "int8"}


def _transcribe_script() -> str:
    return r'''import sys
from pathlib import Path
from faster_whisper import WhisperModel

def stamp(value):
    millis = max(0, round(float(value) * 1000))
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    seconds, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

model_path, source, destination, language, device, compute_type = sys.argv[1:7]
model = WhisperModel(model_path, device=device, compute_type=compute_type, local_files_only=True)
kwargs = {"vad_filter": True}
if language:
    kwargs["language"] = language
segments, _info = model.transcribe(source, **kwargs)
rows = []
for index, segment in enumerate(segments, 1):
    text = " ".join(str(segment.text or "").split()).strip()
    if not text:
        continue
    rows.append(f"{index}\n{stamp(segment.start)} --> {stamp(segment.end)}\n{text}\n")
Path(destination).write_text("\n".join(rows), encoding="utf-8")
'''


def transcribe(
    engine_module,
    media_id: object,
    *,
    model: object = "base",
    language: object = "",
    device: object = "cpu",
    compute_type: object = "int8",
    timeout_seconds: int = 7200,
    python_executable: object | None = None,
) -> AiArtifactResult:
    clean_id = str(media_id or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{16,64}", clean_id):
        raise FasterWhisperError("媒体条目 ID 无效")
    source = resolve_media_item_path(engine_module, clean_id)
    if source is None:
        raise FasterWhisperError("媒体文件不可用")
    managed_model = require_model(engine_module, model)
    lang = str(language or "").strip()
    if lang and not LANGUAGE_RE.fullmatch(lang):
        raise FasterWhisperError("语言代码无效")
    selected_device = str(device or "cpu").strip().lower()
    if selected_device not in {"cpu", "cuda", "auto"}:
        raise FasterWhisperError("设备参数无效")
    selected_compute = str(compute_type or "default").strip().lower()
    if selected_compute not in {"default", "int8", "int8_float16", "float16", "float32"}:
        raise FasterWhisperError("计算精度参数无效")

    interpreter = _python_executable() if python_executable is None else Path(str(python_executable)).expanduser().resolve(strict=True)
    if interpreter is None or not interpreter.is_file() or interpreter.is_symlink():
        raise FasterWhisperError("Python 解释器不可用")

    destination = transcript_path(engine_module, clean_id)
    with tempfile.TemporaryDirectory(prefix="galaxy-faster-whisper-") as directory:
        temporary = Path(directory) / "transcript.srt"
        try:
            result = subprocess.run(
                [
                    str(interpreter),
                    "-c",
                    _transcribe_script(),
                    str(managed_model),
                    str(source),
                    str(temporary),
                    lang,
                    selected_device,
                    selected_compute,
                ],
                capture_output=True,
                text=True,
                timeout=_bounded_timeout(timeout_seconds, default=7200, maximum=14400),
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise FasterWhisperError("faster-whisper 转写超时") from exc
        except OSError as exc:
            raise FasterWhisperError(str(exc)) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise FasterWhisperError(detail[-1600:] or f"Python exited with {result.returncode}")
        if not temporary.is_file() or temporary.is_symlink() or temporary.stat().st_size <= 0:
            raise FasterWhisperError("faster-whisper 未生成有效 SRT")
        target_tmp = destination.with_suffix(".srt.tmp")
        try:
            shutil.copyfile(temporary, target_tmp)
            target_tmp.replace(destination)
        except OSError:
            with suppress(OSError):
                target_tmp.unlink()
            raise
    return AiArtifactResult("transcript", clean_id, destination, f"{PROVIDER_ID}:{_clean_model(model)}")


def run_faster_whisper_provider_self_test() -> None:
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

        target = model_dir(Engine, "base")
        target.mkdir(parents=True)
        (target / "config.json").write_text("{}", encoding="utf-8")
        (target / "model.bin").write_bytes(b"x" * MIN_MODEL_BYTES)
        assert require_model(Engine, "base") == target
        status = provider_status(Engine)
        assert "base" in status.installed_models
        assert recommend({"ramGb": 4}, profile="fast")["model"] == "base"
        assert recommend({"gpuAvailable": True, "vramGb": 12}, profile="accurate")["model"] == "large-v3"

        with patch("faster_whisper_provider.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "ready"
            run.return_value.stderr = ""
            remove_model(Engine, "base")
            target.mkdir(parents=True)
            (target / "config.json").write_text("{}", encoding="utf-8")
            (target / "model.bin").write_bytes(b"x" * MIN_MODEL_BYTES)
            ok, _detail = install_model(Engine, "base", python_executable=sys.executable)
            assert ok
            command = run.call_args.args[0]
            assert command[-2:] == ["base", str(target)]

        assert remove_model(Engine, "base")[0]
        try:
            model_dir(Engine, "../bad")
        except FasterWhisperError:
            pass
        else:
            raise AssertionError("unsafe faster-whisper model id was accepted")
