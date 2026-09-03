from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from job_history import append_history
from media_library import sync_media_library

MAX_IMPORT_FILES = 100
MAX_IMPORT_BYTES = 100 * 1024 * 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus"}
SUPPORTED_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


class LocalMediaImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalImportResult:
    source: Path
    destination: Path
    media_id: str


def _safe_source(value: object) -> Path:
    try:
        source = Path(str(value or "")).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise LocalMediaImportError("本地媒体文件不存在") from exc
    if not source.is_file() or source.is_symlink():
        raise LocalMediaImportError("只支持普通本地媒体文件")
    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise LocalMediaImportError("仅支持常见视频/音频文件")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise LocalMediaImportError(str(exc)) from exc
    if size <= 0 or size > MAX_IMPORT_BYTES:
        raise LocalMediaImportError("媒体文件为空或超过 100 GB 上限")
    return source


def _collision_safe_destination(root: Path, source: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stem = source.stem[:180] or "media"
    suffix = source.suffix.lower()
    candidate = root / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    for _ in range(100):
        candidate = root / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"
        if not candidate.exists():
            return candidate
    raise LocalMediaImportError("无法生成不冲突的导入文件名")


def import_local_media(engine_module, source_file: object) -> LocalImportResult:
    """Copy one user-selected local media file into Galaxy-managed storage.

    The media library intentionally resolves files only under Galaxy's download
    root. Import therefore copies the source instead of adding an arbitrary
    external filesystem path to the catalog.
    """
    source = _safe_source(source_file)
    root = Path(engine_module.default_download_dir()).expanduser().resolve(strict=False) / "imported"
    destination = _collision_safe_destination(root, source)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=4 * 1024 * 1024)
        shutil.copystat(source, temporary, follow_symlinks=False)
        if temporary.stat().st_size != source.stat().st_size:
            raise LocalMediaImportError("导入文件大小校验失败")
        temporary.replace(destination)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise

    finished = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    history = append_history(
        engine_module,
        {
            "state": "completed",
            "finishedAt": finished,
            "label": source.stem[:220],
            "filePath": str(destination),
            "fileName": destination.name,
            "collectionMode": "local-import",
            "durationSeconds": 0,
            "retryPayload": {},
        },
    )
    sync_media_library(engine_module)
    media_id = ""
    if history is not None:
        # Media-library IDs are separate from history IDs; resolve by the newly
        # inserted filename through the public list without exposing its path.
        from media_library import list_media_items

        for item in list_media_items(engine_module, limit=500):
            if item.get("fileName") == destination.name and item.get("available"):
                media_id = str(item.get("id") or "")
                break
    return LocalImportResult(source=source, destination=destination, media_id=media_id)


def import_local_media_batch(engine_module, values: Iterable[object]) -> list[LocalImportResult]:
    items = list(values)[:MAX_IMPORT_FILES]
    if not items:
        return []
    return [import_local_media(engine_module, value) for value in items]


def run_local_media_import_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        downloads = root / "downloads"
        state = root / "state"
        downloads.mkdir()
        source = root / "sample.mp3"
        source.write_bytes(b"ID3" + b"x" * 32)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                state.mkdir(exist_ok=True)
                return state

            @staticmethod
            def default_download_dir() -> Path:
                return downloads

        result = import_local_media(Engine, source)
        assert result.destination.is_file()
        assert result.destination.parent == downloads / "imported"
        assert result.media_id
        try:
            import_local_media(Engine, root / "bad.exe")
        except LocalMediaImportError:
            pass
        else:
            raise AssertionError("unsupported local import was accepted")
