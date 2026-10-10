from __future__ import annotations

"""Galaxy transfer compatibility facade with controllable aria2 sessions.

The pre-V1.8 transfer implementation remains intact in ``transfer_center_legacy``.
This facade preserves every existing symbol and replaces only the aria2/Torrent
execution path with the lifecycle-aware implementation in ``aria2_transfer``.
"""

from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlparse

import transfer_center_legacy as _legacy
from aria2_transfer import (
    Aria2TransferOptions,
    Aria2TransferSession,
    Aria2TransferSnapshot,
    run_aria2_transfer_self_test,
)

# Re-export all existing public/private helper names so older modules keep their
# exact import contract while the new aria2 layer is introduced incrementally.
for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals().setdefault(_name, getattr(_legacy, _name))


def _validated_http_source(engine_module, source: object) -> str:
    text = str(source or "").strip()
    validator = getattr(engine_module, "_validated_source_url", None)
    if callable(validator):
        try:
            return str(validator(text))
        except Exception as exc:  # noqa: BLE001
            raise TransferError(str(exc)) from exc
    try:
        parsed = urlparse(text)
    except ValueError as exc:
        raise TransferError("请输入有效的公网 HTTP(S) 下载地址") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise TransferError("请输入有效的公网 HTTP(S) 下载地址")
    return text


def start_torrent_transfer(
    engine_module,
    source: object,
    *,
    on_update: Callable[[Aria2TransferSnapshot], None] | None = None,
    max_attempts: int = 3,
) -> Aria2TransferSession:
    """Create a non-blocking Torrent/Magnet transfer session.

    The returned object exposes ``pause()``, ``resume()``, ``retry()``,
    ``cancel()``, ``snapshot()`` and ``set_listener()``. Partial files are kept
    on pause so aria2 can continue them on the next process run.
    """

    executable = find_aria2c(engine_module)
    if executable is None:
        raise TransferError("未检测到 aria2c；Torrent/Magnet 功能需要 aria2c")
    normalized = _torrent_source(source)
    destination = _managed_download_dir(engine_module, "torrents")
    return Aria2TransferSession(
        Path(executable),
        Aria2TransferOptions(
            source=normalized,
            destination=destination,
            connections=16,
            seed_time_minutes=0,
            max_attempts=max_attempts,
        ),
        on_update=on_update,
    )


def start_aria2_http_transfer(
    engine_module,
    source_url: object,
    *,
    file_name: str = "",
    sha256: str = "",
    headers: Iterable[object] = (),
    on_update: Callable[[Aria2TransferSnapshot], None] | None = None,
    max_attempts: int = 3,
) -> Aria2TransferSession:
    """Create a resumable aria2 HTTP(S) transfer using Galaxy's URL boundary."""

    executable = find_aria2c(engine_module)
    if executable is None:
        raise TransferError("未检测到 aria2c；高速 HTTP 下载需要 aria2c")
    normalized = _validated_http_source(engine_module, source_url)
    destination = _managed_download_dir(engine_module, "aria2")
    return Aria2TransferSession(
        Path(executable),
        Aria2TransferOptions(
            source=normalized,
            destination=destination,
            file_name=file_name,
            connections=16,
            sha256=sha256,
            headers=tuple(headers),
            max_attempts=max_attempts,
        ),
        on_update=on_update,
    )


def download_torrent(engine_module, source: object, *, timeout_seconds: int = 24 * 3600) -> TorrentResult:
    """Compatibility wrapper for callers that still expect a blocking download."""

    try:
        timeout = max(60, min(int(timeout_seconds), 48 * 3600))
    except (TypeError, ValueError) as exc:
        raise TransferError("Torrent timeout 无效") from exc

    session = start_torrent_transfer(engine_module, source, max_attempts=1)
    session.start()
    snapshot = session.wait(timeout=float(timeout))
    if snapshot.state not in {"completed", "failed", "cancelled"}:
        session.cancel()
        session.join(timeout=3)
        raise TransferError("Torrent 下载超时")
    if snapshot.state != "completed":
        raise TransferError(snapshot.error or f"Torrent 下载未完成：{snapshot.state}")
    return TorrentResult(snapshot.destination, "Torrent/Magnet 下载完成；默认不继续做种")


def transfer_status(engine_module) -> dict[str, object]:
    payload = dict(_legacy.transfer_status(engine_module))
    payload.update(
        {
            "aria2Lifecycle": True,
            "aria2Progress": True,
            "aria2PauseResume": True,
            "aria2Retry": True,
            "aria2MaxConnections": 16,
            "aria2FragmentManifestExternalDownloader": False,
        }
    )
    return payload


def run_transfer_center_self_test() -> None:
    _legacy.run_transfer_center_self_test()
    run_aria2_transfer_self_test()
    assert callable(start_torrent_transfer)
    assert callable(start_aria2_http_transfer)
    assert callable(download_torrent)
