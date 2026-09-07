from __future__ import annotations

import hashlib
import math
from typing import Any, Mapping


MAX_SEEK_SECONDS = 30 * 24 * 3600.0
_DIRECTIONS = frozenset({"next", "previous"})


class MusicPlayerNavigationError(RuntimeError):
    status = 409
    code = "MUSIC_PLAYER_CONFLICT"

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        if status is not None:
            self.status = status
        if code:
            self.code = code


def _media_id(track: Mapping[str, Any] | None) -> str:
    if not isinstance(track, Mapping):
        return ""
    return str(track.get("mediaId") or "").strip().lower()


def _queue_rows(api) -> list[dict[str, Any]]:
    payload = api.queue()
    raw = payload.get("queue") if isinstance(payload, Mapping) else None
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        track = item.get("track")
        media_id = _media_id(track if isinstance(track, Mapping) else None)
        item_id = str(item.get("id") or "").strip().lower()
        if not media_id or not item_id:
            continue
        try:
            position = max(1, int(item.get("position") or 1))
        except (TypeError, ValueError):
            position = 1
        rows.append({"id": item_id, "position": position, "track": dict(track)})
    rows.sort(key=lambda row: (row["position"], row["id"]))
    return rows


def _shuffle_key(row: Mapping[str, Any]) -> bytes:
    # Queue item IDs are random UUIDs. Hashing them gives a stable pseudo-random
    # order for the life of the queue without storing or exposing another seed.
    return hashlib.sha256(str(row.get("id") or "").encode("ascii", errors="ignore")).digest()


def playback_order(api) -> list[dict[str, Any]]:
    rows = _queue_rows(api)
    player_payload = api.player()
    player = player_payload.get("player") if isinstance(player_payload, Mapping) else {}
    if isinstance(player, Mapping) and bool(player.get("shuffle", False)):
        rows.sort(key=_shuffle_key)
    return rows


def navigate(api, direction: object) -> dict[str, Any]:
    action = str(direction or "").strip().lower()
    if action not in _DIRECTIONS:
        raise MusicPlayerNavigationError(
            "direction must be next or previous",
            status=400,
            code="MUSIC_PLAYER_DIRECTION_INVALID",
        )

    player_payload = api.player()
    player = dict(player_payload.get("player") or {}) if isinstance(player_payload, Mapping) else {}
    rows = playback_order(api)
    if not rows:
        raise MusicPlayerNavigationError("music queue is empty", code="MUSIC_QUEUE_EMPTY")

    current_media_id = str(player.get("currentMediaId") or "").strip().lower()
    current_index = next(
        (index for index, row in enumerate(rows) if _media_id(row.get("track")) == current_media_id),
        None,
    )

    if current_index is None:
        target_index = 0 if action == "next" else len(rows) - 1
        boundary = False
    else:
        delta = 1 if action == "next" else -1
        candidate = current_index + delta
        if 0 <= candidate < len(rows):
            target_index = candidate
            boundary = False
        elif str(player.get("repeatMode") or "off").strip().lower() == "all":
            target_index = 0 if action == "next" else len(rows) - 1
            boundary = True
        else:
            current_row = rows[current_index]
            return {
                "moved": False,
                "boundary": True,
                "direction": action,
                "player": player,
                "song": dict(current_row["track"]),
            }

    target = rows[target_index]
    target_media_id = _media_id(target.get("track"))
    updated_payload = api.update_player({"currentMediaId": target_media_id})
    updated_player = dict(updated_payload.get("player") or {}) if isinstance(updated_payload, Mapping) else {}
    return {
        "moved": target_media_id != current_media_id,
        "boundary": boundary,
        "direction": action,
        "player": updated_player,
        "song": dict(target["track"]),
    }


def seek(api, position_seconds: object) -> dict[str, Any]:
    try:
        position = float(position_seconds)
    except (TypeError, ValueError) as exc:
        raise MusicPlayerNavigationError(
            "positionSeconds must be a number",
            status=400,
            code="MUSIC_SEEK_POSITION_INVALID",
        ) from exc
    if not math.isfinite(position) or position < 0.0 or position > MAX_SEEK_SECONDS:
        raise MusicPlayerNavigationError(
            f"positionSeconds must be between 0 and {MAX_SEEK_SECONDS:g}",
            status=400,
            code="MUSIC_SEEK_POSITION_INVALID",
        )

    player_payload = api.player()
    player = dict(player_payload.get("player") or {}) if isinstance(player_payload, Mapping) else {}
    current_media_id = str(player.get("currentMediaId") or "").strip().lower()
    if not current_media_id:
        raise MusicPlayerNavigationError("no current music track", code="MUSIC_PLAYER_NO_CURRENT_TRACK")

    state_payload = api.update_song_state(current_media_id, {"lastPosition": position})
    song = dict(state_payload.get("song") or {}) if isinstance(state_payload, Mapping) else {}
    return {
        "positionSeconds": position,
        "player": player,
        "song": song,
    }


def run_music_player_navigation_self_test() -> None:
    class FakeApi:
        def __init__(self) -> None:
            self._player = {"currentMediaId": "", "repeatMode": "off", "shuffle": False, "volume": 1.0}
            self._queue = [
                {"id": "1" * 32, "position": 1, "track": {"mediaId": "a" * 32, "title": "A", "lastPosition": 0.0}},
                {"id": "2" * 32, "position": 2, "track": {"mediaId": "b" * 32, "title": "B", "lastPosition": 4.0}},
            ]

        def queue(self):
            return {"queue": [dict(row) for row in self._queue]}

        def player(self):
            return {"player": dict(self._player)}

        def update_player(self, payload):
            self._player.update(payload)
            return self.player()

        def update_song_state(self, media_id, payload):
            for row in self._queue:
                if row["track"]["mediaId"] == media_id:
                    row["track"]["lastPosition"] = float(payload["lastPosition"])
                    return {"song": dict(row["track"])}
            raise RuntimeError("missing track")

    api = FakeApi()
    first = navigate(api, "next")
    assert first["song"]["mediaId"] == "a" * 32
    second = navigate(api, "next")
    assert second["song"]["mediaId"] == "b" * 32
    boundary = navigate(api, "next")
    assert boundary["moved"] is False and boundary["boundary"] is True
    api._player["repeatMode"] = "all"
    wrapped = navigate(api, "next")
    assert wrapped["song"]["mediaId"] == "a" * 32 and wrapped["boundary"] is True
    result = seek(api, 12.5)
    assert result["positionSeconds"] == 12.5
    assert result["song"]["lastPosition"] == 12.5
