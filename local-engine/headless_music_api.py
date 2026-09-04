from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from media_library import list_media_items, sync_media_library
from music_workspace import (
    MAX_QUEUE_ITEMS,
    MusicWorkspaceError,
    albums,
    artists,
    clear_queue,
    enqueue,
    get_track,
    lyrics,
    most_played,
    move_queue_item,
    player_state,
    queue_items,
    recently_played,
    remove_queue_item,
    set_track_state,
    songs,
    sync_music_library,
    update_player_state,
    update_track_metadata,
)
from platform_paths import resolve_platform_paths

_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
_QUEUE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_REPEAT_MODES = frozenset({"off", "all", "one"})
_MAX_POSITION_SECONDS = 30 * 24 * 3600.0
_ALLOWED_METADATA_FIELDS = frozenset(
    {
        "title",
        "artist",
        "album",
        "albumArtist",
        "trackNumber",
        "discNumber",
        "year",
        "genre",
    }
)


class HeadlessMusicApiError(RuntimeError):
    status = 400
    code = "MUSIC_INVALID_REQUEST"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class HeadlessMusicNotFoundError(HeadlessMusicApiError):
    status = 404
    code = "MUSIC_NOT_FOUND"


class HeadlessMusicConflictError(HeadlessMusicApiError):
    status = 409
    code = "MUSIC_CONFLICT"


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def _clean_media_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _MEDIA_ID_RE.fullmatch(clean):
        raise HeadlessMusicApiError("invalid media id", code="MUSIC_INVALID_MEDIA_ID")
    return clean


def _clean_queue_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _QUEUE_ID_RE.fullmatch(clean):
        raise HeadlessMusicApiError("invalid queue item id", code="MUSIC_INVALID_QUEUE_ITEM_ID")
    return clean


def _safe_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()[:limit]


def _safe_directory(value: Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    if raw.exists() and raw.is_symlink():
        raise HeadlessMusicApiError(f"{label} cannot be a symbolic link")
    resolved = raw.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _finite_float(value: object, *, label: str, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise HeadlessMusicApiError(f"{label} must be a number") from exc
    if not math.isfinite(parsed) or parsed < low or parsed > high:
        raise HeadlessMusicApiError(f"{label} must be between {low:g} and {high:g}")
    return parsed


def _strict_bool(value: object, *, label: str) -> bool:
    if isinstance(value, bool):
        return value
    raise HeadlessMusicApiError(f"{label} must be a boolean")


def _translate_core_error(exc: Exception) -> HeadlessMusicApiError:
    detail = str(exc).strip()
    not_found = {
        "音乐媒体不存在或不可用": ("music media not found", "MUSIC_MEDIA_NOT_FOUND"),
        "音乐媒体不存在": ("music media not found", "MUSIC_MEDIA_NOT_FOUND"),
        "音乐条目不存在": ("music track not found", "MUSIC_TRACK_NOT_FOUND"),
        "Queue item 不存在": ("queue item not found", "MUSIC_QUEUE_ITEM_NOT_FOUND"),
    }
    if detail in not_found:
        message, code = not_found[detail]
        return HeadlessMusicNotFoundError(message, code=code)
    if "数量超过安全上限" in detail:
        return HeadlessMusicConflictError("music resource limit reached", code="MUSIC_LIMIT_REACHED")
    return HeadlessMusicApiError(detail or "music operation failed")


def _public_track(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    # coverPath is a local filesystem implementation detail. It may be useful
    # to the native desktop, but must never cross the headless boundary.
    result.pop("coverPath", None)
    return result


def _public_tracks(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_public_track(value) for value in values]


def _public_queue(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for value in values:
        item = dict(value)
        track = item.get("track")
        if isinstance(track, Mapping):
            item["track"] = _public_track(track)
        result.append(item)
    return result


@dataclass(frozen=True)
class HeadlessMusicContext:
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


def build_headless_music_context(
    download_root: Path,
    *,
    program_dir: Path | None = None,
    data_dir: Path | None = None,
    state_dir: Path | None = None,
) -> HeadlessMusicContext:
    program = Path(program_dir or Path(__file__).resolve().parent).expanduser().resolve(strict=False)
    paths = resolve_platform_paths(program_dir=program)
    data = _safe_directory(Path(data_dir or paths.data_dir), label="music data directory")
    state = _safe_directory(Path(state_dir or paths.state_dir), label="music state directory")
    downloads = _safe_directory(Path(download_root), label="music download root")
    return HeadlessMusicContext(program, data, state, downloads)


class HeadlessMusicApi:
    def __init__(
        self,
        download_root: Path,
        *,
        context: HeadlessMusicContext | None = None,
        program_dir: Path | None = None,
        data_dir: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.context = context or build_headless_music_context(
            download_root,
            program_dir=program_dir,
            data_dir=data_dir,
            state_dir=state_dir,
        )

    def sync(self) -> dict[str, Any]:
        try:
            synced = sync_music_library(self.context)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"synced": synced}

    def list_songs(
        self,
        *,
        query: object = "",
        favorites_only: object = False,
        limit: object = 500,
    ) -> dict[str, Any]:
        if not isinstance(favorites_only, bool):
            raise HeadlessMusicApiError("favoritesOnly must be a boolean")
        text = _safe_text(query, 200)
        safe_limit = _bounded_int(limit, 500, 1, 2000)
        try:
            rows = songs(self.context, query=text, favorites_only=favorites_only, limit=safe_limit)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {
            "songs": _public_tracks(rows),
            "query": text,
            "favoritesOnly": favorites_only,
            "limit": safe_limit,
        }

    def song_detail(self, media_id: object) -> dict[str, Any]:
        clean = _clean_media_id(media_id)
        try:
            track = get_track(self.context, clean)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"song": _public_track(track)}

    def song_lyrics(self, media_id: object) -> dict[str, Any]:
        clean = _clean_media_id(media_id)
        try:
            result = lyrics(self.context, clean)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"mediaId": clean, "lyrics": result}

    def list_albums(self, *, limit: object = 500) -> dict[str, Any]:
        safe_limit = _bounded_int(limit, 500, 1, 500)
        try:
            rows = albums(self.context, limit=safe_limit)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"albums": rows, "limit": safe_limit}

    def list_artists(self, *, limit: object = 500) -> dict[str, Any]:
        safe_limit = _bounded_int(limit, 500, 1, 500)
        try:
            rows = artists(self.context, limit=safe_limit)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"artists": rows, "limit": safe_limit}

    def recent(self, *, limit: object = 100) -> dict[str, Any]:
        safe_limit = _bounded_int(limit, 100, 1, 500)
        try:
            rows = recently_played(self.context, limit=safe_limit)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"songs": _public_tracks(rows), "limit": safe_limit}

    def most_played(self, *, limit: object = 100) -> dict[str, Any]:
        safe_limit = _bounded_int(limit, 100, 1, 500)
        try:
            rows = most_played(self.context, limit=safe_limit)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"songs": _public_tracks(rows), "limit": safe_limit}

    def update_metadata(self, media_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        clean = _clean_media_id(media_id)
        values = {key: payload[key] for key in _ALLOWED_METADATA_FIELDS if key in payload}
        if not values:
            raise HeadlessMusicApiError("music metadata payload is empty")
        # Deliberately exclude coverPath: headless clients may not set local paths.
        try:
            track = update_track_metadata(self.context, clean, values)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"song": _public_track(track)}

    def update_song_state(self, media_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        clean = _clean_media_id(media_id)
        recognized = {key for key in ("favorite", "lastPosition", "incrementPlay") if key in payload}
        if not recognized:
            raise HeadlessMusicApiError("music state payload is empty")
        favorite = _strict_bool(payload.get("favorite"), label="favorite") if "favorite" in payload else None
        position = None
        if "lastPosition" in payload:
            position = _finite_float(
                payload.get("lastPosition"),
                label="lastPosition",
                low=0.0,
                high=_MAX_POSITION_SECONDS,
            )
        increment = (
            _strict_bool(payload.get("incrementPlay"), label="incrementPlay")
            if "incrementPlay" in payload
            else False
        )
        try:
            track = set_track_state(
                self.context,
                clean,
                favorite=favorite,
                last_position=position,
                increment_play=increment,
            )
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"song": _public_track(track)}

    def queue(self) -> dict[str, Any]:
        try:
            rows = queue_items(self.context)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"queue": _public_queue(rows), "count": len(rows)}

    def enqueue(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        raw_ids = payload.get("mediaIds")
        if not isinstance(raw_ids, (list, tuple)) or not raw_ids:
            raise HeadlessMusicApiError("mediaIds must be a non-empty array")
        if len(raw_ids) > MAX_QUEUE_ITEMS:
            raise HeadlessMusicConflictError("music queue limit reached", code="MUSIC_QUEUE_LIMIT_REACHED")
        media_ids = [_clean_media_id(value) for value in raw_ids]
        replace = _strict_bool(payload.get("replace"), label="replace") if "replace" in payload else False
        try:
            added = enqueue(self.context, media_ids, replace=replace)
            rows = queue_items(self.context)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"added": added, "queue": _public_queue(rows), "count": len(rows)}

    def move_queue_item(self, item_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        clean = _clean_queue_id(item_id)
        if "position" not in payload:
            raise HeadlessMusicApiError("position is required")
        try:
            position = int(payload.get("position"))
        except (TypeError, ValueError) as exc:
            raise HeadlessMusicApiError("position must be an integer") from exc
        if position < 1 or position > MAX_QUEUE_ITEMS:
            raise HeadlessMusicApiError(f"position must be between 1 and {MAX_QUEUE_ITEMS}")
        try:
            rows = move_queue_item(self.context, clean, position)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"queue": _public_queue(rows), "count": len(rows)}

    def remove_queue_item(self, item_id: object) -> dict[str, Any]:
        clean = _clean_queue_id(item_id)
        try:
            deleted = remove_queue_item(self.context, clean)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        if not deleted:
            raise HeadlessMusicNotFoundError("queue item not found", code="MUSIC_QUEUE_ITEM_NOT_FOUND")
        return {"queueItemId": clean, "deleted": True}

    def clear_queue(self) -> dict[str, Any]:
        try:
            clear_queue(self.context)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"cleared": True, "queue": [], "count": 0}

    def player(self) -> dict[str, Any]:
        try:
            state = player_state(self.context)
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"player": state}

    def update_player(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        recognized = {key for key in ("currentMediaId", "repeatMode", "shuffle", "volume") if key in payload}
        if not recognized:
            raise HeadlessMusicApiError("player state payload is empty")

        current_media_id: object | None = None
        if "currentMediaId" in payload:
            raw = str(payload.get("currentMediaId") or "").strip().lower()
            current_media_id = _clean_media_id(raw) if raw else ""

        repeat_mode: object | None = None
        if "repeatMode" in payload:
            repeat_mode = str(payload.get("repeatMode") or "").strip().lower()
            if repeat_mode not in _REPEAT_MODES:
                raise HeadlessMusicApiError("repeatMode must be off, all, or one")

        shuffle: bool | None = None
        if "shuffle" in payload:
            shuffle = _strict_bool(payload.get("shuffle"), label="shuffle")

        volume: float | None = None
        if "volume" in payload:
            volume = _finite_float(payload.get("volume"), label="volume", low=0.0, high=1.0)

        try:
            state = update_player_state(
                self.context,
                current_media_id=current_media_id,
                repeat_mode=repeat_mode,
                shuffle=shuffle,
                volume=volume,
            )
        except MusicWorkspaceError as exc:
            raise _translate_core_error(exc) from exc
        return {"player": state}


def run_headless_music_api_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        program = root / "program"
        data = root / "data"
        state = root / "state"
        downloads = root / "downloads"
        for target in (program, data, state, downloads):
            target.mkdir()

        audio = downloads / "Artist - Song.mp3"
        audio.write_bytes(b"music")
        context = HeadlessMusicContext(program, data, state, downloads)
        history = [
            {
                "state": "completed",
                "filePath": str(audio),
                "fileName": audio.name,
                "label": "Artist - Song",
                "durationSeconds": 180,
                "sourceUrl": "https://example.com/song",
                "finishedAt": "2026-09-04T00:00:00Z",
            }
        ]
        assert sync_media_library(context, history) == 1
        media_id = list_media_items(context, media_type="audio", limit=1)[0]["id"]
        api = HeadlessMusicApi(downloads, context=context)

        assert api.sync()["synced"] == 1
        listed = api.list_songs(limit=10)
        assert listed["songs"][0]["mediaId"] == media_id
        assert "coverPath" not in listed["songs"][0]

        detail = api.song_detail(media_id)["song"]
        assert detail["mediaId"] == media_id and "coverPath" not in detail
        metadata = api.update_metadata(media_id, {"album": "Album", "genre": "Demo", "coverPath": "/tmp/nope"})["song"]
        assert metadata["album"] == "Album" and "coverPath" not in metadata
        state_payload = api.update_song_state(media_id, {"favorite": True, "lastPosition": 12.5, "incrementPlay": True})["song"]
        assert state_payload["favorite"] is True and state_payload["playCount"] == 1
        assert api.list_songs(favorites_only=True)["songs"][0]["mediaId"] == media_id
        assert api.recent()["songs"][0]["mediaId"] == media_id
        assert api.most_played()["songs"][0]["mediaId"] == media_id
        assert api.list_albums()["albums"][0]["album"] == "Album"
        assert api.list_artists()["artists"][0]["artist"] == "Artist"
        assert api.song_lyrics(media_id)["lyrics"]["kind"] == "none"

        queued = api.enqueue({"mediaIds": [media_id], "replace": True})
        assert queued["count"] == 1 and "coverPath" not in queued["queue"][0]["track"]
        queue_id = queued["queue"][0]["id"]
        assert api.move_queue_item(queue_id, {"position": 1})["count"] == 1
        assert api.update_player({"currentMediaId": media_id, "repeatMode": "all", "shuffle": True, "volume": 0.7})["player"]["repeatMode"] == "all"
        assert api.player()["player"]["currentMediaId"] == media_id
        assert api.remove_queue_item(queue_id)["deleted"] is True
        assert api.clear_queue()["count"] == 0

        try:
            api.update_song_state(media_id, {"lastPosition": float("nan")})
        except HeadlessMusicApiError:
            pass
        else:
            raise AssertionError("non-finite music position was accepted")

        try:
            api.update_player({"volume": 2})
        except HeadlessMusicApiError:
            pass
        else:
            raise AssertionError("out-of-range music volume was accepted")
