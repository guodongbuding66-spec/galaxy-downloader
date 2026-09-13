from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from headless_transfer_api import HeadlessTransferContext, build_headless_transfer_context
from telegram_download import (
    browse_public_telegram,
    browse_telegram_chat,
    download_public_telegram,
    download_telegram_chat,
    list_telegram_chats,
)
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
_ALLOWED_PUBLIC_BROWSE_FIELDS = frozenset({"source", "limit", "beforeMessageId", "mediaKinds"})
_ALLOWED_CHAT_LIST_FIELDS = frozenset({"query", "limit"})
_ALLOWED_CHAT_BROWSE_FIELDS = frozenset({"chatKey", "limit", "beforeMessageId", "mediaKinds"})
_ALLOWED_PUBLIC_DOWNLOAD_FIELDS = frozenset({"source", "messageIds", "limit", "mediaKinds"})
_ALLOWED_CHAT_DOWNLOAD_FIELDS = frozenset({"chatKey", "messageIds", "limit", "mediaKinds"})
_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
_EXTENSION_RE = re.compile(r"^[A-Za-z0-9]{1,12}$")
_DOWNLOAD_MAX_ITEMS = 100


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


def _request_object(payload: object, allowed: frozenset[str], *, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HeadlessTelegramApiError(f"Telegram {label} request must be a JSON object")
    unknown = sorted(str(key) for key in payload if key not in allowed)
    if unknown:
        raise HeadlessTelegramApiError(f"Telegram {label} request contains unsupported fields")
    return payload


def _required_text(payload: dict[str, Any], key: str, *, label: str, max_length: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HeadlessTelegramApiError(f"Telegram {label} must be a non-empty string")
    if len(value) > max_length:
        raise HeadlessTelegramApiError(f"Telegram {label} is too long")
    return value.strip()


def _bounded_integer(value: object, *, label: str, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise HeadlessTelegramApiError(f"Telegram {label} must be an integer")
    if value < minimum or value > maximum:
        raise HeadlessTelegramApiError(f"Telegram {label} is out of range")
    return value


def _media_kinds_payload(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise HeadlessTelegramApiError("Telegram mediaKinds must be a non-empty array")
    if len(value) > 3 or any(not isinstance(item, str) for item in value):
        raise HeadlessTelegramApiError("Telegram mediaKinds is invalid")
    cleaned: list[str] = []
    for item in value:
        kind = item.strip().lower()
        if kind not in {"image", "video", "document"}:
            raise HeadlessTelegramApiError("Telegram mediaKinds is invalid")
        if kind not in cleaned:
            cleaned.append(kind)
    return cleaned


def _message_ids_payload(value: object) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise HeadlessTelegramApiError("Telegram messageIds must be an array")
    if len(value) > _DOWNLOAD_MAX_ITEMS:
        raise HeadlessTelegramApiError("Telegram messageIds exceeds the batch limit")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1 or item > 2_147_483_647:
            raise HeadlessTelegramApiError("Telegram messageIds contains an invalid id")
        if item not in result:
            result.append(item)
    return result


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


def _translate_download_error(exc: TelegramTransferError) -> HeadlessTelegramApiError:
    detail = _validation_message(exc)
    if detail == "未检测到 Galaxy Telegram User Session adapter":
        return HeadlessTelegramApiError(
            "Telegram download is not configured",
            status=409,
            code="TELEGRAM_DOWNLOAD_NOT_CONFIGURED",
        )
    validation_markers = (
        "请输入 Telegram",
        "只支持 Telegram",
        "Telegram public username",
        "Telegram public link",
        "Telegram message id",
        "Telegram mediaKinds",
        "Telegram batch",
        "Telegram chat key",
        "Public Post",
    )
    if any(detail.startswith(marker) for marker in validation_markers):
        return HeadlessTelegramApiError(
            "invalid Telegram download request",
            status=400,
            code="TELEGRAM_DOWNLOAD_INVALID_REQUEST",
        )
    return HeadlessTelegramApiError(
        "Telegram download failed",
        status=502,
        code="TELEGRAM_DOWNLOAD_FAILED",
    )


class HeadlessTelegramApi:
    """Authenticated facade for bounded Telegram settings, transfer and download operations."""

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
            "downloadEndpointSupported": True,
            "chatBrowserSupported": True,
            "downloadMaxItems": _DOWNLOAD_MAX_ITEMS,
            "downloadMediaKinds": ["image", "video", "document"],
            "botTokenConfigured": self._token_configured(),
            "modes": ["bot", "user"],
            "sendAsModes": list(SEND_MODES),
            "settings": settings.public_payload(),
        }

    def settings(self) -> dict[str, Any]:
        current = self._current()
        return {"settings": current.public_payload(), "botTokenConfigured": self._token_configured()}

    def save_settings(self, payload: object) -> dict[str, Any]:
        request = _request_object(payload, _ALLOWED_SETTINGS_FIELDS, label="settings")
        current = self._current()
        candidate = TelegramUploadSettings(
            mode=request.get("mode", current.mode),
            chat_id=request.get("chatId", current.chat_id),
            send_as=request.get("sendAs", current.send_as),
            user_adapter=request.get("userAdapter", current.user_adapter),
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
        request = _request_object(payload, _ALLOWED_SECRET_FIELDS, label="Bot Token")
        if "botToken" not in request:
            raise HeadlessTelegramApiError("Telegram Bot Token request contains unsupported fields")
        token = request.get("botToken")
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
        request = _request_object(payload, frozenset(), label="Bot Token clear")
        if request:
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
        request = _request_object(payload, _ALLOWED_UPLOAD_FIELDS, label="upload")
        media_id = _clean_media_id(request.get("mediaId"))
        filename = _optional_text(request.get("filename"), label="filename", max_length=180)
        extension = _optional_text(request.get("extension"), label="extension", max_length=12).strip()
        if extension and not _EXTENSION_RE.fullmatch(extension):
            raise HeadlessTelegramApiError("Telegram extension must be alphanumeric")
        caption = _optional_text(request.get("caption"), label="caption", max_length=1024)
        auto_chunk = request.get("autoChunk", True)
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

    def browse_public(self, payload: object) -> dict[str, Any]:
        request = _request_object(payload, _ALLOWED_PUBLIC_BROWSE_FIELDS, label="public browse")
        source = _required_text(request, "source", label="source", max_length=500)
        limit = _bounded_integer(request.get("limit"), label="limit", default=50, minimum=1, maximum=100)
        before = _bounded_integer(
            request.get("beforeMessageId"), label="beforeMessageId", default=0, minimum=0, maximum=2_147_483_647
        )
        kinds = _media_kinds_payload(request.get("mediaKinds"))
        try:
            return browse_public_telegram(
                self.context,
                source,
                limit=limit,
                before_message_id=before,
                media_kinds=kinds,
            )
        except TelegramTransferError as exc:
            raise _translate_download_error(exc) from exc
        except Exception as exc:
            raise HeadlessTelegramApiError("Telegram download failed", status=502, code="TELEGRAM_DOWNLOAD_FAILED") from exc

    def list_chats(self, payload: object) -> dict[str, Any]:
        request = _request_object(payload, _ALLOWED_CHAT_LIST_FIELDS, label="chat list")
        query = _optional_text(request.get("query"), label="query", max_length=120)
        limit = _bounded_integer(request.get("limit"), label="limit", default=50, minimum=1, maximum=100)
        try:
            return list_telegram_chats(self.context, query=query, limit=limit)
        except TelegramTransferError as exc:
            raise _translate_download_error(exc) from exc
        except Exception as exc:
            raise HeadlessTelegramApiError("Telegram download failed", status=502, code="TELEGRAM_DOWNLOAD_FAILED") from exc

    def browse_chat(self, payload: object) -> dict[str, Any]:
        request = _request_object(payload, _ALLOWED_CHAT_BROWSE_FIELDS, label="chat browse")
        chat_key = _required_text(request, "chatKey", label="chatKey", max_length=120)
        limit = _bounded_integer(request.get("limit"), label="limit", default=50, minimum=1, maximum=100)
        before = _bounded_integer(
            request.get("beforeMessageId"), label="beforeMessageId", default=0, minimum=0, maximum=2_147_483_647
        )
        kinds = _media_kinds_payload(request.get("mediaKinds"))
        try:
            return browse_telegram_chat(
                self.context,
                chat_key,
                limit=limit,
                before_message_id=before,
                media_kinds=kinds,
            )
        except TelegramTransferError as exc:
            raise _translate_download_error(exc) from exc
        except Exception as exc:
            raise HeadlessTelegramApiError("Telegram download failed", status=502, code="TELEGRAM_DOWNLOAD_FAILED") from exc

    def download_public(self, payload: object) -> dict[str, Any]:
        request = _request_object(payload, _ALLOWED_PUBLIC_DOWNLOAD_FIELDS, label="public download")
        source = _required_text(request, "source", label="source", max_length=500)
        ids = _message_ids_payload(request.get("messageIds"))
        limit = _bounded_integer(request.get("limit"), label="limit", default=20, minimum=1, maximum=100)
        kinds = _media_kinds_payload(request.get("mediaKinds"))
        try:
            return download_public_telegram(
                self.context,
                source,
                message_ids=ids,
                limit=limit,
                media_kinds=kinds,
            )
        except TelegramTransferError as exc:
            raise _translate_download_error(exc) from exc
        except Exception as exc:
            raise HeadlessTelegramApiError("Telegram download failed", status=502, code="TELEGRAM_DOWNLOAD_FAILED") from exc

    def download_chat(self, payload: object) -> dict[str, Any]:
        request = _request_object(payload, _ALLOWED_CHAT_DOWNLOAD_FIELDS, label="chat download")
        chat_key = _required_text(request, "chatKey", label="chatKey", max_length=120)
        ids = _message_ids_payload(request.get("messageIds"))
        limit = _bounded_integer(request.get("limit"), label="limit", default=20, minimum=1, maximum=100)
        kinds = _media_kinds_payload(request.get("mediaKinds"))
        try:
            return download_telegram_chat(
                self.context,
                chat_key,
                message_ids=ids,
                limit=limit,
                media_kinds=kinds,
            )
        except TelegramTransferError as exc:
            raise _translate_download_error(exc) from exc
        except Exception as exc:
            raise HeadlessTelegramApiError("Telegram download failed", status=502, code="TELEGRAM_DOWNLOAD_FAILED") from exc
