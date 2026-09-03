from __future__ import annotations

import json
import math
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing, suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from media_library import list_media_items, resolve_media_item_path
from runtime_storage import state_dir as runtime_state_dir

DATABASE_FILENAME = "music-library.sqlite3"
SCHEMA_VERSION = 1
MAX_TRACKS = 100_000
MAX_QUEUE_ITEMS = 10_000
MAX_LRC_BYTES = 10 * 1024 * 1024
MAX_LYRICS_CHARS = 2_000_000
MAX_PROBE_BYTES = 2 * 1024 * 1024
_AUDIO_EXTENSIONS = frozenset({".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus"})
_REPEAT_MODES = frozenset({"off", "all", "one"})
_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
_LRC_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\](.*)")


class MusicWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class MusicTrack:
    media_id: str
    title: str
    artist: str
    album: str
    album_artist: str
    track_number: int
    disc_number: int
    year: int
    genre: str
    cover_path: str
    favorite: bool
    play_count: int
    last_position: float
    last_played_at: str
    has_lyrics: bool

    def public_payload(self) -> dict[str, Any]:
        data = asdict(self)
        mapping = {
            "media_id": "mediaId",
            "album_artist": "albumArtist",
            "track_number": "trackNumber",
            "disc_number": "discNumber",
            "cover_path": "coverPath",
            "play_count": "playCount",
            "last_position": "lastPosition",
            "last_played_at": "lastPlayedAt",
            "has_lyrics": "hasLyrics",
        }
        for old, new in mapping.items():
            data[new] = data.pop(old)
        return data


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def music_database_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / DATABASE_FILENAME


def _connect(engine_module) -> sqlite3.Connection:
    connection = sqlite3.connect(music_database_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS music_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tracks (
            media_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            artist TEXT NOT NULL DEFAULT '',
            album TEXT NOT NULL DEFAULT '',
            album_artist TEXT NOT NULL DEFAULT '',
            track_number INTEGER NOT NULL DEFAULT 0,
            disc_number INTEGER NOT NULL DEFAULT 0,
            year INTEGER NOT NULL DEFAULT 0,
            genre TEXT NOT NULL DEFAULT '',
            cover_path TEXT NOT NULL DEFAULT '',
            favorite INTEGER NOT NULL DEFAULT 0,
            play_count INTEGER NOT NULL DEFAULT 0,
            last_position REAL NOT NULL DEFAULT 0,
            last_played_at TEXT NOT NULL DEFAULT '',
            lyrics_path TEXT NOT NULL DEFAULT '',
            embedded_lyrics TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS queue_items (
            id TEXT PRIMARY KEY,
            media_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(media_id, position)
        );
        CREATE TABLE IF NOT EXISTS player_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            current_media_id TEXT NOT NULL DEFAULT '',
            repeat_mode TEXT NOT NULL DEFAULT 'off',
            shuffle INTEGER NOT NULL DEFAULT 0,
            volume REAL NOT NULL DEFAULT 1.0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_music_tracks_album ON tracks(album, disc_number, track_number);
        CREATE INDEX IF NOT EXISTS idx_music_tracks_artist ON tracks(artist, album, disc_number, track_number);
        CREATE INDEX IF NOT EXISTS idx_music_tracks_favorite ON tracks(favorite, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_music_tracks_recent ON tracks(last_played_at DESC);
        CREATE INDEX IF NOT EXISTS idx_music_tracks_play_count ON tracks(play_count DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_music_queue_position ON queue_items(position);
        INSERT OR IGNORE INTO player_state(singleton) VALUES(1);
        """
    )
    row = connection.execute("SELECT value FROM music_meta WHERE key='schema_version'").fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO music_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    else:
        try:
            version = int(row["value"])
        except (TypeError, ValueError) as exc:
            raise MusicWorkspaceError("Music database schema version is invalid") from exc
        if version != SCHEMA_VERSION:
            raise MusicWorkspaceError(f"Unsupported Music database schema version: {version}")
    connection.commit()
    return connection


def _clean_media_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _MEDIA_ID_RE.fullmatch(clean):
        raise MusicWorkspaceError("Media ID 无效")
    return clean


def _clean_text(value: object, limit: int = 300) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()[:limit]


def _bounded_int(value: object, low: int = 0, high: int = 100_000) -> int:
    try:
        parsed = int(str(value or "0").split("/", 1)[0])
    except (TypeError, ValueError):
        return low
    return max(low, min(parsed, high))


def _bounded_float(value: object, low: float = 0.0, high: float = 30 * 24 * 3600.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return low
    if not math.isfinite(parsed):
        return low
    return max(low, min(parsed, high))


def _media_rows(engine_module, *, max_items: int = MAX_TRACKS) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    offset = 0
    while len(result) < max_items:
        page = list_media_items(engine_module, limit=500, offset=offset, media_type="audio")
        if not page:
            break
        for item in page:
            if item.get("available"):
                result.append(item)
                if len(result) >= max_items:
                    break
        if len(page) < 500:
            break
        offset += len(page)
    return result


def _infer_title_artist(item: dict[str, Any]) -> tuple[str, str]:
    title = _clean_text(item.get("title") or Path(str(item.get("fileName") or "Music")).stem, 300)
    artist = ""
    stem = Path(str(item.get("fileName") or "")).stem
    if " - " in stem:
        left, right = stem.split(" - ", 1)
        if left.strip() and right.strip():
            artist = _clean_text(left, 200)
            if not item.get("title") or str(item.get("title")) == stem:
                title = _clean_text(right, 300)
    return title or "Music", artist


def sync_music_library(engine_module) -> int:
    media = _media_rows(engine_module)
    with closing(_connect(engine_module)) as connection:
        for item in media:
            media_id = _clean_media_id(item.get("id"))
            title, artist = _infer_title_artist(item)
            connection.execute(
                """
                INSERT INTO tracks(media_id, title, artist)
                VALUES(?, ?, ?)
                ON CONFLICT(media_id) DO UPDATE SET
                    title=CASE WHEN tracks.title='' THEN excluded.title ELSE tracks.title END,
                    artist=CASE WHEN tracks.artist='' THEN excluded.artist ELSE tracks.artist END,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (media_id, title, artist),
            )
        connection.commit()
    return len(media)


def _track_row(engine_module, media_id: object) -> sqlite3.Row:
    clean = _clean_media_id(media_id)
    if resolve_media_item_path(engine_module, clean) is None:
        raise MusicWorkspaceError("音乐媒体不存在或不可用")
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT * FROM tracks WHERE media_id=?", (clean,)).fetchone()
    if row is None:
        sync_music_library(engine_module)
        with closing(_connect(engine_module)) as connection:
            row = connection.execute("SELECT * FROM tracks WHERE media_id=?", (clean,)).fetchone()
    if row is None:
        raise MusicWorkspaceError("音乐条目不存在")
    return row


def _lyrics_root(engine_module) -> Path:
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir()) / "data"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "music" / "lyrics"
    if target.exists() and target.is_symlink():
        raise MusicWorkspaceError("Music lyrics root 不能是符号链接")
    target.mkdir(parents=True, exist_ok=True)
    return target


def parse_lrc(text: object) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in str(text or "").replace("\r", "").split("\n"):
        for match in _LRC_RE.finditer(line):
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            if seconds >= 60:
                continue
            fraction = match.group(3) or "0"
            millis = int(fraction.ljust(3, "0")[:3])
            timestamp = minutes * 60 + seconds + millis / 1000.0
            lyric = match.group(4).strip()[:4000]
            if lyric:
                rows.append({"time": round(timestamp, 3), "text": lyric})
            if len(rows) >= 50_000:
                return sorted(rows, key=lambda item: item["time"])
    return sorted(rows, key=lambda item: item["time"])


def attach_lrc(engine_module, media_id: object, lyrics_file: object) -> int:
    clean = _clean_media_id(media_id)
    _track_row(engine_module, clean)
    raw = Path(str(lyrics_file or "")).expanduser()
    if raw.is_symlink():
        raise MusicWorkspaceError("LRC 不能是符号链接")
    try:
        source = raw.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MusicWorkspaceError("歌词文件不存在") from exc
    if not source.is_file() or source.suffix.lower() != ".lrc":
        raise MusicWorkspaceError("请选择 LRC 歌词")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise MusicWorkspaceError(str(exc)) from exc
    if size <= 0 or size > MAX_LRC_BYTES:
        raise MusicWorkspaceError("LRC 文件为空或超过 10 MB")
    text = source.read_text(encoding="utf-8", errors="replace")[:MAX_LYRICS_CHARS]
    rows = parse_lrc(text)
    target = _lyrics_root(engine_module) / f"{clean}.lrc"
    temporary = target.with_suffix(f".{secrets.token_hex(4)}.part")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(target)
    except OSError:
        with suppress(OSError):
            temporary.unlink()
        raise
    with closing(_connect(engine_module)) as connection:
        connection.execute(
            "UPDATE tracks SET lyrics_path=?, updated_at=CURRENT_TIMESTAMP WHERE media_id=?",
            (str(target), clean),
        )
        connection.commit()
    return len(rows)


def _safe_lyrics_path(engine_module, raw: object) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    path = Path(value)
    if path.is_symlink():
        return None
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(_lyrics_root(engine_module).resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved if resolved.is_file() and resolved.suffix.lower() == ".lrc" else None


def lyrics(engine_module, media_id: object) -> dict[str, Any]:
    row = _track_row(engine_module, media_id)
    path = _safe_lyrics_path(engine_module, row["lyrics_path"])
    if path is not None:
        text = path.read_text(encoding="utf-8", errors="replace")[:MAX_LYRICS_CHARS]
        synced = parse_lrc(text)
        return {"kind": "lrc", "synced": synced, "text": text if not synced else ""}
    embedded = str(row["embedded_lyrics"] or "")[:MAX_LYRICS_CHARS]
    if embedded:
        synced = parse_lrc(embedded)
        return {"kind": "embedded", "synced": synced, "text": embedded if not synced else ""}
    return {"kind": "none", "synced": [], "text": ""}


def _find_ffprobe(engine_module) -> Path | None:
    names = ("ffprobe.exe", "ffprobe") if os.name == "nt" else ("ffprobe",)
    roots: list[Path] = []
    accessor = getattr(engine_module, "tools_dir", None)
    if callable(accessor):
        with suppress(OSError, RuntimeError, TypeError, ValueError):
            tools = Path(accessor())
            roots.extend((tools / "ffmpeg" / "bin", tools / "bin", tools))
    accessor = getattr(engine_module, "app_dir", None)
    if callable(accessor):
        with suppress(OSError, RuntimeError, TypeError, ValueError):
            app = Path(accessor())
            roots.extend((app / "bin", app))
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
    resolved = shutil.which("ffprobe")
    if not resolved:
        return None
    candidate = Path(resolved)
    return candidate if candidate.is_file() and not candidate.is_symlink() else None


def _read_bounded(path: Path, limit: int = MAX_PROBE_BYTES) -> bytes:
    try:
        if path.stat().st_size > limit:
            raise MusicWorkspaceError("ffprobe metadata response too large")
        return path.read_bytes()
    except OSError as exc:
        raise MusicWorkspaceError(str(exc)) from exc


def _probe_metadata(engine_module, source: Path) -> dict[str, Any]:
    executable = _find_ffprobe(engine_module)
    if executable is None:
        return {}
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="galaxy-music-probe-out-", delete=False) as stdout_file, tempfile.NamedTemporaryFile(
            prefix="galaxy-music-probe-err-", delete=False
        ) as stderr_file:
            stdout_path = Path(stdout_file.name)
            stderr_path = Path(stderr_file.name)
            completed = subprocess.run(
                [str(executable), "-v", "error", "-show_entries", "format=duration:format_tags", "-of", "json", "--", str(source)],
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=30,
                check=False,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        if completed.returncode != 0:
            return {}
        payload = json.loads(_read_bounded(stdout_path).decode("utf-8", errors="strict"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError, ValueError, MusicWorkspaceError):
        return {}
    finally:
        for path in (stdout_path, stderr_path):
            if path is not None:
                with suppress(OSError):
                    path.unlink()


def refresh_track_metadata(engine_module, media_id: object) -> dict[str, Any]:
    clean = _clean_media_id(media_id)
    source = resolve_media_item_path(engine_module, clean)
    if source is None or source.suffix.lower() not in _AUDIO_EXTENSIONS:
        raise MusicWorkspaceError("音乐媒体不存在")
    _track_row(engine_module, clean)
    payload = _probe_metadata(engine_module, source)
    format_data = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    tags = format_data.get("tags") if isinstance(format_data.get("tags"), dict) else {}
    normalized = {str(key).lower().replace("-", "_"): value for key, value in tags.items()}
    title = _clean_text(normalized.get("title"), 300)
    artist = _clean_text(normalized.get("artist"), 200)
    album = _clean_text(normalized.get("album"), 240)
    album_artist = _clean_text(normalized.get("album_artist") or normalized.get("albumartist"), 200)
    genre = _clean_text(normalized.get("genre"), 120)
    track_number = _bounded_int(normalized.get("track"), 0, 100_000)
    disc_number = _bounded_int(normalized.get("disc"), 0, 10_000)
    year_value = normalized.get("date") or normalized.get("year") or "0"
    year_match = re.search(r"(?:19|20)\d{2}", str(year_value))
    year = int(year_match.group(0)) if year_match else 0
    embedded = ""
    for key in ("syncedlyrics", "synced_lyrics", "lyrics", "unsyncedlyrics", "unsynced_lyrics"):
        if normalized.get(key):
            embedded = str(normalized[key]).replace("\x00", " ")[:MAX_LYRICS_CHARS]
            break
    updates: dict[str, Any] = {
        "title": title,
        "artist": artist,
        "album": album,
        "album_artist": album_artist,
        "genre": genre,
        "track_number": track_number,
        "disc_number": disc_number,
        "year": year,
        "embedded_lyrics": embedded,
    }
    with closing(_connect(engine_module)) as connection:
        current = connection.execute("SELECT * FROM tracks WHERE media_id=?", (clean,)).fetchone()
        if current is None:
            raise MusicWorkspaceError("音乐条目不存在")
        connection.execute(
            """
            UPDATE tracks SET
                title=?, artist=?, album=?, album_artist=?, track_number=?, disc_number=?,
                year=?, genre=?, embedded_lyrics=?, updated_at=CURRENT_TIMESTAMP
            WHERE media_id=?
            """,
            (
                title or current["title"],
                artist or current["artist"],
                album or current["album"],
                album_artist or current["album_artist"],
                track_number or current["track_number"],
                disc_number or current["disc_number"],
                year or current["year"],
                genre or current["genre"],
                embedded or current["embedded_lyrics"],
                clean,
            ),
        )
        connection.commit()
    return get_track(engine_module, clean)


def update_track_metadata(engine_module, media_id: object, values: dict[str, Any]) -> dict[str, Any]:
    clean = _clean_media_id(media_id)
    _track_row(engine_module, clean)
    if not isinstance(values, dict):
        raise MusicWorkspaceError("Music metadata 格式无效")
    allowed = {
        "title": (300, "text"),
        "artist": (200, "text"),
        "album": (240, "text"),
        "albumArtist": (200, "text"),
        "trackNumber": (100_000, "int"),
        "discNumber": (10_000, "int"),
        "year": (9999, "int"),
        "genre": (120, "text"),
        "coverPath": (1000, "text"),
    }
    assignments: list[str] = []
    params: list[Any] = []
    columns = {
        "albumArtist": "album_artist",
        "trackNumber": "track_number",
        "discNumber": "disc_number",
        "coverPath": "cover_path",
    }
    for key, value in values.items():
        spec = allowed.get(key)
        if spec is None:
            continue
        limit, kind = spec
        column = columns.get(key, key)
        if kind == "text":
            clean_value: Any = _clean_text(value, limit)
        else:
            clean_value = _bounded_int(value, 0, limit)
        assignments.append(f"{column}=?")
        params.append(clean_value)
    if assignments:
        with closing(_connect(engine_module)) as connection:
            connection.execute(
                f"UPDATE tracks SET {', '.join(assignments)}, updated_at=CURRENT_TIMESTAMP WHERE media_id=?",  # noqa: S608 - columns are fixed allowlist
                (*params, clean),
            )
            connection.commit()
    return get_track(engine_module, clean)


def set_track_state(
    engine_module,
    media_id: object,
    *,
    favorite: bool | None = None,
    last_position: object | None = None,
    increment_play: bool = False,
) -> dict[str, Any]:
    clean = _clean_media_id(media_id)
    _track_row(engine_module, clean)
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT * FROM tracks WHERE media_id=?", (clean,)).fetchone()
        old_favorite = bool(row["favorite"])
        position = float(row["last_position"] or 0)
        if last_position is not None:
            position = _bounded_float(last_position)
        count = max(0, int(row["play_count"] or 0)) + (1 if increment_play else 0)
        played_at = _utc_now() if increment_play else str(row["last_played_at"] or "")
        connection.execute(
            """
            UPDATE tracks SET favorite=?, play_count=?, last_position=?, last_played_at=?, updated_at=CURRENT_TIMESTAMP
            WHERE media_id=?
            """,
            (1 if (old_favorite if favorite is None else favorite) else 0, count, position, played_at, clean),
        )
        connection.commit()
    return get_track(engine_module, clean)


def _row_to_track(engine_module, row: sqlite3.Row) -> MusicTrack:
    has_lyrics = bool(str(row["embedded_lyrics"] or "")) or _safe_lyrics_path(engine_module, row["lyrics_path"]) is not None
    return MusicTrack(
        media_id=str(row["media_id"]),
        title=str(row["title"] or "Music"),
        artist=str(row["artist"] or ""),
        album=str(row["album"] or ""),
        album_artist=str(row["album_artist"] or ""),
        track_number=max(0, int(row["track_number"] or 0)),
        disc_number=max(0, int(row["disc_number"] or 0)),
        year=max(0, int(row["year"] or 0)),
        genre=str(row["genre"] or ""),
        cover_path=str(row["cover_path"] or ""),
        favorite=bool(row["favorite"]),
        play_count=max(0, int(row["play_count"] or 0)),
        last_position=max(0.0, float(row["last_position"] or 0)),
        last_played_at=str(row["last_played_at"] or ""),
        has_lyrics=has_lyrics,
    )


def get_track(engine_module, media_id: object) -> dict[str, Any]:
    return _row_to_track(engine_module, _track_row(engine_module, media_id)).public_payload()


def songs(
    engine_module,
    *,
    query: object = "",
    favorites_only: bool = False,
    limit: int = 500,
) -> list[dict[str, Any]]:
    sync_music_library(engine_module)
    text = _clean_text(query, 200)
    safe_limit = max(1, min(int(limit), 2000))
    clauses: list[str] = []
    params: list[Any] = []
    if favorites_only:
        clauses.append("favorite=1")
    if text:
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        clauses.append("(title LIKE ? ESCAPE '\\' OR artist LIKE ? ESCAPE '\\' OR album LIKE ? ESCAPE '\\' OR genre LIKE ? ESCAPE '\\')")
        params.extend((pattern, pattern, pattern, pattern))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            f"SELECT * FROM tracks{where} ORDER BY artist, album, disc_number, track_number, title LIMIT ?",  # noqa: S608 - fixed clauses only
            (*params, safe_limit),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        if resolve_media_item_path(engine_module, row["media_id"]) is not None:
            result.append(_row_to_track(engine_module, row).public_payload())
    return result


def albums(engine_module, *, limit: int = 500) -> list[dict[str, Any]]:
    tracks = songs(engine_module, limit=2000)
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for track in tracks:
        album = track["album"] or "Unknown Album"
        artist = track["albumArtist"] or track["artist"] or "Unknown Artist"
        key = (artist, album)
        value = grouped.setdefault(key, {"artist": artist, "album": album, "year": 0, "trackCount": 0, "mediaIds": []})
        value["trackCount"] += 1
        value["mediaIds"].append(track["mediaId"])
        value["year"] = value["year"] or track["year"]
    return list(grouped.values())[: max(1, min(int(limit), 500))]


def artists(engine_module, *, limit: int = 500) -> list[dict[str, Any]]:
    tracks = songs(engine_module, limit=2000)
    grouped: dict[str, dict[str, Any]] = {}
    for track in tracks:
        artist = track["artist"] or track["albumArtist"] or "Unknown Artist"
        value = grouped.setdefault(artist, {"artist": artist, "trackCount": 0, "albums": set()})
        value["trackCount"] += 1
        if track["album"]:
            value["albums"].add(track["album"])
    result = [
        {"artist": key, "trackCount": value["trackCount"], "albumCount": len(value["albums"])}
        for key, value in grouped.items()
    ]
    result.sort(key=lambda item: item["artist"].casefold())
    return result[: max(1, min(int(limit), 500))]


def recently_played(engine_module, *, limit: int = 100) -> list[dict[str, Any]]:
    sync_music_library(engine_module)
    safe_limit = max(1, min(int(limit), 500))
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT * FROM tracks WHERE last_played_at<>'' ORDER BY last_played_at DESC LIMIT ?", (safe_limit,)
        ).fetchall()
    return [_row_to_track(engine_module, row).public_payload() for row in rows]


def most_played(engine_module, *, limit: int = 100) -> list[dict[str, Any]]:
    sync_music_library(engine_module)
    safe_limit = max(1, min(int(limit), 500))
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT * FROM tracks WHERE play_count>0 ORDER BY play_count DESC, last_played_at DESC LIMIT ?", (safe_limit,)
        ).fetchall()
    return [_row_to_track(engine_module, row).public_payload() for row in rows]


def enqueue(engine_module, media_ids: Iterable[object], *, replace: bool = False) -> int:
    clean_ids: list[str] = []
    for value in media_ids:
        clean = _clean_media_id(value)
        _track_row(engine_module, clean)
        if clean not in clean_ids:
            clean_ids.append(clean)
        if len(clean_ids) >= MAX_QUEUE_ITEMS:
            break
    with closing(_connect(engine_module)) as connection:
        if replace:
            connection.execute("DELETE FROM queue_items")
            start = 1
        else:
            row = connection.execute("SELECT COALESCE(MAX(position),0) FROM queue_items").fetchone()
            start = int(row[0] or 0) + 1
        existing = {str(row[0]) for row in connection.execute("SELECT media_id FROM queue_items").fetchall()}
        added = 0
        for media_id in clean_ids:
            if media_id in existing:
                continue
            connection.execute(
                "INSERT INTO queue_items(id, media_id, position) VALUES(?, ?, ?)",
                (uuid4_hex(), media_id, start + added),
            )
            existing.add(media_id)
            added += 1
        connection.commit()
    return added


def uuid4_hex() -> str:
    import uuid

    return uuid.uuid4().hex


def queue_items(engine_module) -> list[dict[str, Any]]:
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute("SELECT id, media_id, position FROM queue_items ORDER BY position, created_at").fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            track = get_track(engine_module, row["media_id"])
        except MusicWorkspaceError:
            continue
        result.append({"id": row["id"], "position": int(row["position"]), "track": track})
    return result


def remove_queue_item(engine_module, item_id: object) -> bool:
    clean = str(item_id or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32}", clean):
        raise MusicWorkspaceError("Queue item ID 无效")
    with closing(_connect(engine_module)) as connection:
        cursor = connection.execute("DELETE FROM queue_items WHERE id=?", (clean,))
        _normalize_queue(connection)
        connection.commit()
        return cursor.rowcount == 1


def move_queue_item(engine_module, item_id: object, new_position: object) -> list[dict[str, Any]]:
    clean = str(item_id or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32}", clean):
        raise MusicWorkspaceError("Queue item ID 无效")
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute("SELECT id FROM queue_items ORDER BY position, created_at").fetchall()
        ids = [str(row["id"]) for row in rows]
        if clean not in ids:
            raise MusicWorkspaceError("Queue item 不存在")
        try:
            target = max(1, min(int(new_position), len(ids)))
        except (TypeError, ValueError):
            target = 1
        ids.remove(clean)
        ids.insert(target - 1, clean)
        for position, value in enumerate(ids, 1):
            connection.execute("UPDATE queue_items SET position=? WHERE id=?", (-position, value))
        for position, value in enumerate(ids, 1):
            connection.execute("UPDATE queue_items SET position=? WHERE id=?", (position, value))
        connection.commit()
    return queue_items(engine_module)


def _normalize_queue(connection: sqlite3.Connection) -> None:
    ids = [str(row[0]) for row in connection.execute("SELECT id FROM queue_items ORDER BY position, created_at").fetchall()]
    for position, value in enumerate(ids, 1):
        connection.execute("UPDATE queue_items SET position=? WHERE id=?", (-position, value))
    for position, value in enumerate(ids, 1):
        connection.execute("UPDATE queue_items SET position=? WHERE id=?", (position, value))


def clear_queue(engine_module) -> None:
    with closing(_connect(engine_module)) as connection:
        connection.execute("DELETE FROM queue_items")
        connection.commit()


def player_state(engine_module) -> dict[str, Any]:
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT * FROM player_state WHERE singleton=1").fetchone()
    return {
        "currentMediaId": str(row["current_media_id"] or ""),
        "repeatMode": str(row["repeat_mode"] or "off"),
        "shuffle": bool(row["shuffle"]),
        "volume": float(row["volume"] or 0),
    }


def update_player_state(
    engine_module,
    *,
    current_media_id: object | None = None,
    repeat_mode: object | None = None,
    shuffle: bool | None = None,
    volume: object | None = None,
) -> dict[str, Any]:
    current = player_state(engine_module)
    media_id = current["currentMediaId"]
    if current_media_id is not None:
        raw = str(current_media_id or "").strip()
        if raw:
            media_id = _clean_media_id(raw)
            _track_row(engine_module, media_id)
        else:
            media_id = ""
    repeat = current["repeatMode"]
    if repeat_mode is not None:
        repeat = str(repeat_mode or "off").strip().lower()
        if repeat not in _REPEAT_MODES:
            raise MusicWorkspaceError("Repeat mode 必须是 off / all / one")
    shuffle_value = current["shuffle"] if shuffle is None else bool(shuffle)
    volume_value = current["volume"] if volume is None else _bounded_float(volume, 0.0, 1.0)
    with closing(_connect(engine_module)) as connection:
        connection.execute(
            """
            UPDATE player_state SET current_media_id=?, repeat_mode=?, shuffle=?, volume=?, updated_at=CURRENT_TIMESTAMP
            WHERE singleton=1
            """,
            (media_id, repeat, 1 if shuffle_value else 0, volume_value),
        )
        connection.commit()
    return player_state(engine_module)


def run_music_workspace_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        data = root / "data"
        downloads = root / "downloads"
        state.mkdir()
        data.mkdir()
        downloads.mkdir()
        media_id = "a" * 32
        audio = downloads / "Artist - Song.mp3"
        audio.write_bytes(b"demo")
        item = {
            "id": media_id,
            "title": "Artist - Song",
            "fileName": audio.name,
            "mediaType": "audio",
            "available": True,
            "sourceHost": "example.com",
        }

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

        with patch("music_workspace.list_media_items", side_effect=lambda **kwargs: [item] if kwargs.get("offset", 0) == 0 else []), patch(
            "music_workspace.resolve_media_item_path", return_value=audio.resolve()
        ):
            assert sync_music_library(Engine) == 1
            track = get_track(Engine, media_id)
            assert track["artist"] == "Artist"
            update_track_metadata(Engine, media_id, {"album": "Album", "year": 2026, "genre": "Demo"})
            assert albums(Engine)[0]["album"] == "Album"
            assert artists(Engine)[0]["artist"] == "Artist"
            set_track_state(Engine, media_id, favorite=True, increment_play=True, last_position=12.5)
            assert songs(Engine, favorites_only=True)[0]["favorite"] is True
            assert recently_played(Engine)[0]["mediaId"] == media_id
            assert most_played(Engine)[0]["playCount"] == 1
            lrc = root / "demo.lrc"
            lrc.write_text("[00:01.50]Hello\n[01:02.003]World", encoding="utf-8")
            assert attach_lrc(Engine, media_id, lrc) == 2
            assert lyrics(Engine, media_id)["synced"][0] == {"time": 1.5, "text": "Hello"}
            assert enqueue(Engine, [media_id]) == 1
            assert len(queue_items(Engine)) == 1
            update_player_state(Engine, current_media_id=media_id, repeat_mode="all", shuffle=True, volume=0.7)
            assert player_state(Engine)["repeatMode"] == "all"
            clear_queue(Engine)
            assert queue_items(Engine) == []
