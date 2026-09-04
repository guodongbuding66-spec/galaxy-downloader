from __future__ import annotations

import importlib.util
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

PROVIDER_ID = "sensevoice"
MODEL_ID = "small"
MODELS = (MODEL_ID,)
ASR_REPOSITORY = "iic/SenseVoiceSmall"
VAD_REPOSITORY = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
ASR_REQUIRED_FILES = ("config.yaml", "model.pt")
VAD_REQUIRED_FILES = ("config.yaml", "model.pt")
MIN_ASR_BYTES = 1024 * 1024
MIN_VAD_BYTES = 1024
MAX_ASR_BYTES = 5 * 1024 * 1024 * 1024
MAX_VAD_BYTES = 512 * 1024 * 1024
MAX_SNAPSHOT_FILES = 20_000
MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
LANGUAGES = ("auto", "zh", "en", "yue", "ja", "ko", "nospeech")
DEVICE_RE = re.compile(r"^(?:cpu|mps|cuda(?::[0-9]{1,2})?)$")


class SenseVoiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SenseVoiceStatus:
    available: bool
    installer_available: bool
    version: str
    installed_models: tuple[str, ...]

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": PROVIDER_ID,
            "name": "SenseVoice",
            "available": self.available,
            "installerAvailable": self.installer_available,
            "version": self.version,
            "models": list(MODELS),
            "installedModels": list(self.installed_models),
            "languages": list(LANGUAGES),
            "installExplicitlyRequired": True,
            "supportsLocalFilesOnly": True,
            "supportsCpu": True,
            "supportsGpu": True,
        }


def _data_dir(engine_module) -> Path:
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir()) / "data"
    if root.is_symlink():
        raise SenseVoiceError("ASR 数据目录不能是符号链接")
    root.mkdir(parents=True, exist_ok=True)
    return root


def model_root(engine_module) -> Path:
    root = _data_dir(engine_module) / "models" / "asr" / PROVIDER_ID
    if root.is_symlink():
        raise SenseVoiceError("SenseVoice 模型根目录不能是符号链接")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _clean_model(value: object) -> str:
    model = str(value or "").strip().lower()
    if model not in MODELS:
        raise SenseVoiceError("SenseVoice 模型名称无效")
    return model


def model_dir(engine_module, model: object = MODEL_ID) -> Path:
    return model_root(engine_module) / _clean_model(model)


def _snapshot_dir(engine_module, model: object, component: str) -> Path:
    if component not in {"asr", "vad"}:
        raise SenseVoiceError("SenseVoice 模型组件无效")
    return model_dir(engine_module, model) / component


def _snapshot_is_safe(
    directory: Path,
    required_files: tuple[str, ...],
    *,
    minimum_bytes: int,
    maximum_bytes: int,
) -> bool:
    if directory.is_symlink() or not directory.is_dir():
        return False
    for name in required_files:
        candidate = directory / name
        if candidate.is_symlink() or not candidate.is_file():
            return False

    count = 0
    total = 0
    try:
        for current_root, directory_names, file_names in os.walk(directory, followlinks=False):
            current = Path(current_root)
            for name in directory_names:
                item = current / name
                if item.is_symlink():
                    return False
            for name in file_names:
                item = current / name
                if item.is_symlink() or not item.is_file():
                    return False
                count += 1
                if count > MAX_SNAPSHOT_FILES:
                    return False
                total += item.stat().st_size
                if total > maximum_bytes:
                    return False
    except OSError:
        return False
    return total >= minimum_bytes


def _safe_model_directory(engine_module, model: object = MODEL_ID) -> Path | None:
    target = model_dir(engine_module, model)
    if target.is_symlink() or not target.is_dir():
        return None
    asr = target / "asr"
    vad = target / "vad"
    if not _snapshot_is_safe(
        asr,
        ASR_REQUIRED_FILES,
        minimum_bytes=MIN_ASR_BYTES,
        maximum_bytes=MAX_ASR_BYTES,
    ):
        return None
    if not _snapshot_is_safe(
        vad,
        VAD_REQUIRED_FILES,
        minimum_bytes=MIN_VAD_BYTES,
        maximum_bytes=MAX_VAD_BYTES,
    ):
        return None
    return target


def provider_available() -> bool:
    return importlib.util.find_spec("funasr") is not None


def installer_available() -> bool:
    return importlib.util.find_spec("modelscope") is not None


def provider_version() -> str:
    if not provider_available():
        return ""
    try:
        return metadata.version("funasr")[:80]
    except metadata.PackageNotFoundError:
        return "unknown"


def provider_status(engine_module) -> SenseVoiceStatus:
    installed = tuple(model for model in MODELS if _safe_model_directory(engine_module, model) is not None)
    return SenseVoiceStatus(
        provider_available(),
        installer_available(),
        provider_version(),
        installed,
    )


def require_model(engine_module, model: object = MODEL_ID) -> Path:
    clean = _clean_model(model)
    directory = _safe_model_directory(engine_module, clean)
    if directory is None:
        raise SenseVoiceError(
            f"SenseVoice 模型 {clean} 尚未显式安装。请先执行 ASR Provider 的 install_model。"
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
        raise SenseVoiceError("Python 解释器不可用") from exc
    if candidate.is_symlink() or not candidate.is_file():
        raise SenseVoiceError("Python 解释器不可用")
    return candidate


def _bounded_timeout(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(60, min(parsed, maximum))


def _install_script() -> str:
    return (
        "import sys; from modelscope.hub.snapshot_download import snapshot_download; "
        "snapshot_download(sys.argv[1], local_dir=sys.argv[2], local_files_only=False); "
        "snapshot_download(sys.argv[3], local_dir=sys.argv[4], local_files_only=False); "
        "print('ready')"
    )


def _safe_child(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def install_model(
    engine_module,
    model: object = MODEL_ID,
    *,
    timeout_seconds: int = 7200,
    python_executable: object | None = None,
) -> tuple[bool, str]:
    clean = _clean_model(model)
    if _safe_model_directory(engine_module, clean) is not None:
        return True, "模型已安装"
    interpreter = _resolve_python(python_executable)
    if interpreter is None:
        return False, "未检测到可运行 FunASR 的 Python"

    root = model_root(engine_module)
    target = model_dir(engine_module, clean)
    if target.is_symlink() or not _safe_child(root, target):
        raise SenseVoiceError("SenseVoice 模型目录无效")

    staging = root / f".{clean}.{uuid.uuid4().hex}.part"
    backup = root / f".{clean}.{uuid.uuid4().hex}.backup"
    if staging.is_symlink() or backup.is_symlink():
        raise SenseVoiceError("SenseVoice 临时模型目录无效")
    staging.mkdir(parents=True, exist_ok=False)
    asr_stage = staging / "asr"
    vad_stage = staging / "vad"

    try:
        result = subprocess.run(
            [
                str(interpreter),
                "-c",
                _install_script(),
                ASR_REPOSITORY,
                str(asr_stage),
                VAD_REPOSITORY,
                str(vad_stage),
            ],
            capture_output=True,
            text=True,
            timeout=_bounded_timeout(timeout_seconds, default=7200, maximum=14_400),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(staging, ignore_errors=True)
        return False, "SenseVoice 模型安装超时"
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return False, str(exc)[:1000]

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        shutil.rmtree(staging, ignore_errors=True)
        return False, detail[-1200:] or f"Python exited with {result.returncode}"
    if not _snapshot_is_safe(
        asr_stage,
        ASR_REQUIRED_FILES,
        minimum_bytes=MIN_ASR_BYTES,
        maximum_bytes=MAX_ASR_BYTES,
    ) or not _snapshot_is_safe(
        vad_stage,
        VAD_REQUIRED_FILES,
        minimum_bytes=MIN_VAD_BYTES,
        maximum_bytes=MAX_VAD_BYTES,
    ):
        shutil.rmtree(staging, ignore_errors=True)
        return False, "模型下载完成但完整性检查失败"

    moved_old = False
    try:
        if target.exists():
            if target.is_symlink():
                raise SenseVoiceError("拒绝替换符号链接模型目录")
            target.replace(backup)
            moved_old = True
        staging.replace(target)
        if moved_old:
            shutil.rmtree(backup, ignore_errors=True)
    except (OSError, SenseVoiceError) as exc:
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
        raise SenseVoiceError("拒绝删除符号链接模型目录")
    if not _safe_child(root, target):
        raise SenseVoiceError("SenseVoice 模型目录无效")
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
    if bool(info.get("gpuAvailable")) or vram >= 4:
        device = "cuda:0"
    elif bool(info.get("metalAvailable")):
        device = "mps"
    else:
        device = "cpu"
    return {"model": MODEL_ID, "device": device, "profile": mode}


def _clean_language(value: object) -> str:
    language = str(value or "auto").strip().lower()
    if language not in LANGUAGES:
        raise SenseVoiceError("SenseVoice 语言参数无效")
    return language


def _clean_device(value: object) -> str:
    device = str(value or "cpu").strip().lower()
    if not DEVICE_RE.fullmatch(device):
        raise SenseVoiceError("SenseVoice 设备参数无效")
    return device


def _transcribe_script() -> str:
    return r'''import sys
from pathlib import Path
from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess


def stamp(ms):
    value = max(0, int(round(float(ms))))
    hours, value = divmod(value, 3600000)
    minutes, value = divmod(value, 60000)
    seconds, value = divmod(value, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{value:03d}"


def clean_text(value):
    return " ".join(str(rich_transcription_postprocess(value or "")).split()).strip()


asr_dir, vad_dir, source, destination, language, device = sys.argv[1:7]
if not Path(asr_dir).is_dir() or not Path(vad_dir).is_dir():
    raise RuntimeError("managed SenseVoice model is unavailable")
model = AutoModel(
    model=asr_dir,
    vad_model=vad_dir,
    vad_kwargs={"max_single_segment_time": 30000},
    device=device,
    disable_update=True,
    disable_pbar=True,
)
res = model.generate(
    input=source,
    cache={},
    language=language,
    use_itn=True,
    batch_size_s=60,
    merge_vad=True,
    merge_length_s=15,
    output_timestamp=True,
    sentence_timestamp=True,
)
if not res or not isinstance(res[0], dict):
    raise RuntimeError("SenseVoice returned no result")
result = res[0]
rows = []
sentences = result.get("sentence_info") or []
for sentence in sentences:
    if not isinstance(sentence, dict):
        continue
    text = clean_text(sentence.get("text", sentence.get("sentence", "")))
    try:
        start = float(sentence.get("start"))
        end = float(sentence.get("end"))
    except (TypeError, ValueError):
        continue
    if text and end > start >= 0:
        rows.append((start, end, text))
if not rows:
    text = clean_text(result.get("text", ""))
    timestamps = result.get("timestamp") or []
    valid = [item for item in timestamps if isinstance(item, (list, tuple)) and len(item) >= 2]
    if text and valid:
        try:
            start = float(valid[0][0])
            end = float(valid[-1][1])
        except (TypeError, ValueError):
            start = end = 0
        if end > start >= 0:
            rows.append((start, end, text))
if not rows:
    raise RuntimeError("SenseVoice returned no timestamped speech")
content = []
for index, (start, end, text) in enumerate(rows, 1):
    content.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
Path(destination).write_text("\n".join(content), encoding="utf-8")
'''


def transcribe(
    engine_module,
    media_id: object,
    *,
    model: object = MODEL_ID,
    language: object = "auto",
    device: object = "cpu",
    timeout_seconds: int = 7200,
    python_executable: object | None = None,
) -> AiArtifactResult:
    clean_id = str(media_id or "").strip().lower()
    if not MEDIA_ID_RE.fullmatch(clean_id):
        raise SenseVoiceError("媒体条目 ID 无效")
    source = resolve_media_item_path(engine_module, clean_id)
    if source is None:
        raise SenseVoiceError("媒体文件不可用")
    managed = require_model(engine_module, model)
    asr_directory = managed / "asr"
    vad_directory = managed / "vad"
    selected_language = _clean_language(language)
    selected_device = _clean_device(device)
    interpreter = _resolve_python(python_executable)
    if interpreter is None:
        raise SenseVoiceError("Python 解释器不可用")

    destination = transcript_path(engine_module, clean_id)
    environment = os.environ.copy()
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    environment["MODELSCOPE_OFFLINE"] = "1"
    with tempfile.TemporaryDirectory(prefix="galaxy-sensevoice-") as directory:
        temporary = Path(directory) / "transcript.srt"
        try:
            result = subprocess.run(
                [
                    str(interpreter),
                    "-c",
                    _transcribe_script(),
                    str(asr_directory),
                    str(vad_directory),
                    str(source),
                    str(temporary),
                    selected_language,
                    selected_device,
                ],
                capture_output=True,
                text=True,
                timeout=_bounded_timeout(timeout_seconds, default=7200, maximum=14_400),
                check=False,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise SenseVoiceError("SenseVoice 转写超时") from exc
        except OSError as exc:
            raise SenseVoiceError(str(exc)[:1600]) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise SenseVoiceError(detail[-1600:] or f"Python exited with {result.returncode}")
        if not temporary.is_file() or temporary.is_symlink() or temporary.stat().st_size <= 0:
            raise SenseVoiceError("SenseVoice 未生成有效 SRT")
        target_tmp = destination.with_suffix(".srt.tmp")
        try:
            shutil.copyfile(temporary, target_tmp)
            target_tmp.replace(destination)
        except OSError:
            with suppress(OSError):
                target_tmp.unlink()
            raise
    return AiArtifactResult("transcript", clean_id, destination, f"{PROVIDER_ID}:{_clean_model(model)}")


def run_sensevoice_provider_self_test() -> None:
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
        assert recommend({"metalAvailable": True})["device"] == "mps"
        assert "disable_update=True" in _transcribe_script()
        assert "vad_model=vad_dir" in _transcribe_script()

        def fake_install(command, **_kwargs):
            asr = Path(command[-3])
            vad = Path(command[-1])
            asr.mkdir(parents=True, exist_ok=True)
            vad.mkdir(parents=True, exist_ok=True)
            (asr / "config.yaml").write_text("model: SenseVoiceSmall", encoding="utf-8")
            (asr / "model.pt").write_bytes(b"x" * MIN_ASR_BYTES)
            (vad / "config.yaml").write_text("model: FsmnVAD", encoding="utf-8")
            (vad / "model.pt").write_bytes(b"x" * MIN_VAD_BYTES)
            return SimpleNamespace(returncode=0, stdout="ready", stderr="")

        with patch("sensevoice_provider.subprocess.run", side_effect=fake_install):
            ok, detail = install_model(Engine, python_executable=sys.executable)
        assert ok, detail
        managed = require_model(Engine)
        assert managed == model_dir(Engine)
        assert provider_status(Engine).installed_models == (MODEL_ID,)

        media = root / "sample.wav"
        media.write_bytes(b"RIFF")

        def fake_transcribe(command, **kwargs):
            assert command[-6] == str(managed / "asr")
            assert command[-5] == str(managed / "vad")
            output = Path(command[-3])
            output.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
            assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
            assert kwargs["env"]["MODELSCOPE_OFFLINE"] == "1"
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("sensevoice_provider.resolve_media_item_path", return_value=media), patch(
            "sensevoice_provider.subprocess.run", side_effect=fake_transcribe
        ):
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
        try:
            model_dir(Engine, "../bad")
        except SenseVoiceError:
            pass
        else:
            raise AssertionError("unsafe SenseVoice model id was accepted")
        try:
            _clean_device("cuda;rm")
        except SenseVoiceError:
            pass
        else:
            raise AssertionError("unsafe SenseVoice device was accepted")
