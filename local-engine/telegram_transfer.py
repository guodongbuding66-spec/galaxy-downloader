from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from media_library import resolve_media_item_path
from runtime_storage import state_dir as runtime_state_dir

SETTINGS_FILENAME = "telegram-upload.json"
SECRETS_FILENAME = "telegram-upload-secret.json"
BOT_SINGLE_FILE_LIMIT = 49 * 1024 * 1024
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
CHAT_RE = re.compile(r"^(?:-?\d{1,24}|@[A-Za-z0-9_]{5,64})$")
SEND_MODES = {"document": "sendDocument", "video": "sendVideo", "audio": "sendAudio"}


class TelegramTransferError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramUploadSettings:
    mode: str = "bot"
    chat_id: str = ""
    send_as: str = "document"
    user_adapter: str = "galaxy-telegram-user"

    def public_payload(self) -> dict[str, Any]:
        return {"mode": self.mode, "chatId": self.chat_id, "sendAs": self.send_as, "userAdapter": self.user_adapter}


def _state_path(engine_module, filename: str) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / filename


def _write_json(path: Path, payload: object, *, secret: bool = False) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if secret and os.name != "nt":
        os.chmod(temporary, 0o600)
    temporary.replace(path)
    if secret and os.name != "nt":
        os.chmod(path, 0o600)


def load_telegram_upload_settings(engine_module) -> TelegramUploadSettings:
    try:
        raw = json.loads(_state_path(engine_module, SETTINGS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return TelegramUploadSettings()
    if not isinstance(raw, dict):
        return TelegramUploadSettings()
    mode = str(raw.get("mode") or "bot").lower()
    send_as = str(raw.get("sendAs") or "document").lower()
    chat_id = str(raw.get("chatId") or "").strip()
    return TelegramUploadSettings(
        mode=mode if mode in {"bot", "user"} else "bot",
        chat_id=chat_id if CHAT_RE.fullmatch(chat_id) else "",
        send_as=send_as if send_as in SEND_MODES else "document",
        user_adapter=str(raw.get("userAdapter") or "galaxy-telegram-user")[:100],
    )


def save_telegram_upload_settings(engine_module, settings: TelegramUploadSettings, *, bot_token: object = "") -> TelegramUploadSettings:
    chat = str(settings.chat_id or "").strip()
    if chat and not CHAT_RE.fullmatch(chat):
        raise TelegramTransferError("Telegram Chat ID / @username 无效")
    cleaned = TelegramUploadSettings(
        mode=settings.mode if settings.mode in {"bot", "user"} else "bot",
        chat_id=chat,
        send_as=settings.send_as if settings.send_as in SEND_MODES else "document",
        user_adapter=re.sub(r"[^A-Za-z0-9_.-]", "", settings.user_adapter)[:100] or "galaxy-telegram-user",
    )
    _write_json(_state_path(engine_module, SETTINGS_FILENAME), cleaned.public_payload())
    token = str(bot_token or "").strip()
    if token:
        if not re.fullmatch(r"\d{5,15}:[A-Za-z0-9_-]{20,120}", token):
            raise TelegramTransferError("Bot Token 格式无效")
        _write_json(_state_path(engine_module, SECRETS_FILENAME), {"botToken": token}, secret=True)
    return cleaned


def _bot_token(engine_module) -> str:
    try:
        value = json.loads(_state_path(engine_module, SECRETS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return ""
    token = str(value.get("botToken") or "") if isinstance(value, dict) else ""
    return token if re.fullmatch(r"\d{5,15}:[A-Za-z0-9_-]{20,120}", token) else ""


def _galaxy_file(engine_module, *, media_id: object = "", file_path: object = "") -> Path:
    if media_id:
        path = resolve_media_item_path(engine_module, media_id)
        if path is None:
            raise TelegramTransferError("媒体文件不可用")
        return path
    try:
        path = Path(str(file_path or "")).expanduser().resolve(strict=True)
        root = Path(engine_module.default_download_dir()).resolve(strict=False)
        path.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise TelegramTransferError("只允许上传 Galaxy 下载目录中的文件") from exc
    if not path.is_file() or path.is_symlink():
        raise TelegramTransferError("文件无效")
    return path


def _edited_name(source: Path, filename: object, extension: object) -> str:
    name = " ".join(str(filename or source.stem).split()).strip()[:180] or source.stem[:180]
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", name).strip(" .") or "media"
    ext = str(extension or source.suffix).strip().lower().lstrip(".")
    ext = re.sub(r"[^a-z0-9]", "", ext)[:12] or source.suffix.lower().lstrip(".") or "bin"
    return f"{name}.{ext}"


def _bot_upload_one(token: str, chat_id: str, source: Path, *, send_as: str, filename: str, thumbnail: Path | None = None, caption: str = "") -> dict[str, Any]:
    method = SEND_MODES.get(send_as, "sendDocument")
    field = {"document": "document", "video": "video", "audio": "audio"}.get(send_as, "document")
    url = f"https://api.telegram.org/bot{token}/{method}"
    files: dict[str, tuple[str, Any, str]] = {}
    try:
        media_handle = source.open("rb")
        files[field] = (filename, media_handle, "application/octet-stream")
        thumb_handle = None
        if thumbnail is not None:
            thumb_handle = thumbnail.open("rb")
            files["thumbnail"] = (thumbnail.name[:180], thumb_handle, "image/jpeg")
        response = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files=files,
            timeout=(20, 300),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise TelegramTransferError(str(exc)) from exc
    finally:
        handle = locals().get("media_handle")
        if handle is not None:
            handle.close()
        thumb = locals().get("thumb_handle")
        if thumb is not None:
            thumb.close()
    try:
        payload = response.json()
    except ValueError as exc:
        raise TelegramTransferError(f"Telegram HTTP {response.status_code} 返回无效 JSON") from exc
    if response.status_code != 200 or not payload.get("ok"):
        raise TelegramTransferError(str(payload.get("description") or f"Telegram HTTP {response.status_code}")[:1000])
    return payload


def _thumbnail(value: object) -> Path | None:
    if not value:
        return None
    try:
        path = Path(str(value)).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise TelegramTransferError("缩略图不存在") from exc
    if not path.is_file() or path.is_symlink() or path.suffix.lower() not in {".jpg", ".jpeg"} or path.stat().st_size > 10 * 1024 * 1024:
        raise TelegramTransferError("缩略图必须是小于 10 MB 的 JPEG")
    return path


def _chunk_file(source: Path, target: Path, *, chunk_bytes: int = BOT_SINGLE_FILE_LIMIT) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    with source.open("rb") as reader:
        index = 1
        while True:
            block = reader.read(chunk_bytes)
            if not block:
                break
            part = target / f"{source.name}.part{index:03d}"
            part.write_bytes(block)
            parts.append(part)
            index += 1
            if len(parts) > 100:
                raise TelegramTransferError("文件需要过多 Telegram 分片")
    return parts


def upload_to_telegram(
    engine_module,
    *,
    media_id: object = "",
    file_path: object = "",
    filename: object = "",
    extension: object = "",
    thumbnail: object = "",
    caption: object = "",
    auto_chunk: bool = True,
) -> list[dict[str, Any]]:
    settings = load_telegram_upload_settings(engine_module)
    if not settings.chat_id:
        raise TelegramTransferError("请先设置 Telegram Chat ID / @username")
    source = _galaxy_file(engine_module, media_id=media_id, file_path=file_path)
    size = source.stat().st_size
    if size <= 0 or size > MAX_UPLOAD_BYTES:
        raise TelegramTransferError("文件为空或超过 4 GB 上限")
    output_name = _edited_name(source, filename, extension)

    if settings.mode == "user":
        adapter = shutil.which(settings.user_adapter)
        if not adapter:
            raise TelegramTransferError("未检测到 Galaxy Telegram User Session adapter")
        request = {"protocol": "galaxy-telegram-user-v1", "source": str(source), "chatId": settings.chat_id, "sendAs": settings.send_as, "filename": output_name, "caption": str(caption or "")[:1024]}
        try:
            completed = subprocess.run([adapter, "--galaxy-telegram-json"], input=json.dumps(request), capture_output=True, text=True, timeout=7200, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TelegramTransferError(str(exc)) from exc
        if completed.returncode != 0:
            raise TelegramTransferError((completed.stderr or completed.stdout or "Telegram user adapter failed")[-1600:])
        return [{"ok": True, "mode": "user", "detail": (completed.stdout or "").strip()[:1000]}]

    token = _bot_token(engine_module)
    if not token:
        raise TelegramTransferError("请先保存 Telegram Bot Token")
    thumb = _thumbnail(thumbnail)
    if size <= BOT_SINGLE_FILE_LIMIT:
        return [_bot_upload_one(token, settings.chat_id, source, send_as=settings.send_as, filename=output_name, thumbnail=thumb, caption=str(caption or ""))]
    if not auto_chunk:
        raise TelegramTransferError("Bot 模式单文件超过安全上限，请开启自动分片或使用 User Session adapter")

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="galaxy-telegram-chunks-") as directory:
        parts = _chunk_file(source, Path(directory))
        total = len(parts)
        for index, part in enumerate(parts, 1):
            part_name = f"{output_name}.part{index:03d}-of-{total:03d}"
            results.append(_bot_upload_one(token, settings.chat_id, part, send_as="document", filename=part_name, caption=f"{str(caption or '')[:900]}\nPart {index}/{total}".strip()))
    return results


def run_telegram_transfer_self_test() -> None:
    assert _edited_name(Path("demo.mp4"), "A:B", "mkv") == "A_B.mkv"
    assert CHAT_RE.fullmatch("@example_user")
    assert CHAT_RE.fullmatch("-100123456789")
