from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from job_history import load_history
from runtime_storage import state_dir as runtime_state_dir

DATABASE_FILENAME = "media-library.sqlite3"
SCHEMA_VERSION = 1
_LIBRARY_LOCK = threading.RLock()
_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts"}
_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".bmp"}


@dataclass(frozen=True)
class MediaLibrarySummary:
    total: int
    available: int
    missing: int
    video: int
    audio: int
    image: int
    other: int

    def public_payload(self) -> dict[str, int]:
        return {
            "total": self.total,
            "available": self.available,
            "missing": self.missing,
            "video": self.video,
            "audio": self.audio,
            "image": self.image,
            "other": self.other,
        }


def media_library_path(engine_module) -> Path:
    target = runtime_state_dir(engine_module)
    target.mkdir(parents=True, exist_ok=True)
    return target / DATABASE_FILENAME


def _connect(engine_module) -> sqlite3.Connection:
    connection = sqlite3.connect(media_library_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    _ensure_schema(connection)
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS library_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS media_items (
            id TEXT PRIMARY KEY,
            file_path TEXT NOT NULL UNIQUE,
            file_name TEXT NOT NULL,
            title TEXT NOT NULL,
            media_type TEXT NOT NULL,
            extension TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            duration_seconds REAL NOT NULL DEFAULT 0,
            source_url TEXT NOT NULL DEFAULT '',
            source_host TEXT NOT NULL DEFAULT '',
            video_quality TEXT NOT NULL DEFAULT '',
            audio_quality TEXT NOT NULL DEFAULT '',
            collection_mode TEXT NOT NULL DEFAULT 'single',
            finished_at TEXT NOT NULL DEFAULT '',
            available INTEGER NOT NULL DEFAULT 1,
            tags_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_media_items_finished_at
            ON media_items(finished_at DESC);
        CREATE INDEX IF NOT EXISTS idx_media_items_media_type
            ON media_items(media_type);
        CREATE INDEX IF NOT EXISTS idx_media_items_source_host
            ON media_items(source_host);
        """
    )
    row = connection.execute("SELECT value FROM library_meta WHERE key='schema_version'").fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO library_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    else:
        try:
            version = int(row["value"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Invalid media library schema version") from exc
        if version != SCHEMA_VERSION:
            raise RuntimeError(f"Unsupported media library schema version: {version}")
    connection.commit()


def _safe_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _safe_source_url(value: object) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "", ""
    hostname = str(parsed.hostname or "").lower()
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return "", ""
    if parsed.username is not None or parsed.password is not None:
        return "", ""
    host = hostname
    try:
        if parsed.port:
            host = f"{host}:{parsed.port}"
    except ValueError:
        pass
    # History retry URLs have already removed secret query values. Keeping that
    # reviewed identity is useful for YouTube v/list identifiers; fragments are
    # always removed here.
    clean = urlunsplit((parsed.scheme.lower(), host, parsed.path or "/", parsed.query, ""))
    return clean[:900], hostname[:160]


def _local_download_path(engine_module, value: object) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        candidate = Path(raw).expanduser().resolve(strict=False)
        root = Path(engine_module.default_download_dir()).expanduser().resolve(strict=False)
        candidate.relative_to(root)
        return candidate
    except (OSError, RuntimeError, ValueError):
        return None


def _media_type(path: Path) -> str:
    extension = path.suffix.lower()
    if extension in _VIDEO_EXTENSIONS:
        return "video"
    if extension in _AUDIO_EXTENSIONS:
        return "audio"
    if extension in _IMAGE_EXTENSIONS:
        return "image"
    return "other"


def _history_source(item: dict[str, Any]) -> tuple[str, str]:
    retry = item.get("retryPayload")
    if isinstance(retry, dict):
        source, host = _safe_source_url(retry.get("sourceUrl"))
        if source:
            return source, host
    return _safe_source_url(item.get("sourceUrl"))


def _item_from_history(engine_module, item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict) or str(item.get("state") or "").lower() != "completed":
        return None
    path = _local_download_path(engine_module, item.get("filePath"))
    if path is None:
        return None
    exists = path.is_file()
    try:
        size_bytes = max(0, int(path.stat().st_size)) if exists else 0
    except OSError:
        exists = False
        size_bytes = 0
    file_name = _safe_text(item.get("fileName"), 240) or path.name[:240]
    label = _safe_text(item.get("label"), 300)
    title = label if label and label != file_name else path.stem[:300]
    source_url, source_host = _history_source(item)
    try:
        duration = max(0.0, float(item.get("durationSeconds") or 0))
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "file_path": str(path),
        "file_name": file_name,
        "title": title or file_name or "Media",
        "media_type": _media_type(path),
        "extension": path.suffix.lower().lstrip(".")[:16],
        "size_bytes": size_bytes,
        "duration_seconds": round(duration, 1),
        "source_url": source_url,
        "source_host": source_host,
        "video_quality": _safe_text(item.get("videoQuality"), 64),
        "audio_quality": _safe_text(item.get("audioQuality"), 64),
        "collection_mode": _safe_text(item.get("collectionMode"), 24) or "single",
        "finished_at": _safe_text(item.get("finishedAt"), 48),
        "available": 1 if exists else 0,
    }


def _upsert(connection: sqlite3.Connection, value: dict[str, Any]) -> None:
    existing = connection.execute(
        "SELECT id FROM media_items WHERE file_path=?",
        (value["file_path"],),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO media_items(
                id, file_path, file_name, title, media_type, extension,
                size_bytes, duration_seconds, source_url, source_host,
                video_quality, audio_quality, collection_mode, finished_at,
                available, tags_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]')
            """,
            (
                uuid.uuid4().hex,
                value["file_path"],
                value["file_name"],
                value["title"],
                value["media_type"],
                value["extension"],
                value["size_bytes"],
                value["duration_seconds"],
                value["source_url"],
                value["source_host"],
                value["video_quality"],
                value["audio_quality"],
                value["collection_mode"],
                value["finished_at"],
                value["available"],
            ),
        )
        return
    connection.execute(
        """
        UPDATE media_items SET
            file_name=?, title=?, media_type=?, extension=?, size_bytes=?,
            duration_seconds=?, source_url=?, source_host=?, video_quality=?,
            audio_quality=?, collection_mode=?, finished_at=?, available=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE file_path=?
        """,
        (
            value["file_name"],
            value["title"],
            value["media_type"],
            value["extension"],
            value["size_bytes"],
            value["duration_seconds"],
            value["source_url"],
            value["source_host"],
            value["video_quality"],
            value["audio_quality"],
            value["collection_mode"],
            value["finished_at"],
            value["available"],
            value["file_path"],
        ),
    )


def sync_media_library(engine_module, history_items: Iterable[object] | None = None) -> int:
    items = list(load_history(engine_module) if history_items is None else history_items)
    accepted: list[dict[str, Any]] = []
    for item in items:
        normalized = _item_from_history(engine_module, item)
        if normalized is not None:
            accepted.append(normalized)
    with _LIBRARY_LOCK, _connect(engine_module) as connection:
        for value in accepted:
            _upsert(connection, value)
        # Reconcile availability for every known item without scanning outside
        # paths that previously passed the download-root boundary.
        rows = connection.execute("SELECT file_path FROM media_items").fetchall()
        for row in rows:
            path = _local_download_path(engine_module, row["file_path"])
            available = 1 if path is not None and path.is_file() else 0
            connection.execute(
                "UPDATE media_items SET available=?, updated_at=CURRENT_TIMESTAMP WHERE file_path=?",
                (available, row["file_path"]),
            )
        connection.commit()
    return len(accepted)


def _public_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        tags = json.loads(row["tags_json"] or "[]")
    except (TypeError, ValueError):
        tags = []
    return {
        "id": row["id"],
        "fileName": row["file_name"],
        "title": row["title"],
        "mediaType": row["media_type"],
        "extension": row["extension"],
        "sizeBytes": int(row["size_bytes"] or 0),
        "durationSeconds": float(row["duration_seconds"] or 0),
        "sourceUrl": row["source_url"],
        "sourceHost": row["source_host"],
        "videoQuality": row["video_quality"],
        "audioQuality": row["audio_quality"],
        "collectionMode": row["collection_mode"],
        "finishedAt": row["finished_at"],
        "available": bool(row["available"]),
        "tags": [str(item)[:60] for item in tags if isinstance(item, str)][:20],
    }


def list_media_items(engine_module, *, limit: int = 100, offset: int = 0, media_type: str | None = None) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))
    params: list[object] = []
    where = ""
    if media_type in {"video", "audio", "image", "other"}:
        where = " WHERE media_type=?"
        params.append(media_type)
    params.extend((safe_limit, safe_offset))
    with _LIBRARY_LOCK, _connect(engine_module) as connection:
        rows = connection.execute(
            f"SELECT * FROM media_items{where} ORDER BY finished_at DESC, created_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
    return [_public_row(row) for row in rows]


def search_media_items(engine_module, query: object, *, limit: int = 100) -> list[dict[str, Any]]:
    text = " ".join(str(query or "").split()).strip()
    if not text:
        return list_media_items(engine_module, limit=limit)
    safe_limit = max(1, min(int(limit), 200))
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")[:160]
    pattern = f"%{escaped}%"
    with _LIBRARY_LOCK, _connect(engine_module) as connection:
        rows = connection.execute(
            """
            SELECT * FROM media_items
            WHERE title LIKE ? ESCAPE '\\'
               OR file_name LIKE ? ESCAPE '\\'
               OR source_host LIKE ? ESCAPE '\\'
            ORDER BY finished_at DESC, created_at DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, safe_limit),
        ).fetchall()
    return [_public_row(row) for row in rows]


def media_library_summary(engine_module) -> MediaLibrarySummary:
    with _LIBRARY_LOCK, _connect(engine_module) as connection:
        row = connection.execute(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN available=1 THEN 1 ELSE 0 END) AS available,
              SUM(CASE WHEN available=0 THEN 1 ELSE 0 END) AS missing,
              SUM(CASE WHEN media_type='video' THEN 1 ELSE 0 END) AS video,
              SUM(CASE WHEN media_type='audio' THEN 1 ELSE 0 END) AS audio,
              SUM(CASE WHEN media_type='image' THEN 1 ELSE 0 END) AS image,
              SUM(CASE WHEN media_type='other' THEN 1 ELSE 0 END) AS other
            FROM media_items
            """
        ).fetchone()
    return MediaLibrarySummary(
        total=int(row["total"] or 0),
        available=int(row["available"] or 0),
        missing=int(row["missing"] or 0),
        video=int(row["video"] or 0),
        audio=int(row["audio"] or 0),
        image=int(row["image"] or 0),
        other=int(row["other"] or 0),
    )


def install_media_library(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_media_library_installed", False):
        return window_cls

    engine_module.media_library_path = lambda: media_library_path(engine_module)
    engine_module.sync_media_library = lambda: sync_media_library(engine_module)
    engine_module.list_media_items = lambda **kwargs: list_media_items(engine_module, **kwargs)
    engine_module.search_media_items = lambda query, **kwargs: search_media_items(engine_module, query, **kwargs)
    engine_module.media_library_summary = lambda: media_library_summary(engine_module).public_payload()

    original_run_job = window_cls._run_job

    def run_job_with_library(window) -> None:
        original_run_job(window)
        try:
            sync_media_library(engine_module)
        except Exception:
            # The catalog is derived state. A database/storage issue must never
            # alter download success/failure semantics.
            pass

    window_cls._run_job = run_job_with_library
    window_cls._galaxy_media_library_installed = True
    engine_module._galaxy_media_library_installed = True
    return window_cls


def run_media_library_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        downloads = root / "downloads"
        state = root / "state"
        downloads.mkdir()
        state.mkdir()
        video = downloads / "Demo Video.mp4"
        video.write_bytes(b"demo-media")

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

        history = [
            {
                "state": "completed",
                "filePath": str(video),
                "fileName": video.name,
                "label": "Demo Video.mp4",
                "finishedAt": "2026-09-02T00:00:00Z",
                "durationSeconds": 125,
                "videoQuality": "1080p",
                "audioQuality": "best",
                "collectionMode": "single",
                "sourceUrl": "https://www.youtube.com/watch",
                "retryPayload": {"sourceUrl": "https://www.youtube.com/watch?v=abc123"},
            },
            {
                "state": "failed",
                "filePath": str(downloads / "failed.mp4"),
            },
        ]
        assert sync_media_library(Engine, history) == 1
        summary = media_library_summary(Engine)
        assert summary.total == 1 and summary.available == 1 and summary.video == 1
        items = list_media_items(Engine)
        assert len(items) == 1
        assert items[0]["fileName"] == video.name
        assert items[0]["sourceUrl"] == "https://www.youtube.com/watch?v=abc123"
        assert "filePath" not in items[0]
        assert search_media_items(Engine, "demo")[0]["id"] == items[0]["id"]
        assert search_media_items(Engine, "youtube.com")[0]["id"] == items[0]["id"]

        video.unlink()
        sync_media_library(Engine, [])
        summary = media_library_summary(Engine)
        assert summary.available == 0 and summary.missing == 1
        assert list_media_items(Engine)[0]["available"] is False

        outside = root / "secret.mp4"
        outside.write_bytes(b"secret")
        assert sync_media_library(
            Engine,
            [{"state": "completed", "filePath": str(outside), "fileName": outside.name}],
        ) == 0
