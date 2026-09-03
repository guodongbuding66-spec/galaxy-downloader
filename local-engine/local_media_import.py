from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Iterable

from media_library import resolve_media_item_path, search_media_items, sync_media_library

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
    raw = Path(str(value or "")).expanduser()
    try:
        if raw.is_symlink():
            raise LocalMediaImportError("不允许通过符号链接导入媒体文件")
        source = raw.resolve(strict=True)
    except LocalMediaImportError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise LocalMediaImportError("本地媒体文件不存在") from exc
    if not source.is_file():
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


def _lookup_media_id(engine_module, destination: Path) -> str:
    try:
        expected = destination.resolve(strict=True)
    except (OSError, RuntimeError):
        return ""
    for item in search_media_items(engine_module, destination.name, limit=200):
        if item.get("fileName") != destination.name or not item.get("available"):
            continue
        media_id = str(item.get("id") or "")
        if not media_id:
            continue
        resolved = resolve_media_item_path(engine_module, media_id)
        if resolved is not None:
            try:
                if resolved.resolve(strict=False) == expected:
                    return media_id
            except (OSError, RuntimeError):
                continue
    return ""


def import_local_media(engine_module, source_file: object) -> LocalImportResult:
    """Copy one user-selected local media file into Galaxy-managed storage."""
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
    library_record = {
        "state": "completed",
        "finishedAt": finished,
        "label": source.stem[:220],
        "filePath": str(destination),
        "fileName": destination.name,
        "collectionMode": "local-import",
        "durationSeconds": 0,
        "retryPayload": {},
    }
    sync_media_library(engine_module, [library_record])
    return LocalImportResult(source=source, destination=destination, media_id=_lookup_media_id(engine_module, destination))


def import_local_media_batch(engine_module, values: Iterable[object]) -> list[LocalImportResult]:
    items = list(islice(values, MAX_IMPORT_FILES))
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
        state.mkdir()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return state

            @staticmethod
            def default_download_dir() -> Path:
                return downloads

        source = root / "sample.mp3"
        source.write_bytes(b"ID3" + b"x" * 32)
        first = import_local_media(Engine, source)
        assert first.destination.is_file()
        assert first.destination.parent.resolve() == (downloads / "imported").resolve()
        assert first.media_id
        assert resolve_media_item_path(Engine, first.media_id) == first.destination.resolve()

        second = import_local_media(Engine, source)
        assert second.destination.is_file()
        assert second.destination != first.destination
        assert second.media_id and second.media_id != first.media_id

        unsupported = root / "bad.exe"
        unsupported.write_bytes(b"x")
        try:
            import_local_media(Engine, unsupported)
        except LocalMediaImportError:
            pass
        else:
            raise AssertionError("unsupported local import was accepted")

        link = root / "sample-link.mp3"
        try:
            link.symlink_to(source)
        except OSError:
            link = None
        if link is not None:
            try:
                import_local_media(Engine, link)
            except LocalMediaImportError:
                pass
            else:
                raise AssertionError("symlink local import was accepted")

        batch_sources: list[Path] = []
        for index in range(MAX_IMPORT_FILES):
            path = root / f"batch-{index}.mp3"
            path.write_bytes(b"ID3x")
            batch_sources.append(path)

        consumed = 0

        def values():
            nonlocal consumed
            for path in batch_sources:
                consumed += 1
                yield path
            consumed += 1
            raise AssertionError("batch consumed more than MAX_IMPORT_FILES inputs")

        rows = import_local_media_batch(Engine, values())
        assert len(rows) == MAX_IMPORT_FILES
        assert consumed == MAX_IMPORT_FILES
        assert all(item.media_id for item in rows)
