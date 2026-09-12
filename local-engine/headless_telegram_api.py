from __future__ import annotations

from pathlib import Path
from typing import Any

from headless_transfer_api import HeadlessTransferContext, build_headless_transfer_context
from telegram_transfer import (
    SEND_MODES,
    TelegramTransferError,
    TelegramUploadSettings,
    load_telegram_upload_settings,
    save_telegram_upload_settings,
    telegram_bot_token_configured,
)

_ALLOWED_SETTINGS_FIELDS = frozenset({"mode", "chatId", "sendAs", "userAdapter"})


class HeadlessTelegramApiError(RuntimeError):
    status = 400
    code = "TELEGRAM_INVALID_REQUEST"

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        if status is not None:
            self.status = int(status)
        if code:
            self.code = str(code)


def _validation_message(exc: BaseException) -> str:
    text = " ".join(str(exc or "").split()).strip()
    return (text or "Telegram settings request failed")[:500]


class HeadlessTelegramApi:
    """Authenticated facade for Telegram public upload settings only.

    Secret mutation and file upload are intentionally separate contracts. This API
    never reads or returns the Bot Token value; only configured/not-configured state
    is public.
    """

    def __init__(
        self,
        download_root: Path,
        *,
        context: HeadlessTransferContext | None = None,
        program_dir: Path | None = None,
        data_dir: Path | None = None,
        state_dir: Path | None = None,
        tools_dir: Path | None = None,
    ) -> None:
        self.context = context or build_headless_transfer_context(
            download_root,
            program_dir=program_dir,
            data_dir=data_dir,
            state_dir=state_dir,
            tools_dir=tools_dir,
        )

    def _current(self) -> TelegramUploadSettings:
        try:
            return load_telegram_upload_settings(self.context)
        except Exception as exc:
            raise HeadlessTelegramApiError(
                "Telegram settings are unavailable",
                status=503,
                code="TELEGRAM_SETTINGS_UNAVAILABLE",
            ) from exc

    def _token_configured(self) -> bool:
        try:
            return bool(telegram_bot_token_configured(self.context))
        except Exception as exc:
            raise HeadlessTelegramApiError(
                "Telegram settings are unavailable",
                status=503,
                code="TELEGRAM_SETTINGS_UNAVAILABLE",
            ) from exc

    def status(self) -> dict[str, Any]:
        settings = self._current()
        return {
            "settingsSupported": True,
            "secretMutationSupported": False,
            "uploadEndpointSupported": False,
            "botTokenConfigured": self._token_configured(),
            "modes": ["bot", "user"],
            "sendAsModes": list(SEND_MODES),
            "settings": settings.public_payload(),
        }

    def settings(self) -> dict[str, Any]:
        current = self._current()
        return {"settings": current.public_payload(), "botTokenConfigured": self._token_configured()}

    def save_settings(self, payload: object) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HeadlessTelegramApiError("Telegram settings request must be a JSON object")
        unknown = sorted(str(key) for key in payload if key not in _ALLOWED_SETTINGS_FIELDS)
        if unknown:
            raise HeadlessTelegramApiError("Telegram settings request contains unsupported fields")

        current = self._current()
        candidate = TelegramUploadSettings(
            mode=payload.get("mode", current.mode),
            chat_id=payload.get("chatId", current.chat_id),
            send_as=payload.get("sendAs", current.send_as),
            user_adapter=payload.get("userAdapter", current.user_adapter),
        )
        try:
            saved = save_telegram_upload_settings(self.context, candidate)
        except TelegramTransferError as exc:
            # Telegram core validation messages are intentionally user-facing and
            # contain neither secret values nor filesystem paths.
            raise HeadlessTelegramApiError(_validation_message(exc)) from exc
        except Exception as exc:
            raise HeadlessTelegramApiError(
                "Telegram settings could not be saved",
                status=503,
                code="TELEGRAM_SETTINGS_UNAVAILABLE",
            ) from exc
        return {"settings": saved.public_payload(), "botTokenConfigured": self._token_configured()}
