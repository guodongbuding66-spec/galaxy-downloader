from __future__ import annotations

"""Galaxy transfer compatibility facade with controllable aria2 sessions.

The pre-V1.8 transfer implementation remains intact in ``transfer_center_legacy``.
This facade preserves every existing symbol and replaces only the aria2/Torrent
execution path with the lifecycle-aware implementation in ``aria2_transfer``.
"""

from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlparse

import aria2_recovery
import transfer_center_legacy as _legacy
from aria2_file_selection import (
    bind_selected_files,
    install_aria2_file_selection,
    normalize_selected_files,
    selected_files_for,
)
from aria2_source_policy import Aria2Source, Aria2SourceError, require_torrent_source
from aria2_transfer import (
    Aria2TransferOptions,
    Aria2TransferSession,
    Aria2TransferSnapshot,
    run_aria2_transfer_self_test,
)
from bandwidth_policy import load_bandwidth_preference
from torrent_metadata_acquisition import (
    AcquiredTorrentMetadata,
    TorrentMetadataAcquisitionError,
    acquire_torrent_metadata,
)
from transfer_preferences import load_aria2_connections_preference

install_aria2_file_selection()

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


def _validated_torrent_source(engine_module, source: object) -> Aria2Source:
    """Classify Torrent input and apply Galaxy's public-URL boundary to remote torrents."""

    try:
        classified = require_torrent_source(source)
    except Aria2SourceError as exc:
        raise TransferError(str(exc)) from exc
    if classified.kind != "torrent_url":
        return classified

    normalized = _validated_http_source(engine_module, classified.source)
    try:
        validated = require_torrent_source(normalized)
    except Aria2SourceError as exc:
        raise TransferError(str(exc)) from exc
    if validated.kind != "torrent_url":
        raise TransferError("Torrent URL 必须是通过公网地址校验的 HTTPS .torrent 地址")
    return validated


def preview_torrent_metadata(engine_module, source: object) -> AcquiredTorrentMetadata:
    """Acquire a safe local torrent and return its bounded file metadata.

    Local torrents are parsed directly. HTTPS torrents are fetched by Galaxy with
    per-redirect public URL validation. Magnet links use aria2 metadata-only mode.
    In every case the caller receives a local ``.torrent`` path that can later be
    passed to ``start_torrent_transfer`` without repeating remote redirects.
    """

    classified = _validated_torrent_source(engine_module, source)
    executable: Path | None = None
    if classified.kind == "magnet":
        resolved = find_aria2c(engine_module)
        if resolved is None:
            raise TransferError("未检测到 aria2c；读取 Magnet 文件列表需要 aria2c。")
        executable = Path(resolved)
    try:
        return acquire_torrent_metadata(
            engine_module,
            classified.source,
            executable=executable,
        )
    except TorrentMetadataAcquisitionError as exc:
        raise TransferError(str(exc)) from exc


def start_torrent_transfer(
    engine_module,
    source: object,
    *,
    selected_files: object = (),
    on_update: Callable[[Aria2TransferSnapshot], None] | None = None,
    max_attempts: int = 3,
) -> Aria2TransferSession:
    """Create a non-blocking, validated Torrent/Magnet transfer session.

    ``selected_files`` contains aria2's one-based Torrent file indexes. An empty
    selection means the normal aria2 behavior: download every file. HTTPS torrent
    URLs are first fetched through Galaxy's redirect-aware public URL boundary and
    converted to a verified local torrent, so aria2 never follows an unvalidated
    HTTP redirect for the metadata source.
    """

    classified = _validated_torrent_source(engine_module, source)
    selected = normalize_selected_files(selected_files)
    executable = find_aria2c(engine_module)
    if executable is None:
        raise TransferError("未检测到 aria2c；Torrent/Magnet 功能需要 aria2c。请先安装或配置 aria2c 后重试。")

    if classified.kind == "torrent_url":
        try:
            acquired = acquire_torrent_metadata(engine_module, classified.source)
        except TorrentMetadataAcquisitionError as exc:
            raise TransferError(str(exc)) from exc
        classified = Aria2Source(str(acquired.torrent_path), "torrent_file")

    destination = _managed_download_dir(engine_module, "torrents")
    connections = load_aria2_connections_preference(engine_module)
    options = Aria2TransferOptions(
        source=classified.source,
        destination=destination,
        connections=connections,
        seed_time_minutes=0,
        max_attempts=max_attempts,
    )
    bind_selected_files(options, selected)
    return aria2_recovery.create_recoverable_aria2_session(
        engine_module,
        Path(executable),
        options,
        source_kind=classified.kind,
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
    connections = load_aria2_connections_preference(engine_module)
    return Aria2TransferSession(
        Path(executable),
        Aria2TransferOptions(
            source=normalized,
            destination=destination,
            file_name=file_name,
            connections=connections,
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
            "aria2RestartRecovery": True,
            "aria2StrictTorrentSources": True,
            "aria2TorrentFileSelection": True,
            "aria2LocalTorrentMetadata": True,
            "aria2RemoteTorrentMetadata": True,
            "aria2MagnetMetadataOnly": True,
            "aria2RedirectValidatedTorrentFetch": True,
            "aria2Connections": load_aria2_connections_preference(engine_module),
            "aria2MaxConnections": 16,
            "aria2BandwidthLimit": True,
            "bandwidthLimitKbps": load_bandwidth_preference(engine_module),
            "aria2FragmentManifestExternalDownloader": False,
        }
    )
    return payload


def run_transfer_center_self_test() -> None:
    _legacy.run_transfer_center_self_test()
    run_aria2_transfer_self_test()
    assert callable(start_torrent_transfer)
    assert callable(start_aria2_http_transfer)
    assert callable(preview_torrent_metadata)
    assert callable(download_torrent)
    assert normalize_selected_files((3, 1, 2, 2)) == (1, 2, 3)

    probe = Aria2TransferOptions(source="https://example.com/demo.torrent", destination=Path("downloads"))
    bind_selected_files(probe, (2, 4))
    assert selected_files_for(probe) == (2, 4)

    class _BoundaryEngine:
        calls: list[str] = []

        @staticmethod
        def _validated_source_url(value: str) -> str:
            _BoundaryEngine.calls.append(value)
            host = (urlparse(value).hostname or "").lower()
            blocked = (
                host == "localhost"
                or host == "127.0.0.1"
                or host.startswith("10.")
                or host.startswith("192.168.")
                or host.startswith("169.254.")
                or host == "172.16.0.1"
            )
            if blocked:
                raise ValueError("仅允许公网 HTTP(S) 下载地址")
            return value

    public = _validated_torrent_source(_BoundaryEngine, "https://downloads.example.com/demo.torrent")
    assert public.kind == "torrent_url"
    assert public.source == "https://downloads.example.com/demo.torrent"
    assert _BoundaryEngine.calls == ["https://downloads.example.com/demo.torrent"]

    for private_url in (
        "https://localhost/demo.torrent",
        "https://127.0.0.1/demo.torrent",
        "https://10.0.0.1/demo.torrent",
        "https://192.168.1.10/demo.torrent",
        "https://172.16.0.1/demo.torrent",
        "https://169.254.169.254/latest.torrent",
    ):
        try:
            _validated_torrent_source(_BoundaryEngine, private_url)
        except TransferError:
            pass
        else:
            raise AssertionError(f"private torrent URL escaped engine URL boundary: {private_url}")

    before = len(_BoundaryEngine.calls)
    valid_hex = "0123456789abcdef0123456789abcdef01234567"
    magnet = _validated_torrent_source(_BoundaryEngine, f"magnet:?xt=urn:btih:{valid_hex}")
    assert magnet.kind == "magnet"
    assert len(_BoundaryEngine.calls) == before
