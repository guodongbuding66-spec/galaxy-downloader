from __future__ import annotations

from urllib.parse import urlsplit

from headless_music_api import HeadlessMusicApiError
from music_player_navigation import MusicPlayerNavigationError, navigate, seek


class HeadlessMusicPlayerHttpMixin:
    """Bounded Previous/Next/Seek commands layered over the existing Music API."""

    def _music_player_error(self, exc: Exception) -> None:
        status = int(getattr(exc, "status", 400) or 400)
        code = str(getattr(exc, "code", "MUSIC_PLAYER_INVALID_REQUEST") or "MUSIC_PLAYER_INVALID_REQUEST")
        self._json(status, {"ok": False, "error": str(exc), "code": code})

    def do_POST(self) -> None:  # noqa: N802
        parts = [part for part in urlsplit(self.path).path.split("/") if part]
        if not (len(parts) == 4 and parts[:3] == ["v1", "music", "player"]):
            super().do_POST()
            return

        action = parts[3]
        if action not in {"next", "previous", "seek"}:
            super().do_POST()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return

        music_api = getattr(self, "music_api", None)
        if music_api is None:
            self._json(503, {"ok": False, "error": "music api is unavailable"})
            return

        try:
            if action == "seek":
                payload = self._read_json()
                if not isinstance(payload, dict) or "positionSeconds" not in payload:
                    raise MusicPlayerNavigationError(
                        "positionSeconds is required",
                        status=400,
                        code="MUSIC_SEEK_POSITION_REQUIRED",
                    )
                result = seek(music_api, payload.get("positionSeconds"))
            else:
                result = navigate(music_api, action)
            self._json(200, {"ok": True, **result})
        except (MusicPlayerNavigationError, HeadlessMusicApiError) as exc:
            self._music_player_error(exc)
        except Exception:
            # Do not serialize implementation details, local paths or arbitrary
            # downstream exception text across the headless boundary.
            self._json(
                502,
                {
                    "ok": False,
                    "error": "music player operation failed",
                    "code": "MUSIC_PLAYER_OPERATION_FAILED",
                },
            )
