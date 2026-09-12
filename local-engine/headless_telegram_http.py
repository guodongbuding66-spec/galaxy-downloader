from __future__ import annotations

from urllib.parse import urlsplit

from headless_service import _safe_detail
from headless_telegram_api import HeadlessTelegramApi, HeadlessTelegramApiError


def _path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


class HeadlessTelegramHttpMixin:
    """Composable authenticated `/v1/telegram/*` settings, secret and upload routes."""

    @property
    def telegram_api(self) -> HeadlessTelegramApi | None:
        return self.server.telegram_api  # type: ignore[attr-defined]

    def _telegram_unavailable(self) -> bool:
        if self.telegram_api is not None:
            return False
        self._json(  # type: ignore[attr-defined]
            503,
            {"ok": False, "error": "telegram api is unavailable", "code": "TELEGRAM_UNAVAILABLE"},
        )
        return True

    def _telegram_error(self, exc: HeadlessTelegramApiError) -> None:
        self._json(  # type: ignore[attr-defined]
            exc.status,
            {"ok": False, "error": _safe_detail(exc), "code": exc.code},
        )

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path  # type: ignore[attr-defined]
        if not path.startswith("/v1/telegram"):
            super().do_GET()  # type: ignore[misc]
            return
        if not self._authorized():  # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "unauthorized"})  # type: ignore[attr-defined]
            return
        if self._telegram_unavailable():
            return
        try:
            parts = _path_parts(path)
            if parts == ["v1", "telegram", "status"]:
                result = self.telegram_api.status()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "telegram", "settings"]:
                result = self.telegram_api.settings()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            self._json(404, {"ok": False, "error": "not found"})  # type: ignore[attr-defined]
        except HeadlessTelegramApiError as exc:
            self._telegram_error(exc)
        except Exception:
            self._json(502, {"ok": False, "error": "telegram request failed"})  # type: ignore[attr-defined]

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path  # type: ignore[attr-defined]
        if not path.startswith("/v1/telegram"):
            super().do_POST()  # type: ignore[misc]
            return
        if not self._authorized():  # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "unauthorized"})  # type: ignore[attr-defined]
            return
        if self._telegram_unavailable():
            return
        try:
            parts = _path_parts(path)
            if parts == ["v1", "telegram", "settings"]:
                result = self.telegram_api.save_settings(self._read_json())  # type: ignore[union-attr,attr-defined]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "telegram", "bot-token"]:
                result = self.telegram_api.save_bot_token(self._read_json())  # type: ignore[union-attr,attr-defined]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "telegram", "bot-token", "clear"]:
                result = self.telegram_api.clear_bot_token(self._read_json())  # type: ignore[union-attr,attr-defined]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "telegram", "upload"]:
                result = self.telegram_api.upload_media(self._read_json())  # type: ignore[union-attr,attr-defined]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            self._json(404, {"ok": False, "error": "not found"})  # type: ignore[attr-defined]
        except HeadlessTelegramApiError as exc:
            self._telegram_error(exc)
        except ValueError as exc:
            self._json(  # type: ignore[attr-defined]
                400,
                {"ok": False, "error": _safe_detail(exc), "code": "TELEGRAM_INVALID_REQUEST"},
            )
        except Exception:
            self._json(502, {"ok": False, "error": "telegram request failed"})  # type: ignore[attr-defined]
