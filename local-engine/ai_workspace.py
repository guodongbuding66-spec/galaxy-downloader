from __future__ import annotations

import os
import re
import subprocess
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from ai_models import (
    load_ai_model_settings,
    normalize_summary_model,
    normalize_whisper_model,
    ollama_executable,
    whisper_executable,
)
from asr_model_manager import AsrModelError, require_whisper_model
from media_library import resolve_media_item_path

MAX_TRANSCRIPT_CHARS = 400_000
MAX_SUMMARY_CHARS = 500_000
LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_-]{0,32}$")


class AiWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class AiArtifactResult:
    kind: str
    media_id: str
    path: Path
    model: str


def _ai_data_dir(engine_module) -> Path:
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir())
    target = root / "ai"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _clean_media_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{16,64}", clean):
        raise AiWorkspaceError("媒体条目 ID 无效")
    return clean


def transcript_path(engine_module, media_id: object) -> Path:
    clean = _clean_media_id(media_id)
    target = _ai_data_dir(engine_module) / "transcripts"
    target.mkdir(parents=True, exist_ok=True)
    return target / f"{clean}.srt"


def summary_path(engine_module, media_id: object) -> Path:
    clean = _clean_media_id(media_id)
    target = _ai_data_dir(engine_module) / "summaries"
    target.mkdir(parents=True, exist_ok=True)
    return target / f"{clean}.md"


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _bounded_timeout(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _atomic_write_text(destination: Path, text: str) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(destination)
    except Exception:
        with suppress(OSError):
            temporary.unlink()
        raise


def _atomic_copy_text(source: Path, destination: Path) -> None:
    text = source.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_TRANSCRIPT_CHARS:
        raise AiWorkspaceError("转写结果过大")
    _atomic_write_text(destination, text)


def _whisper_command(
    executable: Path,
    source: Path,
    checkpoint: Path,
    output_dir: Path,
    language: str,
) -> list[str]:
    command = [
        str(executable),
        str(source),
        "--model",
        str(checkpoint),
        "--output_format",
        "srt",
        "--output_dir",
        str(output_dir),
        "--verbose",
        "False",
    ]
    if language:
        command.extend(["--language", language])
    return command


def transcribe_media(
    engine_module,
    media_id: object,
    *,
    language: object = "",
    model: object | None = None,
    timeout_seconds: int = 3600,
) -> AiArtifactResult:
    clean_id = _clean_media_id(media_id)
    source = resolve_media_item_path(engine_module, clean_id)
    if source is None:
        raise AiWorkspaceError("媒体文件不存在或已移出 Galaxy 下载目录")

    executable = whisper_executable(engine_module)
    if executable is None:
        raise AiWorkspaceError("未检测到 Whisper CLI。请先安装 openai-whisper 并确保 whisper 命令可用。")

    settings = load_ai_model_settings(engine_module)
    chosen_model = normalize_whisper_model(model if model is not None else settings.whisper_model)
    chosen_language = str(language or "").strip()
    if chosen_language and not LANGUAGE_RE.fullmatch(chosen_language):
        raise AiWorkspaceError("语言代码无效")
    try:
        checkpoint = require_whisper_model(engine_module, chosen_model)
    except AsrModelError as exc:
        raise AiWorkspaceError(str(exc)) from exc

    destination = transcript_path(engine_module, clean_id)
    with tempfile.TemporaryDirectory(prefix="galaxy-whisper-") as directory:
        output_dir = Path(directory)
        command = _whisper_command(executable, source, checkpoint, output_dir, chosen_language)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=_bounded_timeout(timeout_seconds, default=3600, minimum=60, maximum=7200),
                check=False,
                creationflags=_creation_flags(),
            )
        except subprocess.TimeoutExpired as exc:
            raise AiWorkspaceError("Whisper 转写超时") from exc
        except OSError as exc:
            raise AiWorkspaceError(str(exc)) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise AiWorkspaceError(detail[-1500:] or f"Whisper exited with {result.returncode}")

        expected = output_dir / f"{source.stem}.srt"
        candidates = [expected] if expected.is_file() else sorted(output_dir.glob("*.srt"))
        if not candidates:
            raise AiWorkspaceError("Whisper 未生成 SRT 字幕")
        _atomic_copy_text(candidates[0], destination)

    return AiArtifactResult("transcript", clean_id, destination, chosen_model)


def _read_transcript(engine_module, media_id: str) -> str:
    path = transcript_path(engine_module, media_id)
    if not path.is_file() or path.is_symlink():
        raise AiWorkspaceError("尚未生成字幕，请先执行 Whisper 转写")
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise AiWorkspaceError("字幕为空")
    return text[:MAX_TRANSCRIPT_CHARS]


def summarize_media(
    engine_module,
    media_id: object,
    *,
    model: object | None = None,
    timeout_seconds: int = 900,
) -> AiArtifactResult:
    clean_id = _clean_media_id(media_id)
    if resolve_media_item_path(engine_module, clean_id) is None:
        raise AiWorkspaceError("媒体文件不存在或已移出 Galaxy 下载目录")

    settings = load_ai_model_settings(engine_module)
    chosen_model = normalize_summary_model(model if model is not None else settings.summary_model)
    if not chosen_model:
        raise AiWorkspaceError("请先在 AI 模型管理中选择 Ollama 摘要模型")
    executable = ollama_executable(engine_module)
    if executable is None:
        raise AiWorkspaceError("未检测到 Ollama")

    transcript = _read_transcript(engine_module, clean_id)
    prompt = (
        "你是本地媒体学习助手。请只根据下面字幕内容生成结构化中文摘要，不要编造字幕中没有的信息。\n"
        "输出 Markdown，包含：核心结论、关键要点、时间线/章节（能从字幕判断时）、术语与待核实事项。\n\n"
        "字幕：\n" + transcript
    )
    try:
        result = subprocess.run(
            [str(executable), "run", chosen_model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=_bounded_timeout(timeout_seconds, default=900, minimum=60, maximum=1800),
            check=False,
            creationflags=_creation_flags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise AiWorkspaceError("Ollama 摘要生成超时") from exc
    except OSError as exc:
        raise AiWorkspaceError(str(exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise AiWorkspaceError(detail[-1500:] or f"Ollama exited with {result.returncode}")

    output = (result.stdout or "").strip()
    if not output:
        raise AiWorkspaceError("Ollama 没有返回摘要")
    destination = summary_path(engine_module, clean_id)
    _atomic_write_text(destination, output[:MAX_SUMMARY_CHARS] + "\n")
    return AiArtifactResult("summary", clean_id, destination, chosen_model)


def run_ai_workspace_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def data_dir() -> Path:
                return root / "data"

        media_id = "a" * 32
        transcript = transcript_path(Engine, media_id)
        summary = summary_path(Engine, media_id)
        assert transcript == root / "data" / "ai" / "transcripts" / f"{media_id}.srt"
        assert summary == root / "data" / "ai" / "summaries" / f"{media_id}.md"
        assert _bounded_timeout("bad", default=900, minimum=60, maximum=1800) == 900
        assert _bounded_timeout(1, default=900, minimum=60, maximum=1800) == 60
        assert _bounded_timeout(9999, default=900, minimum=60, maximum=1800) == 1800

        source = root / "source.srt"
        source.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
        _atomic_copy_text(source, transcript)
        assert transcript.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
        assert not transcript.with_suffix(".srt.tmp").exists()

        checkpoint = root / "model.pt"
        command = _whisper_command(root / "whisper", root / "audio.mp3", checkpoint, root / "out", "zh")
        assert command[command.index("--model") + 1] == str(checkpoint)
        assert command[-2:] == ["--language", "zh"]

        try:
            transcript_path(Engine, "../bad")
        except AiWorkspaceError:
            pass
        else:
            raise AssertionError("unsafe media id was accepted")
