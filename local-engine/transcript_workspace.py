from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_workspace import AiArtifactResult, AiWorkspaceError, transcript_path, transcribe_media
from media_library import resolve_media_item_path
from runtime_storage import state_dir as runtime_state_dir

DATABASE_FILENAME = "transcripts.sqlite3"
MAX_SEGMENTS = 100_000
MAX_SEGMENT_CHARS = 8_000
MAX_SEARCH_RESULTS = 500
TIME_RE = re.compile(r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})")
SPEAKER_PREFIX_RE = re.compile(r"^\s*(?:\[|\()?\s*(speaker\s*[A-Za-z0-9_-]+)\s*(?:\]|\))?\s*[:：-]?\s*", re.I)
ASR_ADAPTERS = {
    "whisper": ("whisper",),
    "whisperx": ("whisperx",),
    "sensevoice": ("galaxy-sensevoice-asr",),
    "parakeet": ("galaxy-parakeet-asr",),
    "qwen3-asr": ("galaxy-qwen3-asr",),
}


class TranscriptWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranscriptSegment:
    index: int
    start_seconds: float
    end_seconds: float
    text: str
    speaker: str = ""

    def public_payload(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "startSeconds": self.start_seconds,
            "endSeconds": self.end_seconds,
            "text": self.text,
            "speaker": self.speaker,
        }


def _db_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / DATABASE_FILENAME


def _connect(engine_module) -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS transcript_segments (
            media_id TEXT NOT NULL,
            segment_index INTEGER NOT NULL,
            start_seconds REAL NOT NULL,
            end_seconds REAL NOT NULL,
            speaker TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            PRIMARY KEY(media_id, segment_index)
        );
        CREATE INDEX IF NOT EXISTS idx_transcript_media_time
          ON transcript_segments(media_id, start_seconds);
        CREATE INDEX IF NOT EXISTS idx_transcript_speaker
          ON transcript_segments(media_id, speaker);
        """
    )
    return connection


def _seconds(match: re.Match[str]) -> float:
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + int(match.group("ms")) / 1000.0
    )


def parse_srt(text: str) -> list[TranscriptSegment]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n{2,}", normalized.strip())
    result: list[TranscriptSegment] = []
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue
        time_index = next((i for i, line in enumerate(lines[:3]) if "-->" in line), -1)
        if time_index < 0:
            continue
        parts = [part.strip() for part in lines[time_index].split("-->", 1)]
        if len(parts) != 2:
            continue
        start_match = TIME_RE.search(parts[0])
        end_match = TIME_RE.search(parts[1])
        if not start_match or not end_match:
            continue
        body = " ".join(lines[time_index + 1 :]).strip()[:MAX_SEGMENT_CHARS]
        if not body:
            continue
        speaker = ""
        prefix = SPEAKER_PREFIX_RE.match(body)
        if prefix:
            speaker = " ".join(prefix.group(1).split())[:80]
            body = body[prefix.end() :].strip() or body
        result.append(
            TranscriptSegment(
                index=len(result) + 1,
                start_seconds=round(_seconds(start_match), 3),
                end_seconds=round(_seconds(end_match), 3),
                text=body,
                speaker=speaker,
            )
        )
        if len(result) >= MAX_SEGMENTS:
            break
    return result


def index_transcript(engine_module, media_id: object, *, path: Path | None = None) -> int:
    clean_id = str(media_id or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{16,64}", clean_id):
        raise TranscriptWorkspaceError("媒体条目 ID 无效")
    if resolve_media_item_path(engine_module, clean_id) is None:
        raise TranscriptWorkspaceError("媒体不存在或已离开 Galaxy 下载目录")
    source = path or transcript_path(engine_module, clean_id)
    if not source.is_file() or source.is_symlink():
        raise TranscriptWorkspaceError("字幕文件不存在")
    segments = parse_srt(source.read_text(encoding="utf-8", errors="replace"))
    if not segments:
        raise TranscriptWorkspaceError("字幕中没有可索引的时间片段")
    with closing(_connect(engine_module)) as connection:
        connection.execute("DELETE FROM transcript_segments WHERE media_id=?", (clean_id,))
        connection.executemany(
            "INSERT INTO transcript_segments(media_id, segment_index, start_seconds, end_seconds, speaker, text) VALUES(?,?,?,?,?,?)",
            [(clean_id, item.index, item.start_seconds, item.end_seconds, item.speaker, item.text) for item in segments],
        )
        connection.commit()
    return len(segments)


def transcript_segments(engine_module, media_id: object, *, limit: int = 1000) -> list[dict[str, Any]]:
    clean_id = str(media_id or "").strip().lower()
    safe_limit = max(1, min(int(limit), 10_000))
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT * FROM transcript_segments WHERE media_id=? ORDER BY segment_index LIMIT ?",
            (clean_id, safe_limit),
        ).fetchall()
    return [
        TranscriptSegment(
            index=int(row["segment_index"]),
            start_seconds=float(row["start_seconds"]),
            end_seconds=float(row["end_seconds"]),
            speaker=str(row["speaker"]),
            text=str(row["text"]),
        ).public_payload()
        for row in rows
    ]


def search_transcript(
    engine_module,
    query: object,
    *,
    media_id: object = "",
    speaker: object = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    text = " ".join(str(query or "").split()).strip()[:200]
    clean_media = str(media_id or "").strip().lower()
    clean_speaker = " ".join(str(speaker or "").split()).strip()[:80]
    safe_limit = max(1, min(int(limit), MAX_SEARCH_RESULTS))
    clauses: list[str] = []
    params: list[object] = []
    if clean_media:
        if not re.fullmatch(r"[a-f0-9]{16,64}", clean_media):
            return []
        clauses.append("media_id=?")
        params.append(clean_media)
    if text:
        clauses.append("LOWER(text) LIKE ?")
        params.append(f"%{text.lower()}%")
    if clean_speaker:
        clauses.append("LOWER(speaker)=?")
        params.append(clean_speaker.lower())
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(safe_limit)
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            f"SELECT * FROM transcript_segments{where} ORDER BY media_id, start_seconds LIMIT ?",
            params,
        ).fetchall()
    return [
        {
            "mediaId": str(row["media_id"]),
            "index": int(row["segment_index"]),
            "startSeconds": float(row["start_seconds"]),
            "endSeconds": float(row["end_seconds"]),
            "speaker": str(row["speaker"]),
            "text": str(row["text"]),
        }
        for row in rows
    ]


def relabel_speaker(engine_module, media_id: object, old_label: object, new_label: object) -> int:
    clean_id = str(media_id or "").strip().lower()
    old = " ".join(str(old_label or "").split()).strip()[:80]
    new = " ".join(str(new_label or "").split()).strip()[:80]
    if not re.fullmatch(r"[a-f0-9]{16,64}", clean_id) or not old or not new:
        raise TranscriptWorkspaceError("说话人标签无效")
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute(
            "UPDATE transcript_segments SET speaker=? WHERE media_id=? AND LOWER(speaker)=LOWER(?)",
            (new, clean_id, old),
        )
        connection.commit()
        return max(0, int(cursor.rowcount))


def asr_provider_status(engine_module) -> list[dict[str, Any]]:
    roots: list[Path] = []
    accessor = getattr(engine_module, "tools_dir", None)
    if callable(accessor):
        try:
            roots.append(Path(accessor()))
        except (OSError, RuntimeError, TypeError, ValueError):
            roots = list(roots)
    result: list[dict[str, Any]] = []
    for provider, executable_names in ASR_ADAPTERS.items():
        executable = ""
        for name in executable_names:
            found = shutil.which(name)
            if found:
                executable = found
                break
            for root in roots:
                for candidate in (root / provider / "bin" / name, root / provider / name, root / "bin" / name):
                    if candidate.is_file() and not candidate.is_symlink():
                        executable = str(candidate)
                        break
                if executable:
                    break
        result.append(
            {
                "id": provider,
                "ready": bool(executable),
                "executable": Path(executable).name if executable else "",
                "diarization": provider == "whisperx",
                "protocol": "builtin" if provider in {"whisper", "whisperx"} else "galaxy-asr-adapter-v1",
            }
        )
    return result


def _adapter_executable(engine_module, provider: str) -> Path | None:
    status = next((item for item in asr_provider_status(engine_module) if item["id"] == provider and item["ready"]), None)
    if status is None:
        return None
    name = str(status["executable"])
    resolved = shutil.which(name)
    if resolved:
        return Path(resolved)
    accessor = getattr(engine_module, "tools_dir", None)
    if callable(accessor):
        root = Path(accessor())
        for candidate in (root / provider / "bin" / name, root / provider / name, root / "bin" / name):
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
    return None


def transcribe_with_asr(
    engine_module,
    media_id: object,
    *,
    provider: str = "whisper",
    model: str = "base",
    language: str = "",
    diarize: bool = False,
    speaker_count: int = 0,
    timeout_seconds: int = 7200,
) -> AiArtifactResult:
    selected = str(provider or "whisper").strip().lower()
    if selected == "whisper":
        result = transcribe_media(engine_module, media_id, model=model, language=language, timeout_seconds=timeout_seconds)
        index_transcript(engine_module, media_id, path=result.path)
        return result

    clean_id = str(media_id or "").strip().lower()
    source = resolve_media_item_path(engine_module, clean_id)
    if source is None:
        raise TranscriptWorkspaceError("媒体文件不可用")
    executable = _adapter_executable(engine_module, selected)
    if executable is None:
        raise TranscriptWorkspaceError(f"ASR Provider 未就绪：{selected}")
    destination = transcript_path(engine_module, clean_id)

    if selected == "whisperx":
        with tempfile.TemporaryDirectory(prefix="galaxy-whisperx-") as directory:
            output = Path(directory)
            command = [str(executable), str(source), "--model", str(model or "base")[:80], "--output_dir", str(output), "--output_format", "srt"]
            if language:
                command.extend(["--language", str(language)[:32]])
            if diarize:
                command.append("--diarize")
                if 1 <= int(speaker_count or 0) <= 32:
                    command.extend(["--min_speakers", str(int(speaker_count)), "--max_speakers", str(int(speaker_count))])
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=max(60, min(int(timeout_seconds), 14400)), check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
            except subprocess.TimeoutExpired as exc:
                raise TranscriptWorkspaceError("WhisperX 转写超时") from exc
            if completed.returncode != 0:
                raise TranscriptWorkspaceError((completed.stderr or completed.stdout or "WhisperX failed")[-1600:])
            candidates = sorted(output.glob("*.srt"))
            if not candidates:
                raise TranscriptWorkspaceError("WhisperX 未生成 SRT")
            destination.write_text(candidates[0].read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    else:
        request = {
            "protocol": "galaxy-asr-adapter-v1",
            "source": str(source),
            "destination": str(destination),
            "model": str(model or "")[:100],
            "language": str(language or "")[:32],
            "diarize": bool(diarize),
            "speakerCount": max(0, min(int(speaker_count or 0), 32)),
        }
        try:
            completed = subprocess.run(
                [str(executable), "--galaxy-asr-json"],
                input=json.dumps(request),
                capture_output=True,
                text=True,
                timeout=max(60, min(int(timeout_seconds), 14400)),
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise TranscriptWorkspaceError(f"{selected} 转写超时") from exc
        if completed.returncode != 0 or not destination.is_file():
            raise TranscriptWorkspaceError((completed.stderr or completed.stdout or f"{selected} adapter failed")[-1600:])

    index_transcript(engine_module, clean_id, path=destination)
    return AiArtifactResult("transcript", clean_id, destination, f"{selected}:{model}")


def run_transcript_workspace_self_test() -> None:
    sample = "1\n00:00:01,000 --> 00:00:02,500\n[Speaker 1] Hello world\n\n2\n00:00:03,000 --> 00:00:04,000\nSpeaker 2: Next line\n"
    rows = parse_srt(sample)
    assert len(rows) == 2
    assert rows[0].speaker.lower() == "speaker 1"
    assert rows[0].start_seconds == 1.0
    assert rows[1].text == "Next line"
    ids = {item["id"] for item in asr_provider_status(object())}
    assert {"whisper", "whisperx", "sensevoice", "parakeet", "qwen3-asr"}.issubset(ids)
