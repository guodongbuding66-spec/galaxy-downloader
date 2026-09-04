from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from media_library import resolve_media_item_path
from platform_paths import resolve_platform_paths
from transfer_center import (
    MAGNET_RE,
    P2PReceiveResult,
    P2PSenderSession,
    TorrentResult,
    TransferError,
    download_torrent,
    receive_p2p_file,
    transfer_status,
)

_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
_SESSION_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_WINDOWS_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s\"'<>|]+")
_POSIX_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_:])/(?:home|Users|root|tmp|var|mnt|srv|opt|private)(?:/[^\s\"'<>|,;:]+)+"
)
_MAGNET_DETAIL_RE = re.compile(r"magnet:\?[^\s\"'<>]+", re.IGNORECASE)


class HeadlessTransferApiError(RuntimeError):
    status = 400
    code = "TRANSFER_INVALID_REQUEST"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class HeadlessTransferNotFoundError(HeadlessTransferApiError):
    status = 404
    code = "TRANSFER_NOT_FOUND"


class HeadlessTransferConflictError(HeadlessTransferApiError):
    status = 409
    code = "TRANSFER_CONFLICT"


def _safe_directory(value: Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    if raw.exists() and raw.is_symlink():
        raise HeadlessTransferApiError(f"{label} cannot be a symbolic link")
    resolved = raw.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _clean_media_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _MEDIA_ID_RE.fullmatch(clean):
        raise HeadlessTransferApiError("invalid media id", code="TRANSFER_MEDIA_ID_INVALID")
    return clean


def _clean_session_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _SESSION_ID_RE.fullmatch(clean):
        raise HeadlessTransferApiError("invalid sender session id", code="TRANSFER_SESSION_ID_INVALID")
    return clean


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(parsed, high))


def _safe_detail(value: object, *, roots: Iterable[Path] = ()) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    candidates: set[str] = set()
    for root in (*tuple(roots), Path.home()):
        try:
            resolved = Path(root).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        candidates.add(str(resolved))
        candidates.add(resolved.as_posix())
    for candidate in sorted((item for item in candidates if item), key=len, reverse=True):
        text = text.replace(candidate, "[LOCAL_PATH]")
    text = _WINDOWS_PATH_RE.sub("[LOCAL_PATH]", text)
    text = _POSIX_PATH_RE.sub("[LOCAL_PATH]", text)
    text = _MAGNET_DETAIL_RE.sub("[MAGNET]", text)
    return text[:1200]


def _translate_error(exc: Exception, *, roots: Iterable[Path] = ()) -> HeadlessTransferApiError:
    if isinstance(exc, HeadlessTransferApiError):
        return exc
    detail = _safe_detail(exc, roots=roots)
    lowered = detail.lower()
    if isinstance(exc, TransferError):
        if "不存在" in detail or "not found" in lowered or "不可用" in detail:
            return HeadlessTransferNotFoundError(detail or "transfer source unavailable")
        if "未检测到 aria2c" in detail:
            return HeadlessTransferConflictError(
                "aria2c is not available",
                code="TRANSFER_ARIA2_UNAVAILABLE",
            )
        if "校验失败" in detail or "握手失败" in detail:
            return HeadlessTransferConflictError(
                detail or "transfer verification failed",
                code="TRANSFER_VERIFICATION_FAILED",
            )
        return HeadlessTransferApiError(detail or "transfer operation failed")
    return HeadlessTransferApiError(detail or "transfer operation failed")


@dataclass(frozen=True)
class HeadlessTransferContext:
    program_path: Path
    data_path: Path
    state_path: Path
    downloads_path: Path
    tools_path: Path

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

    def tools_dir(self) -> Path:
        self.tools_path.mkdir(parents=True, exist_ok=True)
        return self.tools_path


def build_headless_transfer_context(
    download_root: Path,
    *,
    program_dir: Path | None = None,
    data_dir: Path | None = None,
    state_dir: Path | None = None,
    tools_dir: Path | None = None,
) -> HeadlessTransferContext:
    program = Path(program_dir or Path(__file__).resolve().parent).expanduser().resolve(strict=False)
    paths = resolve_platform_paths(program_dir=program)
    data = _safe_directory(Path(data_dir or paths.data_dir), label="transfer data directory")
    state = _safe_directory(Path(state_dir or paths.state_dir), label="transfer state directory")
    downloads = _safe_directory(Path(download_root), label="transfer download root")
    tools = Path(tools_dir or paths.tools_dir).expanduser().resolve(strict=False)
    if tools.exists() and tools.is_symlink():
        raise HeadlessTransferApiError("transfer tools directory cannot be a symbolic link")
    return HeadlessTransferContext(program, data, state, downloads, tools)


@dataclass
class _SenderRecord:
    session_id: str
    media_id: str
    file_name: str
    size_bytes: int
    session: P2PSenderSession

    def public_payload(self, *, include_code: bool = False) -> dict[str, Any]:
        if self.session.served:
            state = "served"
        elif self.session.active:
            state = "active"
        else:
            state = "stopped"
        payload = {
            "sessionId": self.session_id,
            "mediaId": self.media_id,
            "fileName": self.file_name,
            "sizeBytes": self.size_bytes,
            "state": state,
            "served": bool(self.session.served),
            "active": bool(self.session.active),
            "ttlSeconds": int(self.session.ttl_seconds),
        }
        if include_code:
            payload["code"] = self.session.code
        return payload


class HeadlessTransferApi:
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
        self._lock = threading.RLock()
        self._senders: dict[str, _SenderRecord] = {}

    @property
    def _roots(self) -> tuple[Path, ...]:
        return (
            self.context.program_path,
            self.context.data_path,
            self.context.state_path,
            self.context.downloads_path,
            self.context.tools_path,
        )

    def status(self) -> dict[str, Any]:
        try:
            raw = transfer_status(self.context)
        except Exception as exc:
            raise _translate_error(exc, roots=self._roots) from exc
        return {
            "torrentReady": bool(raw.get("torrentReady", False)),
            "torrentContinuedSeeding": False,
            "p2pLan": bool(raw.get("p2pLan", True)),
            "p2pCloudRelay": bool(raw.get("p2pCloudRelay", False)),
            "p2pDiscoveryPort": max(0, int(raw.get("p2pDiscoveryPort") or 0)),
            "p2pCodeLength": max(0, int(raw.get("p2pCodeLength") or 0)),
            "p2pMaxFileBytes": max(0, int(raw.get("p2pMaxFileBytes") or 0)),
            "activeSenders": sum(1 for row in self.senders()["senders"] if row["active"]),
        }

    def senders(self) -> dict[str, Any]:
        with self._lock:
            rows = [record.public_payload() for record in self._senders.values()]
        return {"senders": rows}

    def sender_detail(self, session_id: object) -> dict[str, Any]:
        clean = _clean_session_id(session_id)
        with self._lock:
            record = self._senders.get(clean)
        if record is None:
            raise HeadlessTransferNotFoundError("sender session not found")
        return {"sender": record.public_payload()}

    def start_sender(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HeadlessTransferApiError("sender request must be an object")
        media_id = _clean_media_id(payload.get("mediaId"))
        ttl = _bounded_int(payload.get("ttlSeconds"), 600, 60, 3600)
        with self._lock:
            self._prune_senders_locked()
        try:
            source = resolve_media_item_path(self.context, media_id)
            if source is None:
                raise HeadlessTransferNotFoundError("media file unavailable")
            size = max(0, int(source.stat().st_size))
            session = P2PSenderSession(source, ttl_seconds=ttl).start()
        except Exception as exc:
            raise _translate_error(exc, roots=self._roots) from exc
        record = _SenderRecord(
            session_id=uuid.uuid4().hex,
            media_id=media_id,
            file_name=source.name[:240],
            size_bytes=size,
            session=session,
        )
        with self._lock:
            self._senders[record.session_id] = record
        return {"sender": record.public_payload(include_code=True)}

    def stop_sender(self, session_id: object) -> dict[str, Any]:
        clean = _clean_session_id(session_id)
        with self._lock:
            record = self._senders.get(clean)
        if record is None:
            raise HeadlessTransferNotFoundError("sender session not found")
        record.session.stop()
        return {"sender": record.public_payload(), "stopped": True}

    def receive(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HeadlessTransferApiError("receive request must be an object")
        code = str(payload.get("code") or "").strip()
        timeout = _bounded_int(payload.get("timeoutSeconds"), 15, 1, 60)
        try:
            result: P2PReceiveResult = receive_p2p_file(
                self.context,
                code,
                timeout_seconds=timeout,
            )
        except Exception as exc:
            raise _translate_error(exc, roots=self._roots) from exc
        return {
            "received": True,
            "fileName": result.path.name[:240],
            "sizeBytes": max(0, int(result.size_bytes)),
            "sha256": str(result.sha256 or "")[:64],
            "collection": "received",
        }

    def download_magnet(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HeadlessTransferApiError("magnet request must be an object")
        magnet = str(payload.get("magnet") or "").strip()
        if not MAGNET_RE.fullmatch(magnet):
            raise HeadlessTransferApiError("invalid magnet link", code="TRANSFER_MAGNET_INVALID")
        timeout = _bounded_int(payload.get("timeoutSeconds"), 24 * 3600, 60, 48 * 3600)
        try:
            result: TorrentResult = download_torrent(
                self.context,
                magnet,
                timeout_seconds=timeout,
            )
        except Exception as exc:
            raise _translate_error(exc, roots=self._roots) from exc
        return {
            "completed": True,
            "collection": "torrents",
            "message": _safe_detail(result.message, roots=self._roots),
        }

    def shutdown(self) -> None:
        with self._lock:
            records = list(self._senders.values())
            self._senders.clear()
        for record in records:
            try:
                record.session.stop()
            except Exception:
                pass

    def _prune_senders_locked(self) -> None:
        stale = [
            session_id
            for session_id, record in self._senders.items()
            if not record.session.active and not record.session.served
        ]
        for session_id in stale[:-32]:
            self._senders.pop(session_id, None)
        if len(self._senders) >= 64:
            removable = [
                session_id
                for session_id, record in self._senders.items()
                if not record.session.active
            ]
            for session_id in removable[: max(1, len(self._senders) - 63)]:
                self._senders.pop(session_id, None)
        if len(self._senders) >= 64:
            raise HeadlessTransferConflictError(
                "too many sender sessions",
                code="TRANSFER_SENDER_LIMIT",
            )


def run_headless_transfer_api_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    class FakeSender:
        def __init__(self, source, *, ttl_seconds=600, on_status=None):
            self.source = Path(source)
            self.ttl_seconds = ttl_seconds
            self.code = "ABCDEFGH2345"
            self.active = False
            self.served = False

        def start(self):
            self.active = True
            return self

        def stop(self):
            self.active = False

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        downloads = root / "downloads"
        downloads.mkdir()
        media = downloads / "demo.mp4"
        media.write_bytes(b"demo")
        context = HeadlessTransferContext(
            program_path=root,
            data_path=root / "data",
            state_path=root / "state",
            downloads_path=downloads,
            tools_path=root / "tools",
        )
        api = HeadlessTransferApi(downloads, context=context)

        with patch(
            "headless_transfer_api.transfer_status",
            return_value={
                "torrentReady": True,
                "p2pLan": True,
                "p2pCloudRelay": False,
                "p2pDiscoveryPort": 38977,
                "p2pCodeLength": 12,
                "p2pMaxFileBytes": 123,
                "p2pBindAddress": "192.168.1.7",
            },
        ):
            status = api.status()
            assert status["torrentReady"] is True
            assert "p2pBindAddress" not in status

        with patch("headless_transfer_api.resolve_media_item_path", return_value=media), patch(
            "headless_transfer_api.P2PSenderSession",
            FakeSender,
        ):
            started = api.start_sender({"mediaId": "a" * 32, "ttlSeconds": 120})
            sender = started["sender"]
            assert sender["code"] == "ABCDEFGH2345"
            assert "path" not in sender
            session_id = sender["sessionId"]
            listed = api.senders()["senders"][0]
            assert "code" not in listed
            assert api.stop_sender(session_id)["stopped"] is True

        receive_result = P2PReceiveResult(root / "private" / "received.mp4", 4, "b" * 64)
        with patch("headless_transfer_api.receive_p2p_file", return_value=receive_result):
            received = api.receive({"code": "ABCDEFGH2345"})
            assert received["fileName"] == "received.mp4"
            assert str(root) not in str(received)

        torrent_result = TorrentResult(root / "private" / "torrents", "done")
        with patch("headless_transfer_api.download_torrent", return_value=torrent_result):
            result = api.download_magnet(
                {"magnet": "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"}
            )
            assert result["collection"] == "torrents"
            assert str(root) not in str(result)

        try:
            api.download_magnet({"magnet": "https://example.com/file.torrent"})
        except HeadlessTransferApiError as exc:
            assert exc.code == "TRANSFER_MAGNET_INVALID"
        else:
            raise AssertionError("unsafe magnet source was accepted")

        with patch(
            "headless_transfer_api.receive_p2p_file",
            side_effect=TransferError(f"failed at {root / 'secret'}"),
        ):
            try:
                api.receive({"code": "ABCDEFGH2345"})
            except HeadlessTransferApiError as exc:
                assert str(root) not in str(exc)
                assert "[LOCAL_PATH]" in str(exc)
            else:
                raise AssertionError("path-leaking transfer error was not redacted")

        api.shutdown()


if __name__ == "__main__":
    run_headless_transfer_api_self_test()
    print("Headless transfer API self-test passed")
