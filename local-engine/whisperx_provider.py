from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from diarization_assignment import DiarizationAssignmentError, apply_diarization
from media_library import resolve_media_item_path
from transcript_workspace import TranscriptWorkspaceError, index_transcript

PROVIDER_ID = "whisperx"
DEFAULT_DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
HF_TOKEN_ENV_NAMES = ("GALAXY_WHISPERX_HF_TOKEN", "HF_TOKEN", "HUGGINGFACE_TOKEN")
MAX_TURNS = 100_000
MAX_SPEAKERS = 64
MODEL_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,120}$")
MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")


class WhisperXError(RuntimeError):
    pass


@dataclass(frozen=True)
class WhisperXStatus:
    available: bool
    version: str
    diarization_prepared: bool
    token_configured: bool
    model: str

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": PROVIDER_ID,
            "name": "WhisperX Speaker Diarization",
            "runtimeAvailable": self.available,
            "version": self.version,
            "diarizationPrepared": self.diarization_prepared,
            "tokenConfigured": self.token_configured,
            "model": self.model,
            "explicitPrepareRequired": True,
            "localFilesOnly": True,
            "supportsSpeakerDiarization": True,
            "maxSpeakers": MAX_SPEAKERS,
        }


@dataclass(frozen=True)
class WhisperXDiarizationResult:
    media_id: str
    model: str
    turn_count: int
    speaker_count: int
    assigned_segments: int
    unmatched_segments: int

    def public_payload(self) -> dict[str, Any]:
        return {
            "mediaId": self.media_id,
            "provider": PROVIDER_ID,
            "model": self.model,
            "turnCount": self.turn_count,
            "speakerCount": self.speaker_count,
            "assignedSegments": self.assigned_segments,
            "unmatchedSegments": self.unmatched_segments,
        }


def _data_dir(engine_module) -> Path:
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir()) / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def provider_root(engine_module) -> Path:
    root = _data_dir(engine_module) / "models" / "asr" / PROVIDER_ID
    if root.is_symlink():
        raise WhisperXError("WhisperX 模型根目录不能是符号链接")
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_root(engine_module) -> Path:
    root = provider_root(engine_module) / "hf-cache"
    if root.is_symlink():
        raise WhisperXError("WhisperX 缓存目录不能是符号链接")
    root.mkdir(parents=True, exist_ok=True)
    return root


def manifest_path(engine_module) -> Path:
    return provider_root(engine_module) / "diarization.json"


def _clean_model(value: object) -> str:
    clean = str(value or DEFAULT_DIARIZATION_MODEL).strip()
    if not MODEL_RE.fullmatch(clean):
        raise WhisperXError("WhisperX diarization 模型名称无效")
    return clean


def _clean_media_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not MEDIA_ID_RE.fullmatch(clean):
        raise WhisperXError("媒体条目 ID 无效")
    return clean


def _clean_device(value: object) -> str:
    clean = str(value or "cpu").strip().lower()
    if clean not in {"cpu", "cuda"}:
        raise WhisperXError("WhisperX device 参数无效")
    return clean


def _clean_speaker_count(value: object, field: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise WhisperXError(f"{field} 无效") from exc
    if parsed < 1 or parsed > MAX_SPEAKERS:
        raise WhisperXError(f"{field} 必须在 1-{MAX_SPEAKERS} 之间")
    return parsed


def _bounded_timeout(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(60, min(parsed, maximum))


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


def _token() -> str:
    for name in HF_TOKEN_ENV_NAMES:
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def provider_available() -> bool:
    return importlib.util.find_spec("whisperx") is not None


def provider_version() -> str:
    if not provider_available():
        return ""
    try:
        return metadata.version("whisperx")[:80]
    except metadata.PackageNotFoundError:
        return "unknown"


def _load_manifest(engine_module) -> dict[str, Any] | None:
    path = manifest_path(engine_module)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("provider") != PROVIDER_ID:
        return None
    model = str(data.get("model") or "")
    if not MODEL_RE.fullmatch(model):
        return None
    cache = cache_root(engine_module)
    try:
        has_files = any(item.is_file() and not item.is_symlink() for item in cache.rglob("*"))
    except OSError:
        return None
    return data if has_files else None


def provider_status(engine_module) -> WhisperXStatus:
    manifest = _load_manifest(engine_module)
    return WhisperXStatus(
        available=provider_available(),
        version=provider_version(),
        diarization_prepared=manifest is not None,
        token_configured=bool(_token()),
        model=str(manifest.get("model")) if manifest else DEFAULT_DIARIZATION_MODEL,
    )


def _subprocess_env(cache: Path, *, token: str = "", offline: bool) -> dict[str, str]:
    env = dict(os.environ)
    for name in HF_TOKEN_ENV_NAMES:
        env.pop(name, None)
    if token:
        env["GALAXY_WHISPERX_HF_TOKEN"] = token
    env["HF_HOME"] = str(cache)
    env["HUGGINGFACE_HUB_CACHE"] = str(cache / "hub")
    env["TORCH_HOME"] = str(cache / "torch")
    if offline:
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
    else:
        env.pop("HF_HUB_OFFLINE", None)
        env.pop("TRANSFORMERS_OFFLINE", None)
    return env


def _prepare_script() -> str:
    return r'''import os, sys
from whisperx.diarize import DiarizationPipeline
cache, model = sys.argv[1:3]
token = os.environ.get("GALAXY_WHISPERX_HF_TOKEN") or None
DiarizationPipeline(model_name=model, token=token, device="cpu", cache_dir=cache)
print("ready")
'''


def prepare_diarization(
    engine_module,
    *,
    model: object = DEFAULT_DIARIZATION_MODEL,
    timeout_seconds: int = 3600,
    python_executable: object | None = None,
) -> tuple[bool, str]:
    clean_model = _clean_model(model)
    token = _token()
    if not token:
        raise WhisperXError("WhisperX diarization 首次准备需要 Hugging Face token")
    interpreter = _python_executable() if python_executable is None else Path(str(python_executable)).expanduser().resolve(strict=True)
    if interpreter is None or not interpreter.is_file() or interpreter.is_symlink():
        raise WhisperXError("Python 解释器不可用")
    if not provider_available():
        return False, "WhisperX Python runtime 未安装"

    cache = cache_root(engine_module)
    try:
        result = subprocess.run(
            [str(interpreter), "-c", _prepare_script(), str(cache), clean_model],
            capture_output=True,
            text=True,
            timeout=_bounded_timeout(timeout_seconds, default=3600, maximum=7200),
            check=False,
            env=_subprocess_env(cache, token=token, offline=False),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        return False, "WhisperX diarization 模型准备超时"
    except OSError as exc:
        return False, str(exc)[:1000]
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail[-1600:] or f"Python exited with {result.returncode}"

    manifest = manifest_path(engine_module)
    temporary = manifest.with_suffix(".tmp")
    payload = {"provider": PROVIDER_ID, "model": clean_model, "version": provider_version()}
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(manifest)
    except OSError:
        with suppress(OSError):
            temporary.unlink()
        raise
    return True, "WhisperX diarization 模型已准备"


def remove_diarization_models(engine_module) -> tuple[bool, str]:
    root = provider_root(engine_module)
    cache = root / "hf-cache"
    marker = root / "diarization.json"
    if cache.is_symlink() or marker.is_symlink():
        raise WhisperXError("拒绝删除符号链接 WhisperX 模型数据")
    try:
        if cache.exists():
            shutil.rmtree(cache)
        with suppress(FileNotFoundError):
            marker.unlink()
    except OSError as exc:
        return False, str(exc)[:1000]
    return True, "WhisperX diarization 模型已删除"


def _diarize_script() -> str:
    return r'''import json, os, sys
from whisperx.diarize import DiarizationPipeline
source, cache, model, device, min_raw, max_raw, destination = sys.argv[1:8]
token = os.environ.get("GALAXY_WHISPERX_HF_TOKEN") or None
pipeline = DiarizationPipeline(model_name=model, token=token, device=device, cache_dir=cache)
kwargs = {}
if min_raw: kwargs["min_speakers"] = int(min_raw)
if max_raw: kwargs["max_speakers"] = int(max_raw)
frame = pipeline(source, **kwargs)
rows = []
for _, row in frame.iterrows():
    rows.append({"startSeconds": float(row["start"]), "endSeconds": float(row["end"]), "speaker": str(row["speaker"])})
with open(destination, "w", encoding="utf-8") as handle:
    json.dump(rows, handle, ensure_ascii=False, separators=(",", ":"))
'''


def diarize_media(
    engine_module,
    media_id: object,
    *,
    min_speakers: object = None,
    max_speakers: object = None,
    device: object = "cpu",
    minimum_overlap_seconds: object = 0.05,
    clear_unmatched: bool = False,
    timeout_seconds: int = 7200,
    python_executable: object | None = None,
) -> WhisperXDiarizationResult:
    clean_id = _clean_media_id(media_id)
    source = resolve_media_item_path(engine_module, clean_id)
    if source is None:
        raise WhisperXError("媒体文件不可用")
    manifest = _load_manifest(engine_module)
    if manifest is None:
        raise WhisperXError("WhisperX diarization 模型尚未显式准备")
    if not provider_available():
        raise WhisperXError("WhisperX Python runtime 未安装")

    minimum = _clean_speaker_count(min_speakers, "minSpeakers")
    maximum = _clean_speaker_count(max_speakers, "maxSpeakers")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise WhisperXError("minSpeakers 不能大于 maxSpeakers")
    selected_device = _clean_device(device)
    interpreter = _python_executable() if python_executable is None else Path(str(python_executable)).expanduser().resolve(strict=True)
    if interpreter is None or not interpreter.is_file() or interpreter.is_symlink():
        raise WhisperXError("Python 解释器不可用")

    cache = cache_root(engine_module)
    model = _clean_model(manifest.get("model"))
    temporary_dir = provider_root(engine_module) / "tmp"
    if temporary_dir.is_symlink():
        raise WhisperXError("WhisperX 临时目录不能是符号链接")
    temporary_dir.mkdir(parents=True, exist_ok=True)
    output = temporary_dir / f"{clean_id}.diarization.json.tmp"
    with suppress(OSError):
        output.unlink()
    try:
        result = subprocess.run(
            [
                str(interpreter), "-c", _diarize_script(), str(source), str(cache), model,
                selected_device, str(minimum or ""), str(maximum or ""), str(output),
            ],
            capture_output=True,
            text=True,
            timeout=_bounded_timeout(timeout_seconds, default=7200, maximum=14400),
            check=False,
            env=_subprocess_env(cache, token=_token(), offline=True),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise WhisperXError("WhisperX diarization 超时") from exc
    except OSError as exc:
        raise WhisperXError(str(exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise WhisperXError(detail[-1600:] or f"Python exited with {result.returncode}")
    try:
        if not output.is_file() or output.is_symlink() or output.stat().st_size > 16 * 1024 * 1024:
            raise WhisperXError("WhisperX 未生成有效 diarization 结果")
        rows = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WhisperXError("WhisperX diarization 结果无效") from exc
    finally:
        with suppress(OSError):
            output.unlink()
    if not isinstance(rows, list) or not rows or len(rows) > MAX_TURNS:
        raise WhisperXError("WhisperX diarization turn 数量无效")

    try:
        index_transcript(engine_module, clean_id)
        assigned = apply_diarization(
            engine_module,
            clean_id,
            rows,
            minimum_overlap_seconds=minimum_overlap_seconds,
            clear_unmatched=bool(clear_unmatched),
        )
    except (TranscriptWorkspaceError, DiarizationAssignmentError) as exc:
        raise WhisperXError(str(exc)) from exc
    return WhisperXDiarizationResult(
        media_id=clean_id,
        model=model,
        turn_count=assigned.turn_count,
        speaker_count=assigned.speaker_count,
        assigned_segments=assigned.assigned_segments,
        unmatched_segments=assigned.unmatched_segments,
    )


def run_whisperx_provider_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        media = root / "media.mp4"
        media.write_bytes(b"media")

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def data_dir() -> Path:
                target = root / "data"
                target.mkdir(exist_ok=True)
                return target

        status = provider_status(Engine)
        assert status.model == DEFAULT_DIARIZATION_MODEL
        assert status.public_payload().get("token") is None

        cache = cache_root(Engine)
        (cache / "ready.bin").write_bytes(b"ready")
        manifest_path(Engine).write_text(
            json.dumps({"provider": PROVIDER_ID, "model": DEFAULT_DIARIZATION_MODEL}), encoding="utf-8"
        )
        with patch("whisperx_provider.provider_available", return_value=True), patch(
            "whisperx_provider.resolve_media_item_path", return_value=media
        ), patch("whisperx_provider.subprocess.run") as run, patch(
            "whisperx_provider.index_transcript", return_value=2
        ), patch("whisperx_provider.apply_diarization") as apply:
            run.return_value.returncode = 0
            run.return_value.stdout = ""
            run.return_value.stderr = ""
            apply.return_value.turn_count = 2
            apply.return_value.speaker_count = 2
            apply.return_value.assigned_segments = 2
            apply.return_value.unmatched_segments = 0

            def fake_run(*args, **kwargs):
                command = args[0]
                Path(command[-1]).write_text(
                    json.dumps([
                        {"startSeconds": 0.0, "endSeconds": 1.0, "speaker": "SPEAKER_00"},
                        {"startSeconds": 1.0, "endSeconds": 2.0, "speaker": "SPEAKER_01"},
                    ]), encoding="utf-8"
                )
                class Result:
                    returncode = 0
                    stdout = ""
                    stderr = ""
                return Result()

            run.side_effect = fake_run
            result = diarize_media(Engine, "a" * 32, min_speakers=1, max_speakers=2)
            assert result.speaker_count == 2 and result.assigned_segments == 2
            env = run.call_args.kwargs["env"]
            assert env["HF_HUB_OFFLINE"] == "1" and env["TRANSFORMERS_OFFLINE"] == "1"
            assert "GALAXY_WHISPERX_HF_TOKEN" not in env

        try:
            diarize_media(Engine, "../bad")
        except WhisperXError:
            pass
        else:
            raise AssertionError("unsafe media id was accepted")

        try:
            _clean_model("../bad")
        except WhisperXError:
            pass
        else:
            raise AssertionError("unsafe model id was accepted")
