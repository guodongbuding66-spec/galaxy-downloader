from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_workspace import transcript_path
from media_library import resolve_media_item_path
from runtime_storage import state_dir as runtime_state_dir

DATABASE_FILENAME = "transcripts.sqlite3"
SCHEMA_VERSION = 1
MAX_SEGMENTS = 100_000
MAX_SEGMENT_CHARS = 8_000
MAX_TRANSCRIPT_BYTES = 16 * 1024 * 1024
MAX_SEARCH_RESULTS = 500
TIME_RE = re.compile(r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})")
SPEAKER_PREFIX_RE = re.compile(r"^\s*(?:\[|\()?\s*(speaker\s*[A-Za-z0-9_-]+)\s*(?:\]|\))?\s*[:：-]?\s*", re.I)


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
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    _ensure_schema(connection)
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS transcript_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
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
    row = connection.execute("SELECT value FROM transcript_meta WHERE key='schema_version'").fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO transcript_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    else:
        try:
            version = int(row["value"])
        except (TypeError, ValueError) as exc:
            raise TranscriptWorkspaceError("Transcript 数据库版本无效") from exc
        if version != SCHEMA_VERSION:
            raise TranscriptWorkspaceError(f"不支持的 Transcript 数据库版本：{version}")
    connection.commit()


def _clean_media_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{16,64}", clean):
        raise TranscriptWorkspaceError("媒体条目 ID 无效")
    return clean


def _safe_limit(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, maximum))


def _seconds(match: re.Match[str]) -> float | None:
    hours = int(match.group("h"))
    minutes = int(match.group("m"))
    seconds = int(match.group("s"))
    millis = int(match.group("ms"))
    if minutes > 59 or seconds > 59 or millis > 999:
        return None
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


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
        start_seconds = _seconds(start_match)
        end_seconds = _seconds(end_match)
        if start_seconds is None or end_seconds is None or end_seconds < start_seconds:
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
                start_seconds=round(start_seconds, 3),
                end_seconds=round(end_seconds, 3),
                text=body,
                speaker=speaker,
            )
        )
        if len(result) >= MAX_SEGMENTS:
            break
    return result


def index_transcript(engine_module, media_id: object) -> int:
    clean_id = _clean_media_id(media_id)
    if resolve_media_item_path(engine_module, clean_id) is None:
        raise TranscriptWorkspaceError("媒体不存在或已离开 Galaxy 下载目录")
    source = transcript_path(engine_module, clean_id)
    if not source.is_file() or source.is_symlink():
        raise TranscriptWorkspaceError("字幕文件不存在")
    try:
        if source.stat().st_size > MAX_TRANSCRIPT_BYTES:
            raise TranscriptWorkspaceError("字幕文件超过 16 MB 上限")
        text = source.read_text(encoding="utf-8", errors="replace")
    except TranscriptWorkspaceError:
        raise
    except OSError as exc:
        raise TranscriptWorkspaceError(str(exc)) from exc
    segments = parse_srt(text)
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
    try:
        clean_id = _clean_media_id(media_id)
    except TranscriptWorkspaceError:
        return []
    safe_limit = _safe_limit(limit, default=1000, maximum=10_000)
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


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _optional_seconds(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed)


def search_transcript(
    engine_module,
    query: object,
    *,
    media_id: object = "",
    speaker: object = "",
    start_seconds: object = None,
    end_seconds: object = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    text = " ".join(str(query or "").split()).strip()[:200]
    clean_media = str(media_id or "").strip().lower()
    clean_speaker = " ".join(str(speaker or "").split()).strip()[:80]
    safe_limit = _safe_limit(limit, default=100, maximum=MAX_SEARCH_RESULTS)
    start = _optional_seconds(start_seconds)
    end = _optional_seconds(end_seconds)
    clauses: list[str] = []
    params: list[object] = []
    if clean_media:
        if not re.fullmatch(r"[a-f0-9]{16,64}", clean_media):
            return []
        clauses.append("media_id=?")
        params.append(clean_media)
    if text:
        clauses.append("LOWER(text) LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(text.lower())}%")
    if clean_speaker:
        clauses.append("LOWER(speaker)=?")
        params.append(clean_speaker.lower())
    if start is not None:
        clauses.append("end_seconds>=?")
        params.append(start)
    if end is not None:
        clauses.append("start_seconds<=?")
        params.append(end)
    if start is not None and end is not None and end < start:
        return []
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
    clean_id = _clean_media_id(media_id)
    old = " ".join(str(old_label or "").split()).strip()[:80]
    new = " ".join(str(new_label or "").split()).strip()[:80]
    if not old or not new:
        raise TranscriptWorkspaceError("说话人标签无效")
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute(
            "UPDATE transcript_segments SET speaker=? WHERE media_id=? AND LOWER(speaker)=LOWER(?)",
            (new, clean_id, old),
        )
        connection.commit()
        return max(0, int(cursor.rowcount))


def run_transcript_workspace_self_test() -> None:
    import tempfile
    from media_library import search_media_items, sync_media_library

    sample = (
        "1\n00:00:01,000 --> 00:00:02,500\n[Speaker 1] Hello 100% world\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\nSpeaker 2: Next_line\n\n"
        "3\n00:99:00,000 --> 00:99:01,000\ninvalid time\n"
    )
    rows = parse_srt(sample)
    assert len(rows) == 2
    assert rows[0].speaker.lower() == "speaker 1"
    assert rows[0].start_seconds == 1.0
    assert rows[1].text == "Next_line"

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        downloads.mkdir()
        state.mkdir()
        data.mkdir()
        media = downloads / "demo.mp4"
        media.write_bytes(b"demo")

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return state

            @staticmethod
            def data_dir() -> Path:
                return data

            @staticmethod
            def default_download_dir() -> Path:
                return downloads

        sync_media_library(
            Engine,
            [{
                "state": "completed",
                "filePath": str(media),
                "fileName": media.name,
                "label": "demo",
                "finishedAt": "2026-09-03T00:00:00Z",
                "collectionMode": "single",
            }],
        )
        media_id = str(search_media_items(Engine, "demo", limit=10)[0]["id"])
        path = transcript_path(Engine, media_id)
        path.write_text(sample, encoding="utf-8")
        assert index_transcript(Engine, media_id) == 2
        assert len(transcript_segments(Engine, media_id)) == 2
        assert len(search_transcript(Engine, "100%", media_id=media_id)) == 1
        assert len(search_transcript(Engine, "Next_", media_id=media_id)) == 1
        assert len(search_transcript(Engine, "", media_id=media_id, start_seconds=2.6, end_seconds=3.2)) == 1
        assert relabel_speaker(Engine, media_id, "Speaker 2", "Host") == 1
        assert search_transcript(Engine, "", media_id=media_id, speaker="Host")[0]["text"] == "Next_line"
        assert _db_path(Engine).is_file()
