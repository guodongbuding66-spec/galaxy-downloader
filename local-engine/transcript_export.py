from __future__ import annotations

import csv
import json
import re
import uuid
from contextlib import closing, suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from transcript_workspace import MAX_SEGMENTS, TranscriptWorkspaceError, _clean_media_id, _connect

EXPORT_FORMATS = ("txt", "md", "srt", "vtt", "json", "csv")
MAX_EXPORT_BYTES = 64 * 1024 * 1024
MAX_BASENAME_CHARS = 80
_PAGE_SIZE = 1000


class TranscriptExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranscriptExportResult:
    media_id: str
    format: str
    path: str
    segment_count: int
    size_bytes: int

    def public_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["mediaId"] = data.pop("media_id")
        data["segmentCount"] = data.pop("segment_count")
        data["sizeBytes"] = data.pop("size_bytes")
        return data


def _clean_format(value: object) -> str:
    selected = str(value or "").strip().lower().lstrip(".")
    if selected not in EXPORT_FORMATS:
        raise TranscriptExportError("不支持的 Transcript 导出格式")
    return selected


def _safe_basename(value: object, media_id: str) -> str:
    raw = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    if not raw:
        return media_id
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(" ._-")[:MAX_BASENAME_CHARS]
    return clean or media_id


def _base_export_dir(engine_module) -> Path:
    accessor = getattr(engine_module, "default_download_dir", None)
    if callable(accessor):
        base = Path(accessor())
    else:
        data_accessor = getattr(engine_module, "data_dir", None)
        base = Path(data_accessor()) if callable(data_accessor) else Path(engine_module.app_dir()) / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def transcript_export_dir(engine_module) -> Path:
    base = _base_export_dir(engine_module)
    target = base / "Galaxy Exports" / "Transcripts"
    if target.exists() and target.is_symlink():
        raise TranscriptExportError("Transcript 导出目录不能是符号链接")
    target.mkdir(parents=True, exist_ok=True)
    try:
        target.resolve(strict=False).relative_to(base.resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise TranscriptExportError("Transcript 导出目录无效") from exc
    return target


def _output_path(engine_module, media_id: str, format_name: str, basename: object) -> Path:
    root = transcript_export_dir(engine_module)
    stem = _safe_basename(basename, media_id)
    candidate = root / f"{stem}.{format_name}"
    if not candidate.exists():
        return candidate
    for index in range(2, 1001):
        candidate = root / f"{stem}-{index}.{format_name}"
        if not candidate.exists():
            return candidate
    raise TranscriptExportError("同名 Transcript 导出文件过多")


def _iter_segments(engine_module, media_id: str) -> Iterator[dict[str, Any]]:
    yielded = 0
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute(
            "SELECT segment_index, start_seconds, end_seconds, speaker, text "
            "FROM transcript_segments WHERE media_id=? ORDER BY segment_index",
            (media_id,),
        )
        while yielded < MAX_SEGMENTS:
            rows = cursor.fetchmany(min(_PAGE_SIZE, MAX_SEGMENTS - yielded))
            if not rows:
                break
            for row in rows:
                yielded += 1
                yield {
                    "index": int(row["segment_index"]),
                    "startSeconds": float(row["start_seconds"]),
                    "endSeconds": float(row["end_seconds"]),
                    "speaker": str(row["speaker"]),
                    "text": str(row["text"]),
                }


def _stamp(seconds: object, *, decimal: str = ".") -> str:
    try:
        millis = max(0, round(float(seconds) * 1000))
    except (TypeError, ValueError):
        millis = 0
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{decimal}{millis:03d}"


def _display_text(row: dict[str, Any], *, include_speaker: bool) -> str:
    text = str(row.get("text") or "").replace("\r", " ").replace("\n", " ").strip()
    speaker = " ".join(str(row.get("speaker") or "").split()).strip()
    if include_speaker and speaker:
        return f"[{speaker}] {text}"
    return text


def _write_export(
    target: Path,
    *,
    engine_module,
    media_id: str,
    format_name: str,
    include_speaker: bool,
) -> tuple[int, int]:
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    written_bytes = 0
    segment_count = 0

    def emit(handle, value: str) -> None:
        nonlocal written_bytes
        encoded_size = len(value.encode("utf-8"))
        if written_bytes + encoded_size > MAX_EXPORT_BYTES:
            raise TranscriptExportError("Transcript 导出超过 64 MB 安全上限")
        handle.write(value)
        written_bytes += encoded_size

    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            if format_name == "vtt":
                emit(handle, "WEBVTT\n\n")
            elif format_name == "md":
                emit(handle, f"# Transcript\n\nMedia ID: `{media_id}`\n\n")
            elif format_name == "json":
                emit(handle, json.dumps({"mediaId": media_id}, ensure_ascii=False)[:-1] + ',"segments":[')
            elif format_name == "csv":
                header_buffer = []
                import io

                stream = io.StringIO(newline="")
                writer = csv.writer(stream)
                writer.writerow(["index", "startSeconds", "endSeconds", "start", "end", "speaker", "text"])
                header_buffer.append(stream.getvalue())
                emit(handle, "".join(header_buffer))

            first_json = True
            csv_writer = None
            csv_stream = None
            if format_name == "csv":
                import io

                csv_stream = io.StringIO(newline="")
                csv_writer = csv.writer(csv_stream)

            for row in _iter_segments(engine_module, media_id):
                segment_count += 1
                start_dot = _stamp(row["startSeconds"], decimal=".")
                end_dot = _stamp(row["endSeconds"], decimal=".")
                display = _display_text(row, include_speaker=include_speaker)

                if format_name == "txt":
                    emit(handle, f"[{start_dot} --> {end_dot}] {display}\n")
                elif format_name == "md":
                    safe = display.replace("\\", "\\\\").replace("`", "\\`")
                    emit(handle, f"- **{start_dot} → {end_dot}** — {safe}\n")
                elif format_name == "srt":
                    start_srt = _stamp(row["startSeconds"], decimal=",")
                    end_srt = _stamp(row["endSeconds"], decimal=",")
                    emit(handle, f"{segment_count}\n{start_srt} --> {end_srt}\n{display}\n\n")
                elif format_name == "vtt":
                    emit(handle, f"{start_dot} --> {end_dot}\n{display}\n\n")
                elif format_name == "json":
                    payload = {
                        "index": int(row["index"]),
                        "startSeconds": float(row["startSeconds"]),
                        "endSeconds": float(row["endSeconds"]),
                        "speaker": str(row["speaker"]) if include_speaker else "",
                        "text": str(row["text"]),
                    }
                    prefix = "" if first_json else ","
                    emit(handle, prefix + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                    first_json = False
                elif format_name == "csv" and csv_writer is not None and csv_stream is not None:
                    csv_stream.seek(0)
                    csv_stream.truncate(0)
                    csv_writer.writerow(
                        [
                            int(row["index"]),
                            float(row["startSeconds"]),
                            float(row["endSeconds"]),
                            start_dot,
                            end_dot,
                            str(row["speaker"]) if include_speaker else "",
                            str(row["text"]),
                        ]
                    )
                    emit(handle, csv_stream.getvalue())

            if segment_count == 0:
                raise TranscriptExportError("Transcript 尚未建立可导出的索引")
            if format_name == "json":
                emit(handle, f'],"segmentCount":{segment_count}}}')

        temporary.replace(target)
    except TranscriptExportError:
        with suppress(OSError):
            temporary.unlink()
        raise
    except OSError as exc:
        with suppress(OSError):
            temporary.unlink()
        raise TranscriptExportError(str(exc)) from exc
    return segment_count, target.stat().st_size


def export_transcript(
    engine_module,
    media_id: object,
    *,
    format: object = "txt",
    basename: object = "",
    include_speaker: bool = True,
) -> TranscriptExportResult:
    try:
        clean_id = _clean_media_id(media_id)
    except TranscriptWorkspaceError as exc:
        raise TranscriptExportError(str(exc)) from exc
    format_name = _clean_format(format)
    target = _output_path(engine_module, clean_id, format_name, basename)
    count, size = _write_export(
        target,
        engine_module=engine_module,
        media_id=clean_id,
        format_name=format_name,
        include_speaker=bool(include_speaker),
    )
    return TranscriptExportResult(clean_id, format_name, str(target), count, size)


def run_transcript_export_self_test() -> None:
    import tempfile

    from ai_workspace import transcript_path
    from media_library import search_media_items, sync_media_library
    from transcript_workspace import index_transcript, relabel_speaker

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        downloads.mkdir()
        state.mkdir()
        data.mkdir()

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

        media = downloads / "demo.mp4"
        media.write_bytes(b"demo")
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
        transcript_path(Engine, media_id).write_text(
            "1\n00:00:01,000 --> 00:00:02,500\n[Speaker 1] Hello world\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nSpeaker 2: Next line\n",
            encoding="utf-8",
        )
        assert index_transcript(Engine, media_id) == 2
        assert relabel_speaker(Engine, media_id, "Speaker 2", "Host") == 1

        outputs = {
            name: export_transcript(Engine, media_id, format=name, basename="Demo Export")
            for name in EXPORT_FORMATS
        }
        assert all(result.segment_count == 2 and result.size_bytes > 0 for result in outputs.values())
        assert Path(outputs["txt"].path).read_text(encoding="utf-8").count("Hello world") == 1
        assert "[Host] Next line" in Path(outputs["srt"].path).read_text(encoding="utf-8")
        assert Path(outputs["vtt"].path).read_text(encoding="utf-8").startswith("WEBVTT")
        assert "# Transcript" in Path(outputs["md"].path).read_text(encoding="utf-8")
        json_payload = json.loads(Path(outputs["json"].path).read_text(encoding="utf-8"))
        assert json_payload["mediaId"] == media_id and json_payload["segmentCount"] == 2
        with Path(outputs["csv"].path).open("r", encoding="utf-8", newline="") as csv_file:
            csv_rows = list(csv.DictReader(csv_file))
        assert len(csv_rows) == 2 and csv_rows[1]["speaker"] == "Host"

        duplicate = export_transcript(Engine, media_id, format="txt", basename="Demo Export")
        assert duplicate.path != outputs["txt"].path
        assert Path(duplicate.path).parent == downloads / "Galaxy Exports" / "Transcripts"

        try:
            export_transcript(Engine, media_id, format="../../bad")
        except TranscriptExportError:
            pass
        else:
            raise AssertionError("unsafe transcript export format was accepted")
