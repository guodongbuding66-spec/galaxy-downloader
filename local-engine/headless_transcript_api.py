from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from media_library import resolve_media_item_path
from platform_paths import resolve_platform_paths
from transcript_export import EXPORT_FORMATS, TranscriptExportError, export_transcript, transcript_export_dir
from transcript_workspace import (
    TranscriptWorkspaceError,
    index_transcript,
    relabel_speaker,
    search_transcript,
    transcript_segments,
)

_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
_MAX_WINDOW_SECONDS = 365 * 24 * 3600


class HeadlessTranscriptApiError(RuntimeError):
    pass


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def _media_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _MEDIA_ID_RE.fullmatch(clean):
        raise HeadlessTranscriptApiError("invalid media id")
    return clean


def _safe_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()[:limit]


def _optional_seconds(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise HeadlessTranscriptApiError("time filter must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0 or parsed > _MAX_WINDOW_SECONDS:
        raise HeadlessTranscriptApiError("time filter is outside the supported range")
    return parsed


def _export_format(value: object) -> str:
    selected = str(value or "txt").strip().lower().lstrip(".")
    if selected not in EXPORT_FORMATS:
        raise HeadlessTranscriptApiError("unsupported transcript export format")
    return selected


@dataclass(frozen=True)
class HeadlessTranscriptContext:
    program_path: Path
    data_path: Path
    state_path: Path
    downloads_path: Path

    def app_dir(self) -> Path:
        return self.program_path

    def data_dir(self) -> Path:
        self.data_path.mkdir(parents=True, exist_ok=True)
        return self.data_path

    def state_dir(self) -> Path:
        self.state_path.mkdir(parents=True, exist_ok=True)
        return self.state_path

    def default_download_dir(self) -> Path:
        self.downloads_path.mkdir(parents=True, exist_ok=True)
        return self.downloads_path


def _safe_directory(value: Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    if raw.exists() and raw.is_symlink():
        raise HeadlessTranscriptApiError(f"{label} cannot be a symbolic link")
    resolved = raw.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def build_headless_transcript_context(
    download_root: Path,
    *,
    program_dir: Path | None = None,
    data_dir: Path | None = None,
    state_dir: Path | None = None,
) -> HeadlessTranscriptContext:
    program = Path(program_dir or Path(__file__).resolve().parent).expanduser().resolve(strict=False)
    paths = resolve_platform_paths(program_dir=program)
    downloads = _safe_directory(Path(download_root), label="transcript download root")
    data = _safe_directory(Path(data_dir or paths.data_dir), label="transcript data directory")
    state = _safe_directory(Path(state_dir or paths.state_dir), label="transcript state directory")
    return HeadlessTranscriptContext(program, data, state, downloads)


class HeadlessTranscriptApi:
    def __init__(
        self,
        download_root: Path,
        *,
        context: HeadlessTranscriptContext | None = None,
        program_dir: Path | None = None,
        data_dir: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.context = context or build_headless_transcript_context(
            download_root,
            program_dir=program_dir,
            data_dir=data_dir,
            state_dir=state_dir,
        )

    def _require_media(self, media_id: object) -> str:
        clean = _media_id(media_id)
        if resolve_media_item_path(self.context, clean) is None:
            raise HeadlessTranscriptApiError("media item not found")
        return clean

    def index(self, media_id: object) -> dict[str, Any]:
        clean = self._require_media(media_id)
        try:
            count = index_transcript(self.context, clean)
        except TranscriptWorkspaceError as exc:
            raise HeadlessTranscriptApiError(str(exc)) from exc
        return {"mediaId": clean, "segmentCount": count}

    def list_segments(self, media_id: object, *, limit: object = 1000) -> dict[str, Any]:
        clean = self._require_media(media_id)
        safe_limit = _bounded_int(limit, 1000, 1, 5000)
        rows = transcript_segments(self.context, clean, limit=safe_limit)
        return {"mediaId": clean, "segments": rows, "limit": safe_limit}

    def search(
        self,
        *,
        query: object = "",
        media_id: object = "",
        speaker: object = "",
        start_seconds: object = None,
        end_seconds: object = None,
        limit: object = 100,
    ) -> dict[str, Any]:
        clean_media = ""
        if str(media_id or "").strip():
            clean_media = self._require_media(media_id)
        text = _safe_text(query, 200)
        clean_speaker = _safe_text(speaker, 80)
        start = _optional_seconds(start_seconds)
        end = _optional_seconds(end_seconds)
        if start is not None and end is not None and end < start:
            raise HeadlessTranscriptApiError("endSeconds must be greater than or equal to startSeconds")
        safe_limit = _bounded_int(limit, 100, 1, 500)
        rows = search_transcript(
            self.context,
            text,
            media_id=clean_media,
            speaker=clean_speaker,
            start_seconds=start,
            end_seconds=end,
            limit=safe_limit,
        )
        return {
            "results": rows,
            "query": text,
            "mediaId": clean_media,
            "speaker": clean_speaker,
            "startSeconds": start,
            "endSeconds": end,
            "limit": safe_limit,
        }

    def relabel(self, media_id: object, old_label: object, new_label: object) -> dict[str, Any]:
        clean = self._require_media(media_id)
        old = _safe_text(old_label, 80)
        new = _safe_text(new_label, 80)
        if not old or not new:
            raise HeadlessTranscriptApiError("oldLabel and newLabel are required")
        try:
            changed = relabel_speaker(self.context, clean, old, new)
        except TranscriptWorkspaceError as exc:
            raise HeadlessTranscriptApiError(str(exc)) from exc
        return {"mediaId": clean, "updated": changed, "oldLabel": old, "newLabel": new}

    def export(
        self,
        media_id: object,
        *,
        format: object = "txt",
        basename: object = "",
        include_speaker: object = True,
    ) -> dict[str, Any]:
        clean = self._require_media(media_id)
        selected = _export_format(format)
        safe_basename = _safe_text(basename, 80)
        try:
            result = export_transcript(
                self.context,
                clean,
                format=selected,
                basename=safe_basename,
                include_speaker=bool(include_speaker),
            )
        except (TranscriptExportError, TranscriptWorkspaceError) as exc:
            raise HeadlessTranscriptApiError(str(exc)) from exc
        path = Path(result.path).resolve(strict=False)
        root = transcript_export_dir(self.context).resolve(strict=False)
        try:
            path.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HeadlessTranscriptApiError("transcript export escaped the managed export directory") from exc
        if not path.is_file() or path.is_symlink():
            raise HeadlessTranscriptApiError("transcript export was not created safely")
        return {
            "mediaId": result.media_id,
            "format": result.format,
            "fileName": path.name[:240],
            "segmentCount": result.segment_count,
            "sizeBytes": result.size_bytes,
        }


def run_headless_transcript_api_self_test() -> None:
    import tempfile

    from ai_workspace import transcript_path
    from media_library import search_media_items, sync_media_library

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        downloads = root / "downloads"
        data = root / "data"
        state = root / "state"
        program = root / "program"
        for target in (downloads, data, state, program):
            target.mkdir()
        media = downloads / "Transcript Demo.mp4"
        media.write_bytes(b"demo")
        context = HeadlessTranscriptContext(program, data, state, downloads)
        history = [
            {
                "state": "completed",
                "filePath": str(media),
                "fileName": media.name,
                "label": "Transcript Demo",
                "sourceUrl": "https://example.com/demo",
                "finishedAt": "2026-09-03T00:00:00Z",
            }
        ]
        assert sync_media_library(context, history) == 1
        item = search_media_items(context, "Transcript Demo", limit=1)[0]
        media_id = item["id"]
        source = transcript_path(context, media_id)
        source.write_text(
            "1\n00:00:01,000 --> 00:00:02,000\n[Speaker 1] Hello world\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\n[Speaker 2] Next line\n",
            encoding="utf-8",
        )
        api = HeadlessTranscriptApi(downloads, context=context)
        indexed = api.index(media_id)
        assert indexed["segmentCount"] == 2
        listed = api.list_segments(media_id, limit=10)
        assert len(listed["segments"]) == 2
        searched = api.search(query="hello", media_id=media_id)
        assert len(searched["results"]) == 1
        relabeled = api.relabel(media_id, "Speaker 1", "Host")
        assert relabeled["updated"] == 1
        exported = api.export(media_id, format="json", basename="demo")
        assert exported["fileName"].endswith(".json")
        assert "path" not in exported and "filePath" not in exported
        try:
            api.search(media_id=media_id, start_seconds="nan")
        except HeadlessTranscriptApiError:
            pass
        else:
            raise AssertionError("non-finite transcript time filter was accepted")
