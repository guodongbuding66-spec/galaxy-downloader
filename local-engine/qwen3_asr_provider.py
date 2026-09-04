from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import suppress
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from ai_workspace import AiArtifactResult, transcript_path
from media_library import resolve_media_item_path

PROVIDER_ID = "qwen3-asr"
MODEL_ID = "0.6b-hf"
MODELS = (MODEL_ID,)
REPOSITORY = "Qwen/Qwen3-ASR-0.6B-hf"
REVISION = "7f1569a48a89f3e3f4dc3a5c9d28bddd903bc76c"
MODEL_WEIGHT = "model.safetensors"
MODEL_WEIGHT_BYTES = 1_564_928_088
MODEL_WEIGHT_SHA256 = "d3f212dd20abecd315d830bc54ae3865e56ebfc3276484e57b771288ba27fd35"
REQUIRED_FILES = (
    "chat_template.jinja",
    "config.json",
    "generation_config.json",
    MODEL_WEIGHT,
    "processor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
DOWNLOAD_PATTERNS = REQUIRED_FILES
MANIFEST_NAME = "galaxy-qwen3-asr-manifest.json"
MAX_SNAPSHOT_FILES = 1_000
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024 * 1024
MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
DEVICE_RE = re.compile(r"^(?:cpu|cuda(?::[0-9]{1,2})?)$")
LANGUAGES = (
    "auto",
    "zh",
    "en",
    "yue",
    "ar",
    "de",
    "fr",
    "es",
    "pt",
    "id",
    "it",
    "ko",
    "ru",
    "th",
    "vi",
    "ja",
    "tr",
    "hi",
    "ms",
    "nl",
    "sv",
    "da",
    "fi",
    "pl",
    "cs",
    "fil",
    "fa",
    "el",
    "hu",
    "mk",
    "ro",
)
MIN_TRANSFORMERS_VERSION = (5, 13, 0)


class Qwen3AsrError(RuntimeError):
    pass


@dataclass(frozen=True)
class Qwen3AsrStatus:
    available: bool
    installer_available: bool
    version: str
    installed_models: tuple[str, ...]

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": PROVIDER_ID,
            "name": "Qwen3-ASR",
            "available": self.available,
            "installerAvailable": self.installer_available,
            "version": self.version,
            "models": list(MODELS),
            "installedModels": list(self.installed_models),
            "languages": list(LANGUAGES),
            "languageMode": "automatic-or-forced",
            "installExplicitlyRequired": True,
            "supportsLocalFilesOnly": True,
            "supportsCpu": True,
            "supportsGpu": True,
            "supportsMps": False,
            "repositoryRevision": REVISION,
        }


def _data_dir(engine_module) -> Path:
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir()) / "data"
    if root.is_symlink():
        raise Qwen3AsrError("ASR 数据目录不能是符号链接")
    root.mkdir(parents=True, exist_ok=True)
    return root


def model_root(engine_module) -> Path:
    root = _data_dir(engine_module) / "models" / "asr" / PROVIDER_ID
    if root.is_symlink():
        raise Qwen3AsrError("Qwen3-ASR 模型根目录不能是符号链接")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _clean_model(value: object) -> str:
    model = str(value or "").strip().lower()
    if model not in MODELS:
        raise Qwen3AsrError("Qwen3-ASR 模型名称无效")
    return model


def model_dir(engine_module, model: object = MODEL_ID) -> Path:
    return model_root(engine_module) / _clean_model(model)


def _safe_child(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_payload() -> dict[str, Any]:
    return {
        "provider": PROVIDER_ID,
        "model": MODEL_ID,
        "repository": REPOSITORY,
        "revision": REVISION,
        "weight": MODEL_WEIGHT,
        "weightBytes": MODEL_WEIGHT_BYTES,
        "weightSha256": MODEL_WEIGHT_SHA256,
    }


def _read_manifest(directory: Path) -> dict[str, Any] | None:
    candidate = directory / MANIFEST_NAME
    if candidate.is_symlink() or not candidate.is_file():
        return None
    try:
        raw = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _manifest_matches(directory: Path) -> bool:
    raw = _read_manifest(directory)
    if raw is None:
        return False
    expected = _manifest_payload()
    return all(raw.get(key) == value for key, value in expected.items())


def _snapshot_is_safe(directory: Path, *, verify_weight_hash: bool = False) -> bool:
    if directory.is_symlink() or not directory.is_dir() or not _manifest_matches(directory):
        return False
    for name in REQUIRED_FILES:
        candidate = directory / name
        if candidate.is_symlink() or not candidate.is_file():
            return False
    weight = directory / MODEL_WEIGHT
    try:
        if weight.stat().st_size != MODEL_WEIGHT_BYTES:
            return False
    except OSError:
        return False

    count = 0
    total = 0
    try:
        for current_root, directory_names, file_names in os.walk(directory, followlinks=False):
            current = Path(current_root)
            for name in directory_names:
                if (current / name).is_symlink():
                    return False
            for name in file_names:
                item = current / name
                if item.is_symlink() or not item.is_file():
                    return False
                count += 1
                if count > MAX_SNAPSHOT_FILES:
                    return False
                total += item.stat().st_size
                if total > MAX_SNAPSHOT_BYTES:
                    return False
    except OSError:
        return False

    if verify_weight_hash:
        try:
            return _sha256(weight) == MODEL_WEIGHT_SHA256
        except OSError:
            return False
    return True


def _safe_model_directory(engine_module, model: object = MODEL_ID) -> Path | None:
    target = model_dir(engine_module, model)
    return target if _snapshot_is_safe(target) else None


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = [int(item) for item in re.findall(r"\d+", str(value or ""))[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])  # type: ignore[return-value]


def provider_version() -> str:
    if importlib.util.find_spec("transformers") is None:
        return ""
    try:
        return metadata.version("transformers")[:80]
    except metadata.PackageNotFoundError:
        return "unknown"


def provider_available() -> bool:
    if importlib.util.find_spec("transformers") is None or importlib.util.find_spec("torch") is None:
        return False
    version = provider_version()
    return version == "unknown" or _version_tuple(version) >= MIN_TRANSFORMERS_VERSION


def installer_available() -> bool:
    return importlib.util.find_spec("huggingface_hub") is not None


def provider_status(engine_module) -> Qwen3AsrStatus:
    installed = tuple(model for model in MODELS if _safe_model_directory(engine_module, model) is not None)
    return Qwen3AsrStatus(
        provider_available(),
        installer_available(),
        provider_version(),
        installed,
    )


def require_model(engine_module, model: object = MODEL_ID) -> Path:
    clean = _clean_model(model)
    directory = _safe_model_directory(engine_module, clean)
    if directory is None:
        raise Qwen3AsrError(
            f"Qwen3-ASR 模型 {clean} 尚未显式安装。请先执行 ASR Provider 的 install_model。"
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


def _resolve_python(value: object | None) -> Path | None:
    if value is None:
        return _python_executable()
    try:
        candidate = Path(str(value)).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise Qwen3AsrError("Python 解释器不可用") from exc
    if candidate.is_symlink() or not candidate.is_file():
        raise Qwen3AsrError("Python 解释器不可用")
    return candidate


def _bounded_timeout(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(60, min(parsed, maximum))


def _install_script() -> str:
    return (
        "import json,sys; from huggingface_hub import snapshot_download; "
        "snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3], "
        "allow_patterns=json.loads(sys.argv[4]), local_files_only=False); print('ready')"
    )


def install_model(
    engine_module,
    model: object = MODEL_ID,
    *,
    timeout_seconds: int = 10_800,
    python_executable: object | None = None,
) -> tuple[bool, str]:
    clean = _clean_model(model)
    if _safe_model_directory(engine_module, clean) is not None:
        return True, "模型已安装"
    interpreter = _resolve_python(python_executable)
    if interpreter is None:
        return False, "未检测到可运行 Hugging Face Hub 的 Python"

    root = model_root(engine_module)
    target = model_dir(engine_module, clean)
    if target.is_symlink() or not _safe_child(root, target):
        raise Qwen3AsrError("Qwen3-ASR 模型目录无效")
    staging = root / f".{clean}.{uuid.uuid4().hex}.part"
    backup = root / f".{clean}.{uuid.uuid4().hex}.backup"
    if staging.is_symlink() or backup.is_symlink():
        raise Qwen3AsrError("Qwen3-ASR 临时模型目录无效")
    staging.mkdir(parents=True, exist_ok=False)

    environment = os.environ.copy()
    environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
    try:
        result = subprocess.run(
            [
                str(interpreter),
                "-c",
                _install_script(),
                REPOSITORY,
                REVISION,
                str(staging),
                json.dumps(list(DOWNLOAD_PATTERNS)),
            ],
            capture_output=True,
            text=True,
            timeout=_bounded_timeout(timeout_seconds, default=10_800, maximum=21_600),
            check=False,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(staging, ignore_errors=True)
        return False, "Qwen3-ASR 模型安装超时"
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return False, str(exc)[:1000]

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        shutil.rmtree(staging, ignore_errors=True)
        return False, detail[-1200:] or f"Python exited with {result.returncode}"

    try:
        (staging / MANIFEST_NAME).write_text(
            json.dumps(_manifest_payload(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return False, str(exc)[:1000]

    if not _snapshot_is_safe(staging, verify_weight_hash=True):
        shutil.rmtree(staging, ignore_errors=True)
        return False, "模型下载完成但固定版本完整性检查失败"

    moved_old = False
    try:
        if target.exists():
            if target.is_symlink():
                raise Qwen3AsrError("拒绝替换符号链接模型目录")
            target.replace(backup)
            moved_old = True
        staging.replace(target)
        if moved_old:
            shutil.rmtree(backup, ignore_errors=True)
    except (OSError, Qwen3AsrError) as exc:
        with suppress(OSError):
            if target.exists() and not target.is_symlink():
                shutil.rmtree(target)
        if moved_old and backup.exists() and not backup.is_symlink():
            with suppress(OSError):
                backup.replace(target)
        shutil.rmtree(staging, ignore_errors=True)
        return False, str(exc)[:1000]

    if _safe_model_directory(engine_module, clean) is None:
        return False, "模型安装后完整性检查失败"
    return True, "模型已安装"


def remove_model(engine_module, model: object = MODEL_ID) -> tuple[bool, str]:
    clean = _clean_model(model)
    root = model_root(engine_module)
    target = model_dir(engine_module, clean)
    if target.is_symlink():
        raise Qwen3AsrError("拒绝删除符号链接模型目录")
    if not _safe_child(root, target):
        raise Qwen3AsrError("Qwen3-ASR 模型目录无效")
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
    try:
        vram = max(0.0, float(info.get("vramGb") or 0))
    except (TypeError, ValueError):
        vram = 0.0
    device = "cuda:0" if bool(info.get("gpuAvailable")) and vram >= 4 else "cpu"
    return {"model": MODEL_ID, "device": device, "profile": mode}


def _clean_language(value: object) -> str:
    language = str(value or "auto").strip().lower()
    if language not in LANGUAGES:
        raise Qwen3AsrError("Qwen3-ASR 语言参数无效")
    return language


def _clean_device(value: object) -> str:
    device = str(value or "cpu").strip().lower()
    if not DEVICE_RE.fullmatch(device):
        raise Qwen3AsrError("Qwen3-ASR 设备参数无效")
    return device


def _transcribe_script() -> str:
    return r'''import shutil
import subprocess
import sys
from pathlib import Path

import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor


def stamp(seconds):
    value = max(0, int(round(float(seconds) * 1000.0)))
    hours, value = divmod(value, 3600000)
    minutes, value = divmod(value, 60000)
    seconds, value = divmod(value, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{value:03d}"


def duration_seconds(source):
    probe = shutil.which("ffprobe")
    if probe:
        result = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", source],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            try:
                value = float((result.stdout or "").strip())
                if value > 0:
                    return value
            except ValueError:
                pass
    try:
        import soundfile as sf
        info = sf.info(source)
        if info.samplerate and info.frames:
            value = float(info.frames) / float(info.samplerate)
            if value > 0:
                return value
    except Exception:
        pass
    return 1.0


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


model_dir, source, destination, device, language = sys.argv[1:6]
managed = Path(model_dir)
if not managed.is_dir():
    raise RuntimeError("managed Qwen3-ASR model is unavailable")
if device == "cpu":
    torch_device = "cpu"
    dtype = torch.float32
elif device == "cuda":
    torch_device = "cuda:0"
    dtype = torch.bfloat16
elif device.startswith("cuda:"):
    torch_device = device
    dtype = torch.bfloat16
else:
    raise RuntimeError("unsupported Qwen3-ASR device")

processor = AutoProcessor.from_pretrained(str(managed), local_files_only=True)
model = AutoModelForMultimodalLM.from_pretrained(
    str(managed),
    local_files_only=True,
    dtype=dtype,
)
model.to(torch_device)
requested_language = None if language == "auto" else language
inputs = processor.apply_transcription_request(
    audio=source,
    language=requested_language,
).to(model.device, model.dtype)
output_ids = model.generate(**inputs, max_new_tokens=512)
generated_ids = output_ids[:, inputs["input_ids"].shape[1]:]
decoded = processor.decode(generated_ids, return_format="transcription_only")
text = clean_text(decoded[0] if isinstance(decoded, (list, tuple)) else decoded)
if not text:
    raise RuntimeError("Qwen3-ASR returned no speech")
end = max(1.0, duration_seconds(source))
Path(destination).write_text(
    f"1\n00:00:00,000 --> {stamp(end)}\n{text}\n",
    encoding="utf-8",
)
'''


def transcribe(
    engine_module,
    media_id: object,
    *,
    model: object = MODEL_ID,
    language: object = "auto",
    device: object = "cpu",
    timeout_seconds: int = 10_800,
    python_executable: object | None = None,
) -> AiArtifactResult:
    clean_id = str(media_id or "").strip().lower()
    if not MEDIA_ID_RE.fullmatch(clean_id):
        raise Qwen3AsrError("媒体条目 ID 无效")
    source = resolve_media_item_path(engine_module, clean_id)
    if source is None:
        raise Qwen3AsrError("媒体文件不可用")
    managed = require_model(engine_module, model)
    selected_language = _clean_language(language)
    selected_device = _clean_device(device)
    interpreter = _resolve_python(python_executable)
    if interpreter is None:
        raise Qwen3AsrError("Python 解释器不可用")
    if not provider_available():
        raise Qwen3AsrError("Qwen3-ASR Transformers 运行时不可用或版本低于 5.13.0")

    destination = transcript_path(engine_module, clean_id)
    environment = os.environ.copy()
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    environment["HF_DATASETS_OFFLINE"] = "1"
    environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
    with tempfile.TemporaryDirectory(prefix="galaxy-qwen3-asr-") as directory:
        temporary = Path(directory) / "transcript.srt"
        try:
            result = subprocess.run(
                [
                    str(interpreter),
                    "-c",
                    _transcribe_script(),
                    str(managed),
                    str(source),
                    str(temporary),
                    selected_device,
                    selected_language,
                ],
                capture_output=True,
                text=True,
                timeout=_bounded_timeout(timeout_seconds, default=10_800, maximum=21_600),
                check=False,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise Qwen3AsrError("Qwen3-ASR 转写超时") from exc
        except OSError as exc:
            raise Qwen3AsrError(str(exc)[:1600]) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise Qwen3AsrError(detail[-1600:] or f"Python exited with {result.returncode}")
        if not temporary.is_file() or temporary.is_symlink() or temporary.stat().st_size <= 0:
            raise Qwen3AsrError("Qwen3-ASR 未生成有效 SRT")
        target_tmp = destination.with_suffix(".srt.tmp")
        try:
            shutil.copyfile(temporary, target_tmp)
            target_tmp.replace(destination)
        except OSError:
            with suppress(OSError):
                target_tmp.unlink()
            raise
    return AiArtifactResult("transcript", clean_id, destination, f"{PROVIDER_ID}:{_clean_model(model)}")


def run_qwen3_asr_provider_self_test() -> None:
    import tempfile as _tempfile
    from types import SimpleNamespace
    from unittest.mock import patch

    with _tempfile.TemporaryDirectory() as directory:
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

        assert provider_status(Engine).installed_models == ()
        assert recommend({"gpuAvailable": True, "vramGb": 8})["device"] == "cuda:0"
        assert recommend({"gpuAvailable": True, "vramGb": 2})["device"] == "cpu"
        assert REVISION == "7f1569a48a89f3e3f4dc3a5c9d28bddd903bc76c"
        assert MIN_TRANSFORMERS_VERSION == (5, 13, 0)
        script = _transcribe_script()
        assert "local_files_only=True" in script
        assert "apply_transcription_request" in script
        assert 'language=requested_language' in script

        payload = b"qwen3-asr-test-weight"
        payload_hash = hashlib.sha256(payload).hexdigest()

        def fake_install(command, **kwargs):
            assert command[-4] == REPOSITORY
            assert command[-3] == REVISION
            destination = Path(command[-2])
            patterns = set(json.loads(command[-1]))
            assert patterns == set(REQUIRED_FILES)
            destination.mkdir(parents=True, exist_ok=True)
            for name in REQUIRED_FILES:
                target = destination / name
                if name == MODEL_WEIGHT:
                    target.write_bytes(payload)
                else:
                    target.write_text("{}", encoding="utf-8")
            assert kwargs["env"]["HF_HUB_DISABLE_TELEMETRY"] == "1"
            return SimpleNamespace(returncode=0, stdout="ready", stderr="")

        with patch(__name__ + ".MODEL_WEIGHT_BYTES", len(payload)), patch(
            __name__ + ".MODEL_WEIGHT_SHA256", payload_hash
        ), patch(__name__ + ".subprocess.run", side_effect=fake_install):
            ok, detail = install_model(Engine, python_executable=sys.executable)
            assert ok, detail
            managed = require_model(Engine)
            assert provider_status(Engine).installed_models == (MODEL_ID,)

            media = root / "sample.wav"
            media.write_bytes(b"RIFF")

            def fake_transcribe(command, **kwargs):
                assert command[-5] == str(managed)
                assert command[-4] == str(media)
                output = Path(command[-3])
                assert command[-2] == "cpu"
                assert command[-1] == "en"
                output.write_text(
                    "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
                    encoding="utf-8",
                )
                assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
                assert kwargs["env"]["TRANSFORMERS_OFFLINE"] == "1"
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch(__name__ + ".resolve_media_item_path", return_value=media), patch(
                __name__ + ".provider_available", return_value=True
            ), patch(__name__ + ".subprocess.run", side_effect=fake_transcribe):
                artifact = transcribe(
                    Engine,
                    "a" * 32,
                    language="en",
                    device="cpu",
                    python_executable=sys.executable,
                )
            assert artifact.kind == "transcript"
            assert artifact.media_id == "a" * 32
            assert artifact.path.is_file()

            assert remove_model(Engine)[0]
            assert not managed.exists()

        for bad_model in ("../bad", "1.7b"):
            try:
                model_dir(Engine, bad_model)
            except Qwen3AsrError:
                pass
            else:
                raise AssertionError("unsafe or unreviewed Qwen3-ASR model id was accepted")
        for bad_device in ("mps", "cuda;rm"):
            try:
                _clean_device(bad_device)
            except Qwen3AsrError:
                pass
            else:
                raise AssertionError("unsupported Qwen3-ASR device was accepted")
        try:
            _clean_language("xx")
        except Qwen3AsrError:
            pass
        else:
            raise AssertionError("unsupported Qwen3-ASR language was accepted")
