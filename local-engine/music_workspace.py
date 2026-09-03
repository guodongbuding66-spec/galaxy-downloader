from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from media_library import list_media_items, resolve_media_item_path
from runtime_storage import state_dir as runtime_state_dir

DATABASE_FILENAME = "music-library.sqlite3"
LRC_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\](.*)")


class MusicWorkspaceError(RuntimeError):
    pass


def _db_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / DATABASE_FILENAME


def _connect(engine_module) -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS music_state (
          media_id TEXT PRIMARY KEY,
          favorite INTEGER NOT NULL DEFAULT 0,
          play_count INTEGER NOT NULL DEFAULT 0,
          last_position REAL NOT NULL DEFAULT 0,
          lyrics_path TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return connection


def parse_lrc(text: object) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in str(text or "").replace("\r", "").split("\n"):
        for match in LRC_RE.finditer(line):
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            fraction = match.group(3) or "0"
            millis = int(fraction.ljust(3, "0")[:3])
            timestamp = minutes * 60 + seconds + millis / 1000.0
            lyric = match.group(4).strip()[:2000]
            if lyric:
                rows.append({"time": round(timestamp, 3), "text": lyric})
            if len(rows) >= 50_000:
                return sorted(rows, key=lambda item: item["time"])
    return sorted(rows, key=lambda item: item["time"])


def _music_item(engine_module, media_id: object) -> tuple[str, Path]:
    clean_id = str(media_id or "").strip().lower()
    path = resolve_media_item_path(engine_module, clean_id)
    if path is None or path.suffix.lower() not in {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus"}:
        raise MusicWorkspaceError("音乐条目不存在")
    return clean_id, path


def attach_lyrics(engine_module, media_id: object, lyrics_file: object) -> int:
    clean_id, media = _music_item(engine_module, media_id)
    try:
        source = Path(str(lyrics_file or "")).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise MusicWorkspaceError("歌词文件不存在") from exc
    if not source.is_file() or source.is_symlink() or source.suffix.lower() != ".lrc" or source.stat().st_size > 10 * 1024 * 1024:
        raise MusicWorkspaceError("仅支持不超过 10 MB 的 LRC 歌词")
    target = media.with_suffix(".lrc")
    if source != target:
        target.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    count = len(parse_lrc(target.read_text(encoding="utf-8", errors="replace")))
    with closing(_connect(engine_module)) as connection:
        connection.execute(
            "INSERT INTO music_state(media_id,lyrics_path) VALUES(?,?) ON CONFLICT(media_id) DO UPDATE SET lyrics_path=excluded.lyrics_path,updated_at=CURRENT_TIMESTAMP",
            (clean_id, str(target)),
        )
        connection.commit()
    return count


def synced_lyrics(engine_module, media_id: object) -> list[dict[str, Any]]:
    clean_id, media = _music_item(engine_module, media_id)
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT lyrics_path FROM music_state WHERE media_id=?", (clean_id,)).fetchone()
    candidates = [Path(str(row["lyrics_path"]))] if row and row["lyrics_path"] else []
    candidates.append(media.with_suffix(".lrc"))
    for path in candidates:
        if path.is_file() and not path.is_symlink():
            return parse_lrc(path.read_text(encoding="utf-8", errors="replace"))
    return []


def set_music_state(engine_module, media_id: object, *, favorite: bool | None = None, last_position: object | None = None, increment_play: bool = False) -> None:
    clean_id, _media = _music_item(engine_module, media_id)
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT * FROM music_state WHERE media_id=?", (clean_id,)).fetchone()
        old_favorite = bool(row["favorite"]) if row else False
        old_count = int(row["play_count"] or 0) if row else 0
        old_position = float(row["last_position"] or 0) if row else 0.0
        lyrics_path = str(row["lyrics_path"] or "") if row else ""
        try:
            position = old_position if last_position is None else max(0.0, min(float(last_position), 30 * 24 * 3600))
        except (TypeError, ValueError):
            position = old_position
        connection.execute(
            "INSERT INTO music_state(media_id,favorite,play_count,last_position,lyrics_path) VALUES(?,?,?,?,?) ON CONFLICT(media_id) DO UPDATE SET favorite=excluded.favorite,play_count=excluded.play_count,last_position=excluded.last_position,lyrics_path=excluded.lyrics_path,updated_at=CURRENT_TIMESTAMP",
            (clean_id, 1 if (old_favorite if favorite is None else favorite) else 0, old_count + (1 if increment_play else 0), position, lyrics_path),
        )
        connection.commit()


def music_library_v2(engine_module, *, query: object = "", favorites_only: bool = False) -> list[dict[str, Any]]:
    text = " ".join(str(query or "").split()).strip().lower()
    media = [item for item in list_media_items(engine_module, limit=500, media_type="audio") if item.get("available")]
    with closing(_connect(engine_module)) as connection:
        states = {str(row["media_id"]): row for row in connection.execute("SELECT * FROM music_state").fetchall()}
    result: list[dict[str, Any]] = []
    for item in media:
        state = states.get(str(item["id"]))
        favorite = bool(state["favorite"]) if state else False
        if favorites_only and not favorite:
            continue
        haystack = f"{item.get('title','')} {item.get('fileName','')} {item.get('sourceHost','')}".lower()
        if text and text not in haystack:
            continue
        result.append({
            **item,
            "favorite": favorite,
            "playCount": int(state["play_count"] or 0) if state else 0,
            "lastPosition": float(state["last_position"] or 0) if state else 0.0,
            "hasSyncedLyrics": bool(synced_lyrics(engine_module, item["id"])),
        })
    return result


def run_music_workspace_self_test() -> None:
    rows = parse_lrc("[00:01.50]Hello\n[01:02.003]World")
    assert rows[0] == {"time": 1.5, "text": "Hello"}
    assert rows[1]["time"] == 62.003
