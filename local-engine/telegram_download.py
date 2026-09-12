from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlsplit

from telegram_transfer import TelegramTransferError, load_telegram_upload_settings

DOWNLOAD_PROTOCOL = "galaxy-telegram-user-download-v1"
DEFAULT_USER_ADAPTER = "galaxy-telegram-user"
MEDIA_KINDS = frozenset({"image", "video", "document"})
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,64}$")
CHAT_KEY_RE = re.compile(r"^[A-Za-z0-9_:@.\-]{1,120}$")
MAX_MESSAGES = 100
MAX_DOWNLOAD_ITEMS = 100


@dataclass(frozen=True)
class TelegramPublicSource:
    username: str
    post_id: int = 0

    def public_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"username": self.username}
        if self.post_id:
            payload["postId"] = self.post_id
        return payload


def _clean_username(value: object) -> str:
    username = str(value or "").strip().lstrip("@")
    if not USERNAME_RE.fullmatch(username):
        raise TelegramTransferError("Telegram public username 无效")
    return username


def _positive_message_id(value: object, *, optional: bool = False) -> int:
    if optional and value in {None, "", 0, "0"}:
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise TelegramTransferError("Telegram message id 无效") from exc
    if parsed < 1 or parsed > 2_147_483_647:
        raise TelegramTransferError("Telegram message id 无效")
    return parsed


def parse_public_telegram_source(value: object) -> TelegramPublicSource:
    raw = str(value or "").strip()
    if not raw or any(char.isspace() for char in raw):
        raise TelegramTransferError("请输入 Telegram public post / channel")
    if raw.startswith("@"):
        return TelegramPublicSource(_clean_username(raw))

    parsed = urlsplit(raw)
    if parsed.scheme.lower() == "tg" and parsed.netloc.lower() == "resolve":
        query = parse_qs(parsed.query)
        username = _clean_username((query.get("domain") or [""])[0])
        post = _positive_message_id((query.get("post") or [0])[0], optional=True)
        return TelegramPublicSource(username, post)

    if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname not in {
        "t.me",
        "www.t.me",
        "telegram.me",
        "www.telegram.me",
    }:
        raise TelegramTransferError("只支持 Telegram public t.me / telegram.me 链接")

    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[0] == "s":
        parts = parts[1:]
    if not parts or parts[0].lower() in {"c", "joinchat"} or parts[0].startswith("+"):
        raise TelegramTransferError("只支持 Telegram public channel / post")
    username = _clean_username(parts[0])
    post = _positive_message_id(parts[1], optional=True) if len(parts) > 1 else 0
    if len(parts) > 2:
        raise TelegramTransferError("Telegram public link 路径无效")
    return TelegramPublicSource(username, post)


def _bounded_limit(value: object, default: int = 50) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, MAX_MESSAGES))


def _media_kinds(value: object = None) -> list[str]:
    if value is None:
        return ["image", "video", "document"]
    if isinstance(value, str):
        raw: Iterable[object] = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw = value
    else:
        raise TelegramTransferError("Telegram mediaKinds 必须是数组")
    cleaned: list[str] = []
    for item in raw:
        kind = str(item or "").strip().lower()
        if not kind or kind in cleaned:
            continue
        if kind not in MEDIA_KINDS:
            raise TelegramTransferError("Telegram mediaKinds 仅支持 image / video / document")
        cleaned.append(kind)
    if not cleaned:
        raise TelegramTransferError("Telegram mediaKinds 不能为空")
    return cleaned


def _message_ids(value: object) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise TelegramTransferError("Telegram messageIds 必须是数组")
    result: list[int] = []
    for item in value:
        message_id = _positive_message_id(item)
        if message_id not in result:
            result.append(message_id)
        if len(result) > MAX_MESSAGES:
            raise TelegramTransferError("Telegram batch 最多 100 条消息")
    return result


def _clean_chat_key(value: object) -> str:
    chat_key = str(value or "").strip()
    if not CHAT_KEY_RE.fullmatch(chat_key):
        raise TelegramTransferError("Telegram chat key 无效")
    return chat_key


def _adapter(engine_module) -> str:
    settings = load_telegram_upload_settings(engine_module)
    name = str(settings.user_adapter or DEFAULT_USER_ADAPTER).strip() or DEFAULT_USER_ADAPTER
    adapter = shutil.which(name)
    if not adapter:
        raise TelegramTransferError("未检测到 Galaxy Telegram User Session adapter")
    return adapter


def _run_adapter(engine_module, request: dict[str, Any], *, timeout: int = 300) -> dict[str, Any]:
    adapter = _adapter(engine_module)
    try:
        completed = subprocess.run(
            [adapter, "--galaxy-telegram-download-json"],
            input=json.dumps(request, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=max(10, min(int(timeout), 7200)),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TelegramTransferError("Telegram User Session adapter 不可用") from exc
    if completed.returncode != 0:
        raise TelegramTransferError("Telegram User Session adapter 执行失败")
    try:
        payload = json.loads(completed.stdout or "{}")
    except (TypeError, ValueError) as exc:
        raise TelegramTransferError("Telegram User Session adapter 返回无效 JSON") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise TelegramTransferError("Telegram User Session adapter 返回失败")
    return payload


def _safe_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())[:limit]


def _public_message(item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    try:
        message_id = _positive_message_id(item.get("messageId"))
    except TelegramTransferError:
        return None
    media_kind = str(item.get("mediaKind") or "").strip().lower()
    if media_kind and media_kind not in MEDIA_KINDS:
        media_kind = ""
    file_name = Path(str(item.get("fileName") or "")).name[:180]
    try:
        size = max(0, int(item.get("sizeBytes") or 0))
    except (TypeError, ValueError):
        size = 0
    return {
        "messageId": message_id,
        "date": _safe_text(item.get("date"), 64),
        "text": _safe_text(item.get("text"), 800),
        "mediaKind": media_kind,
        "fileName": file_name,
        "sizeBytes": size,
    }


def _messages(payload: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    raw = payload.get("messages")
    if not isinstance(raw, list):
        raise TelegramTransferError("Telegram User Session adapter 缺少 messages")
    result: list[dict[str, Any]] = []
    for item in raw[:limit]:
        rendered = _public_message(item)
        if rendered is not None:
            result.append(rendered)
    return result


def browse_public_telegram(
    engine_module,
    source: object,
    *,
    limit: object = 50,
    before_message_id: object = 0,
    media_kinds: object = None,
) -> dict[str, Any]:
    parsed = parse_public_telegram_source(source)
    bounded = _bounded_limit(limit)
    request = {
        "protocol": DOWNLOAD_PROTOCOL,
        "action": "browse",
        "publicSource": parsed.public_payload(),
        "limit": bounded,
        "beforeMessageId": _positive_message_id(before_message_id, optional=True),
        "mediaKinds": _media_kinds(media_kinds),
    }
    payload = _run_adapter(engine_module, request)
    return {"source": parsed.public_payload(), "messages": _messages(payload, limit=bounded)}


def list_telegram_chats(engine_module, *, query: object = "", limit: object = 50) -> dict[str, Any]:
    bounded = _bounded_limit(limit)
    request = {
        "protocol": DOWNLOAD_PROTOCOL,
        "action": "chats",
        "query": _safe_text(query, 120),
        "limit": bounded,
    }
    payload = _run_adapter(engine_module, request)
    raw = payload.get("chats")
    if not isinstance(raw, list):
        raise TelegramTransferError("Telegram User Session adapter 缺少 chats")
    chats: list[dict[str, Any]] = []
    for item in raw[:bounded]:
        if not isinstance(item, dict):
            continue
        try:
            chat_key = _clean_chat_key(item.get("chatKey"))
        except TelegramTransferError:
            continue
        username = str(item.get("username") or "").strip().lstrip("@")
        if username and not USERNAME_RE.fullmatch(username):
            username = ""
        kind = str(item.get("type") or "").strip().lower()
        if kind not in {"user", "group", "channel"}:
            kind = ""
        chats.append(
            {
                "chatKey": chat_key,
                "title": _safe_text(item.get("title"), 180),
                "username": username,
                "type": kind,
            }
        )
    return {"chats": chats}


def browse_telegram_chat(
    engine_module,
    chat_key: object,
    *,
    limit: object = 50,
    before_message_id: object = 0,
    media_kinds: object = None,
) -> dict[str, Any]:
    clean_key = _clean_chat_key(chat_key)
    bounded = _bounded_limit(limit)
    request = {
        "protocol": DOWNLOAD_PROTOCOL,
        "action": "browse",
        "chatKey": clean_key,
        "limit": bounded,
        "beforeMessageId": _positive_message_id(before_message_id, optional=True),
        "mediaKinds": _media_kinds(media_kinds),
    }
    payload = _run_adapter(engine_module, request)
    return {"chatKey": clean_key, "messages": _messages(payload, limit=bounded)}


def _output_root(engine_module, scope: str) -> Path:
    downloads = Path(engine_module.default_download_dir()).expanduser().resolve(strict=False)
    root = downloads / "Telegram" / scope
    if downloads.exists() and downloads.is_symlink():
        raise TelegramTransferError("Galaxy download root 不能是符号链接")
    if root.exists() and root.is_symlink():
        raise TelegramTransferError("Telegram download scope 不能是符号链接")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve(strict=False)


def _scope_name(*, public_source: TelegramPublicSource | None = None, chat_key: str = "") -> str:
    if public_source is not None:
        return public_source.username.lower()
    digest = hashlib.sha256(chat_key.encode("utf-8")).hexdigest()[:16]
    return f"chat-{digest}"


def _managed_download(root: Path, relative_path: object) -> Path:
    raw = str(relative_path or "").strip().replace("\\", "/")
    candidate_rel = Path(raw)
    if not raw or candidate_rel.is_absolute() or ".." in candidate_rel.parts:
        raise TelegramTransferError("Telegram adapter 返回了越界路径")
    candidate = root / candidate_rel
    current = root
    for part in candidate_rel.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise TelegramTransferError("Telegram adapter 返回了符号链接路径")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise TelegramTransferError("Telegram adapter 返回了无效下载路径") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise TelegramTransferError("Telegram adapter 返回了无效下载文件")
    return resolved


def _download_results(payload: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    raw = payload.get("items")
    if not isinstance(raw, list):
        raise TelegramTransferError("Telegram User Session adapter 缺少 items")
    if len(raw) > MAX_DOWNLOAD_ITEMS:
        raise TelegramTransferError("Telegram adapter 返回文件过多")
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TelegramTransferError("Telegram adapter 返回无效下载项")
        path = _managed_download(root, item.get("relativePath"))
        kind = str(item.get("mediaKind") or "").strip().lower()
        if kind not in MEDIA_KINDS:
            raise TelegramTransferError("Telegram adapter 返回无效媒体类型")
        result.append(
            {
                "messageId": _positive_message_id(item.get("messageId")),
                "mediaKind": kind,
                "fileName": path.name[:180],
                "sizeBytes": max(0, int(path.stat().st_size)),
                "collection": "telegram",
            }
        )
    return result


def _download_request(
    engine_module,
    *,
    public_source: TelegramPublicSource | None = None,
    chat_key: str = "",
    message_ids: object = None,
    limit: object = 20,
    media_kinds: object = None,
) -> dict[str, Any]:
    bounded = _bounded_limit(limit, 20)
    ids = _message_ids(message_ids)
    scope = _scope_name(public_source=public_source, chat_key=chat_key)
    root = _output_root(engine_module, scope)
    request: dict[str, Any] = {
        "protocol": DOWNLOAD_PROTOCOL,
        "action": "download",
        "limit": bounded,
        "messageIds": ids,
        "mediaKinds": _media_kinds(media_kinds),
        "outputRoot": str(root),
    }
    if public_source is not None:
        request["publicSource"] = public_source.public_payload()
    else:
        request["chatKey"] = chat_key
    payload = _run_adapter(engine_module, request, timeout=7200)
    return {
        "items": _download_results(payload, root),
        "requestedMessageIds": ids,
        "scope": scope,
    }


def download_public_telegram(
    engine_module,
    source: object,
    *,
    message_ids: object = None,
    limit: object = 20,
    media_kinds: object = None,
) -> dict[str, Any]:
    parsed = parse_public_telegram_source(source)
    ids = _message_ids(message_ids)
    if parsed.post_id and ids and parsed.post_id not in ids:
        raise TelegramTransferError("Public Post 与 messageIds 不一致")
    if parsed.post_id and not ids:
        ids = [parsed.post_id]
    return _download_request(
        engine_module,
        public_source=parsed,
        message_ids=ids,
        limit=limit,
        media_kinds=media_kinds,
    )


def download_telegram_chat(
    engine_module,
    chat_key: object,
    *,
    message_ids: object = None,
    limit: object = 20,
    media_kinds: object = None,
) -> dict[str, Any]:
    clean_key = _clean_chat_key(chat_key)
    return _download_request(
        engine_module,
        chat_key=clean_key,
        message_ids=message_ids,
        limit=limit,
        media_kinds=media_kinds,
    )


def run_telegram_download_self_test() -> None:
    assert parse_public_telegram_source("https://t.me/example_channel/123").public_payload() == {
        "username": "example_channel",
        "postId": 123,
    }
    assert parse_public_telegram_source("@example_channel").username == "example_channel"
    assert _media_kinds(["video", "image", "video"]) == ["video", "image"]
