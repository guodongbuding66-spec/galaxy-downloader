from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from headless_transfer_api import HeadlessTransferContext, build_headless_transfer_context
from telegram_transfer import (
    SEND_MODES,
    TelegramTransferError,
    TelegramUploadSettings,
    clear_telegram_bot_token,
    load_telegram_upload_settings,
    save_telegram_upload_settings,
    telegram_bot_token_configured,
    upload_to_telegram,
)

_ALLOWED_SETTINGS_FIELDS = frozenset({"mode", "chatId", "sendAs", "userAdapter"})
_ALLOWED_SECRET_FIELDS = frozenset({"botToken"})
_ALLOWED_UPLOAD_FIELDS = frozenset({"mediaId", "filename", "extension", "caption", "autoChunk"})
_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
_EXTENSION_RE = re.compile(r"^[A-Za-z0-9]{1,12}$")


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


def _clean_media_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _MEDIA_ID_RE.fullmatch(clean):
        raise HeadlessTelegramApiError("invalid media id", code="TELEGRAM_MEDIA_ID_INVALID")
    return clean


def _optional_text(value: object, *, label: str, max_length: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HeadlessTelegramApiError(f"Telegram {label} must be a string")
    if len(value) > max_length:
        raise HeadlessTelegramApiError(f"Telegram {label} is too long")
    return value


def _translate_upload_error(exc: TelegramTransferError) -> HeadlessTelegramApiError:
    detail = _validation_message(exc)
    if detail == "媒体文件不可用":
        return HeadlessTelegramApiError("media file unavailable", status=404, code="TELEGRAM_MEDIA_NOT_FOUND")
    if detail in {
        "请先设置 Telegram Chat ID / @username",
        "请先保存 Telegram Bot Token",
        "未检测到 Galaxy Telegram User Session adapter",
    }:
        return HeadlessTelegramApiError("Telegram upload is not configured", status=409, code="TELEGRAM_NOT_CONFIGURED")
    if detail in {
        "文件为空或超过 4 GB 上限",
        "Bot 模式单文件超过 50 MB，请开启自动分片或使用 User Session adapter",
        "文件需要过多 Telegram 分片",
    }:
        return HeadlessTelegramApiError("Telegram upload exceeds the configured limit", status=409, code="TELEGRAM_UPLOAD_LIMIT")
    return HeadlessTelegramApiError("Telegram upload failed", status=502, code="TELEGRAM_UPLOAD_FAILED")


class HeadlessTelegramApi:
    """Authenticated facade for Telegram settings, secrets and media uploads.

    The Bot Token remains write-only. Headless upload accepts only a Galaxy media
    library id; arbitrary local file and thumbnail paths are intentionally not exposed.
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
            "secretMutationSupported": True,
            "uploadEndpointSupported": True,
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
            raise HeadlessTelegramApiError(_validation_message(exc)) from exc
        except Exception as exc:
            raise HeadlessTelegramApiError(
                "Telegram settings could not be saved",
                status=503,
                code="TELEGRAM_SETTINGS_UNAVAILABLE",
            ) from exc
        return {"settings": saved.public_payload(), "botTokenConfigured": self._token_configured()}

    def save_bot_token(self, payload: object) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HeadlessTelegramApiError("Telegram Bot Token request must be a JSON object")
        unknown = sorted(str(key) for key in payload if key not in _ALLOWED_SECRET_FIELDS)
        if unknown or "botToken" not in payload:
            raise HeadlessTelegramApiError("Telegram Bot Token request contains unsupported fields")
        token = payload.get("botToken")
        if not isinstance(token, str) or not token.strip():
            raise HeadlessTelegramApiError("Telegram Bot Token must be a non-empty string")
        current = self._current()
        try:
            save_telegram_upload_settings(self.context, current, bot_token=token)
        except TelegramTransferError as exc:
            raise HeadlessTelegramApiError(_validation_message(exc)) from exc
        except Exception as exc:
            raise HeadlessTelegramApiError(
                "Telegram Bot Token could not be saved",
                status=503,
                code="TELEGRAM_SECRET_UNAVAILABLE",
            ) from exc
        return {"botTokenConfigured": self._token_configured()}

    def clear_bot_token(self, payload: object) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HeadlessTelegramApiError("Telegram Bot Token clear request must be a JSON object")
        if payload:
            raise HeadlessTelegramApiError("Telegram Bot Token clear request must be empty")
        try:
            clear_telegram_bot_token(self.context)
        except TelegramTransferError as exc:
            raise HeadlessTelegramApiError(
                _validation_message(exc),
                status=503,
                code="TELEGRAM_SECRET_UNAVAILABLE",
            ) from exc
        except Exception as exc:
            raise HeadlessTelegramApiError(
                "Telegram Bot Token could not be cleared",
                status=503,
                code="TELEGRAM_SECRET_UNAVAILABLE",
            ) from exc
        return {"botTokenConfigured": self._token_configured()}

    def upload_media(self, payload: object) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HeadlessTelegramApiError("Telegram upload request must be a JSON object")
        unknown = sorted(str(key) for key in payload if key not in _ALLOWED_UPLOAD_FIELDS)
        if unknown:
            raise HeadlessTelegramApiError("Telegram upload request contains unsupported fields")
        media_id = _clean_media_id(payload.get("mediaId"))
        filename = _optional_text(payload.get("filename"), label="filename", max_length=180)
        extension = _optional_text(payload.get("extension"), label="extension", max_length=12).strip()
        if extension and not _EXTENSION_RE.fullmatch(extension):
            raise HeadlessTelegramApiError("Telegram extension must be alphanumeric")
        caption = _optional_text(payload.get("caption"), label="caption", max_length=1024)
        auto_chunk = payload.get("autoChunk", True)
        if not isinstance(auto_chunk, bool):
            raise HeadlessTelegramApiError("Telegram autoChunk must be a boolean")

        current = self._current()
        try:
            results = upload_to_telegram(
                self.context,
                media_id=media_id,
                filename=filename,
                extension=extension,
                caption=caption,
                auto_chunk=auto_chunk,
            )
        except TelegramTransferError as exc:
            raise _translate_upload_error(exc) from exc
        except Exception as exc:
            raise HeadlessTelegramApiError(
                "Telegram upload failed",
                status=502,
                code="TELEGRAM_UPLOAD_FAILED",
            ) from exc
        return {
            "uploaded": True,
            "mediaId": media_id,
            "parts": len(results),
            "mode": current.mode,
            "sendAs": current.send_as,
            "autoChunk": auto_chunk,
        }
