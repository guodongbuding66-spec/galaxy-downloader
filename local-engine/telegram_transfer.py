from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from PIL import Image, UnidentifiedImageError

from media_library import resolve_media_item_path
from runtime_storage import state_dir as runtime_state_dir

SETTINGS_FILENAME = "telegram-upload.json"
SECRETS_FILENAME = "telegram-upload-secret.json"
BOT_SINGLE_FILE_LIMIT = 50 * 1024 * 1024
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
MAX_THUMBNAIL_BYTES = 200 * 1024
MAX_THUMBNAIL_DIMENSION = 320
MAX_CHUNK_PARTS = 100
CHAT_RE = re.compile(r"^(?:-?\d{1,24}|@[A-Za-z0-9_]{5,64})$")
BOT_TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{20,120}$")
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
        return {
            "mode": self.mode,
            "chatId": self.chat_id,
            "sendAs": self.send_as,
            "userAdapter": self.user_adapter,
        }


def _state_path(engine_module, filename: str) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / filename


def _write_json(path: Path, payload: object, *, secret: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        if secret and os.name != "nt":
            os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", closefd=True) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if secret and os.name != "nt":
            os.chmod(path, 0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _clean_adapter(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "", str(value or ""))[:100]
    if cleaned in {"", ".", ".."}:
        return "galaxy-telegram-user"
    return cleaned


def _validated_settings(settings: TelegramUploadSettings) -> TelegramUploadSettings:
    chat = str(settings.chat_id or "").strip()
    if chat and not CHAT_RE.fullmatch(chat):
        raise TelegramTransferError("Telegram Chat ID / @username 无效")
    mode = str(settings.mode or "bot").strip().lower()
    send_as = str(settings.send_as or "document").strip().lower()
    return TelegramUploadSettings(
        mode=mode if mode in {"bot", "user"} else "bot",
        chat_id=chat,
        send_as=send_as if send_as in SEND_MODES else "document",
        user_adapter=_clean_adapter(settings.user_adapter),
    )


def load_telegram_upload_settings(engine_module) -> TelegramUploadSettings:
    try:
        raw = json.loads(_state_path(engine_module, SETTINGS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return TelegramUploadSettings()
    if not isinstance(raw, dict):
        return TelegramUploadSettings()
    try:
        return _validated_settings(
            TelegramUploadSettings(
                mode=str(raw.get("mode") or "bot"),
                chat_id=str(raw.get("chatId") or ""),
                send_as=str(raw.get("sendAs") or "document"),
                user_adapter=str(raw.get("userAdapter") or "galaxy-telegram-user"),
            )
        )
    except TelegramTransferError:
        return TelegramUploadSettings()


def save_telegram_upload_settings(
    engine_module,
    settings: TelegramUploadSettings,
    *,
    bot_token: object | None = None,
) -> TelegramUploadSettings:
    cleaned = _validated_settings(settings)
    token = "" if bot_token is None else str(bot_token or "").strip()
    if token and not BOT_TOKEN_RE.fullmatch(token):
        raise TelegramTransferError("Bot Token 格式无效")
    _write_json(_state_path(engine_module, SETTINGS_FILENAME), cleaned.public_payload())
    if token:
        _write_json(_state_path(engine_module, SECRETS_FILENAME), {"botToken": token}, secret=True)
    return cleaned


def clear_telegram_bot_token(engine_module) -> None:
    path = _state_path(engine_module, SECRETS_FILENAME)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise TelegramTransferError("无法清除 Telegram Bot Token") from exc


def _bot_token(engine_module) -> str:
    try:
        value = json.loads(_state_path(engine_module, SECRETS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return ""
    token = str(value.get("botToken") or "") if isinstance(value, dict) else ""
    return token if BOT_TOKEN_RE.fullmatch(token) else ""


def telegram_bot_token_configured(engine_module) -> bool:
    return bool(_bot_token(engine_module))


def _safe_request_error(exc: BaseException, token: str) -> str:
    text = str(exc) or exc.__class__.__name__
    if token:
        text = text.replace(token, "<redacted>")
    text = re.sub(r"bot\d{5,15}:[A-Za-z0-9_-]{20,120}", "bot<redacted>", text)
    return text[:1000]


def _galaxy_file(engine_module, *, media_id: object = "", file_path: object = "") -> Path:
    if media_id:
        path = resolve_media_item_path(engine_module, media_id)
        if path is None:
            raise TelegramTransferError("媒体文件不可用")
        return path

    raw = str(file_path or "").strip()
    if not raw:
        raise TelegramTransferError("请选择要上传的 Galaxy 文件")
    try:
        source = Path(raw).expanduser()
        if not source.is_absolute() or source.is_symlink():
            raise TelegramTransferError("只允许上传 Galaxy 下载目录中的普通文件")
        path = source.resolve(strict=True)
        root = Path(engine_module.default_download_dir()).expanduser().resolve(strict=False)
        path.relative_to(root)
    except TelegramTransferError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise TelegramTransferError("只允许上传 Galaxy 下载目录中的文件") from exc
    if not path.is_file():
        raise TelegramTransferError("文件无效")
    return path


def _edited_name(source: Path, filename: object, extension: object) -> str:
    name = " ".join(str(filename or source.stem).split()).strip()[:180] or source.stem[:180]
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", name).strip(" .") or "media"
    ext = str(extension or source.suffix).strip().lower().lstrip(".")
    ext = re.sub(r"[^a-z0-9]", "", ext)[:12] or source.suffix.lower().lstrip(".") or "bin"
    return f"{name}.{ext}"


def _thumbnail(value: object) -> Path | None:
    if not value:
        return None
    try:
        source = Path(str(value)).expanduser()
        if not source.is_absolute() or source.is_symlink():
            raise TelegramTransferError("缩略图必须是普通本地 JPEG 文件")
        path = source.resolve(strict=True)
        size = path.stat().st_size
    except TelegramTransferError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise TelegramTransferError("缩略图不存在") from exc
    if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg"} or size <= 0 or size >= MAX_THUMBNAIL_BYTES:
        raise TelegramTransferError("缩略图必须是小于 200 KB 的 JPEG")
    try:
        with Image.open(path) as image:
            width, height = image.size
            image_format = str(image.format or "").upper()
            if image_format != "JPEG" or width < 1 or height < 1:
                raise TelegramTransferError("缩略图必须是有效 JPEG")
            if width > MAX_THUMBNAIL_DIMENSION or height > MAX_THUMBNAIL_DIMENSION:
                raise TelegramTransferError("缩略图宽高不能超过 320 px")
            image.verify()
    except TelegramTransferError:
        raise
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise TelegramTransferError("缩略图必须是有效 JPEG") from exc
    return path


def _bot_upload_one(
    token: str,
    chat_id: str,
    source: Path,
    *,
    send_as: str,
    filename: str,
    thumbnail: Path | None = None,
    caption: str = "",
) -> dict[str, Any]:
    method = SEND_MODES.get(send_as, "sendDocument")
    field = {"document": "document", "video": "video", "audio": "audio"}.get(send_as, "document")
    url = f"https://api.telegram.org/bot{token}/{method}"
    files: dict[str, tuple[str, Any, str]] = {}
    media_handle = None
    thumb_handle = None
    try:
        media_handle = source.open("rb")
        files[field] = (filename, media_handle, "application/octet-stream")
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
        raise TelegramTransferError(_safe_request_error(exc, token)) from exc
    finally:
        if media_handle is not None:
            media_handle.close()
        if thumb_handle is not None:
            thumb_handle.close()

    try:
        payload = response.json()
    except ValueError as exc:
        raise TelegramTransferError(f"Telegram HTTP {response.status_code} 返回无效 JSON") from exc
    if not isinstance(payload, dict):
        raise TelegramTransferError("Telegram 返回无效响应")
    if response.status_code != 200 or not payload.get("ok"):
        description = str(payload.get("description") or f"Telegram HTTP {response.status_code}")
        raise TelegramTransferError(_safe_request_error(RuntimeError(description), token))
    return payload


def _chunk_file(source: Path, target: Path, *, chunk_bytes: int = BOT_SINGLE_FILE_LIMIT) -> list[Path]:
    if chunk_bytes < 1:
        raise TelegramTransferError("Telegram 分片大小无效")
    size = source.stat().st_size
    total = int(math.ceil(size / chunk_bytes)) if size else 0
    if total < 1 or total > MAX_CHUNK_PARTS:
        raise TelegramTransferError("文件需要过多 Telegram 分片")
    target.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    with source.open("rb") as reader:
        for index in range(1, total + 1):
            part = target / f"{source.name}.part{index:03d}"
            remaining = min(chunk_bytes, size - ((index - 1) * chunk_bytes))
            with part.open("wb") as writer:
                while remaining > 0:
                    block = reader.read(min(1024 * 1024, remaining))
                    if not block:
                        raise TelegramTransferError("读取 Telegram 分片源文件失败")
                    writer.write(block)
                    remaining -= len(block)
            parts.append(part)
    return parts


def _run_user_adapter(
    settings: TelegramUploadSettings,
    source: Path,
    *,
    output_name: str,
    caption: str,
) -> list[dict[str, Any]]:
    adapter = shutil.which(settings.user_adapter)
    if not adapter:
        raise TelegramTransferError("未检测到 Galaxy Telegram User Session adapter")
    request = {
        "protocol": "galaxy-telegram-user-v1",
        "source": str(source),
        "chatId": settings.chat_id,
        "sendAs": settings.send_as,
        "filename": output_name,
        "caption": caption[:1024],
    }
    try:
        completed = subprocess.run(
            [adapter, "--galaxy-telegram-json"],
            input=json.dumps(request, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=7200,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TelegramTransferError(str(exc)[:1000]) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Telegram user adapter failed")[-1600:]
        raise TelegramTransferError(detail)
    return [{"ok": True, "mode": "user", "detail": (completed.stdout or "").strip()[:1000]}]


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
    caption_text = str(caption or "")[:1024]

    if settings.mode == "user":
        return _run_user_adapter(settings, source, output_name=output_name, caption=caption_text)

    token = _bot_token(engine_module)
    if not token:
        raise TelegramTransferError("请先保存 Telegram Bot Token")
    thumb = _thumbnail(thumbnail)
    if size <= BOT_SINGLE_FILE_LIMIT:
        return [
            _bot_upload_one(
                token,
                settings.chat_id,
                source,
                send_as=settings.send_as,
                filename=output_name,
                thumbnail=thumb,
                caption=caption_text,
            )
        ]
    if not auto_chunk:
        raise TelegramTransferError("Bot 模式单文件超过 50 MB，请开启自动分片或使用 User Session adapter")

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="galaxy-telegram-chunks-") as directory:
        parts = _chunk_file(source, Path(directory))
        total = len(parts)
        for index, part in enumerate(parts, 1):
            part_name = f"{output_name}.part{index:03d}-of-{total:03d}"
            part_caption = f"{caption_text[:900]}\nPart {index}/{total}".strip()
            results.append(
                _bot_upload_one(
                    token,
                    settings.chat_id,
                    part,
                    send_as="document",
                    filename=part_name,
                    caption=part_caption,
                )
            )
    return results


def run_telegram_transfer_self_test() -> None:
    assert _edited_name(Path("demo.mp4"), "A:B", "mkv") == "A_B.mkv"
    assert CHAT_RE.fullmatch("@example_user")
    assert CHAT_RE.fullmatch("-100123456789")
    assert BOT_TOKEN_RE.fullmatch("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd")
    assert BOT_SINGLE_FILE_LIMIT == 50 * 1024 * 1024
    assert MAX_THUMBNAIL_BYTES == 200 * 1024
    assert MAX_THUMBNAIL_DIMENSION == 320
