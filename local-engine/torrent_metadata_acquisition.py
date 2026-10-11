from __future__ import annotations

"""Safe metadata acquisition for local, HTTPS and Magnet Torrent sources.

All non-local sources are converted into a verified local ``.torrent`` file before
selective download UI or aria2 payload download begins. HTTPS redirects are
followed manually and each hop is re-validated through Galaxy's public URL
boundary. Magnet metadata is obtained with aria2's metadata-only mode, so payload
files are not downloaded during preview.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

from aria2_source_policy import Aria2SourceError, TORRENT_FILE_MAX_BYTES, require_torrent_source
from torrent_metadata import TorrentMetadata, TorrentMetadataError, parse_torrent_bytes, read_local_torrent_metadata

MAX_REDIRECTS = 5
HTTP_CONNECT_TIMEOUT = 5.0
HTTP_READ_TIMEOUT = 15.0
MAGNET_METADATA_TIMEOUT = 120.0


class TorrentMetadataAcquisitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class AcquiredTorrentMetadata:
    original_source: str
    original_kind: str
    torrent_path: Path
    metadata: TorrentMetadata


def _state_root(engine_module) -> Path:
    state_dir = getattr(engine_module, "state_dir", None)
    if callable(state_dir):
        try:
            root = Path(state_dir()).expanduser().resolve(strict=False)
            root.mkdir(parents=True, exist_ok=True)
            return root
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
    app_dir = getattr(engine_module, "app_dir", None)
    if not callable(app_dir):
        raise TorrentMetadataAcquisitionError("无法确定 Galaxy 状态目录")
    try:
        root = Path(app_dir()).expanduser().resolve(strict=False) / "state"
        root.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise TorrentMetadataAcquisitionError("无法创建 Galaxy Torrent 元数据目录") from exc
    return root


def _cache_dir(engine_module) -> Path:
    target = _state_root(engine_module) / "torrent-metadata"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _cache_bytes(engine_module, data: bytes) -> tuple[Path, TorrentMetadata]:
    try:
        metadata = parse_torrent_bytes(data)
    except TorrentMetadataError as exc:
        raise TorrentMetadataAcquisitionError(str(exc)) from exc
    digest = hashlib.sha256(data).hexdigest()
    target = _cache_dir(engine_module) / f"{digest}.torrent"
    if target.exists():
        try:
            if target.is_symlink():
                raise TorrentMetadataAcquisitionError("Torrent 元数据缓存不能是符号链接")
            existing = target.read_bytes()
        except OSError as exc:
            raise TorrentMetadataAcquisitionError("无法读取 Torrent 元数据缓存") from exc
        if existing == data:
            return target, metadata
    temp = target.with_suffix(f".tmp-{os.getpid()}")
    try:
        with temp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, target)
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise TorrentMetadataAcquisitionError("无法写入 Torrent 元数据缓存") from exc
    return target, metadata


def _validated_https_url(engine_module, value: object) -> str:
    text = str(value or "").strip()
    validator = getattr(engine_module, "_validated_source_url", None)
    if not callable(validator):
        raise TorrentMetadataAcquisitionError("缺少公网 URL 校验器，无法安全获取远程 Torrent 元数据")
    try:
        normalized = str(validator(text)).strip()
        parsed = urlsplit(normalized)
    except Exception as exc:  # noqa: BLE001 - fail closed for external input
        raise TorrentMetadataAcquisitionError(str(exc) or "远程 Torrent URL 校验失败") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise TorrentMetadataAcquisitionError("远程 Torrent 元数据仅允许公网 HTTPS URL")
    return normalized


def _read_response_body(response) -> bytes:
    raw_length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
    if raw_length:
        try:
            if int(raw_length) > TORRENT_FILE_MAX_BYTES:
                raise TorrentMetadataAcquisitionError("远程 Torrent 文件超过 10 MB")
        except ValueError:
            pass
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > TORRENT_FILE_MAX_BYTES:
            raise TorrentMetadataAcquisitionError("远程 Torrent 文件超过 10 MB")
        chunks.append(bytes(chunk))
    data = b"".join(chunks)
    if not data:
        raise TorrentMetadataAcquisitionError("远程 Torrent 文件为空")
    return data


def _default_request_get() -> tuple[Callable[..., object], tuple[type[BaseException], ...]]:
    """Load requests only when an HTTPS metadata fetch is actually requested.

    Core transfer-contract tests intentionally import Galaxy without installing
    optional/runtime dependencies. Keeping this import lazy preserves that
    lightweight boundary while production environments still use the requests
    dependency declared in requirements.txt.
    """
    try:
        import requests  # type: ignore
    except ImportError as exc:
        raise TorrentMetadataAcquisitionError("缺少 requests 依赖，无法获取远程 Torrent 元数据") from exc
    return requests.get, (requests.RequestException,)


def fetch_https_torrent_bytes(
    engine_module,
    source: object,
    *,
    request_get: Callable[..., object] | None = None,
) -> bytes:
    """Fetch a remote torrent with per-hop public-URL validation and size bounds."""

    try:
        classified = require_torrent_source(source)
    except Aria2SourceError as exc:
        raise TorrentMetadataAcquisitionError(str(exc)) from exc
    if classified.kind != "torrent_url":
        raise TorrentMetadataAcquisitionError("该来源不是 HTTPS .torrent 地址")

    request_errors: tuple[type[BaseException], ...] = ()
    if request_get is None:
        request_get, request_errors = _default_request_get()

    current = _validated_https_url(engine_module, classified.source)
    for redirect_count in range(MAX_REDIRECTS + 1):
        response = None
        try:
            response = request_get(
                current,
                allow_redirects=False,
                stream=True,
                timeout=(HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT),
                headers={"Accept": "application/x-bittorrent,application/octet-stream;q=0.9,*/*;q=0.1"},
            )
            status = int(getattr(response, "status_code", 0) or 0)
            if status in {301, 302, 303, 307, 308}:
                location = str(getattr(response, "headers", {}).get("Location") or "").strip()
                if not location:
                    raise TorrentMetadataAcquisitionError("远程 Torrent 重定向缺少 Location")
                if redirect_count >= MAX_REDIRECTS:
                    raise TorrentMetadataAcquisitionError("远程 Torrent 重定向次数过多")
                current = _validated_https_url(engine_module, urljoin(current, location))
                continue
            if status < 200 or status >= 300:
                raise TorrentMetadataAcquisitionError(f"远程 Torrent 请求失败：HTTP {status or 'unknown'}")
            return _read_response_body(response)
        except TorrentMetadataAcquisitionError:
            raise
        except Exception as exc:
            if request_errors and isinstance(exc, request_errors):
                raise TorrentMetadataAcquisitionError(f"远程 Torrent 请求失败：{exc}") from exc
            raise
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
    raise TorrentMetadataAcquisitionError("远程 Torrent 重定向失败")


def _magnet_metadata_command(executable: Path, directory: Path, source: str) -> list[str]:
    return [
        str(executable),
        "--dir",
        str(directory),
        "--bt-metadata-only=true",
        "--bt-save-metadata=true",
        "--seed-time=0",
        "--file-allocation=none",
        "--summary-interval=0",
        "--console-log-level=warn",
        "--download-result=hide",
        "--",
        source,
    ]


def acquire_magnet_metadata(
    engine_module,
    source: object,
    executable: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout_seconds: float = MAGNET_METADATA_TIMEOUT,
) -> AcquiredTorrentMetadata:
    try:
        classified = require_torrent_source(source)
    except Aria2SourceError as exc:
        raise TorrentMetadataAcquisitionError(str(exc)) from exc
    if classified.kind != "magnet":
        raise TorrentMetadataAcquisitionError("该来源不是 Magnet 链接")
    executable = Path(executable)
    if not str(executable):
        raise TorrentMetadataAcquisitionError("未检测到 aria2c，无法获取 Magnet 元数据")

    work_root = _cache_dir(engine_module)
    temp_dir = Path(tempfile.mkdtemp(prefix="magnet-", dir=work_root))
    try:
        try:
            completed = runner(
                _magnet_metadata_command(executable, temp_dir, classified.source),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=max(10.0, min(float(timeout_seconds), 300.0)),
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TorrentMetadataAcquisitionError("获取 Magnet 元数据超时") from exc
        except OSError as exc:
            raise TorrentMetadataAcquisitionError(f"无法启动 aria2c：{exc}") from exc
        if int(getattr(completed, "returncode", 1)) != 0:
            output = str(getattr(completed, "stdout", "") or "").strip().replace("\r", " ").replace("\n", " ")
            raise TorrentMetadataAcquisitionError((output[:300] or "aria2c 未能获取 Magnet 元数据"))

        candidates = [path for path in temp_dir.glob("*.torrent") if path.is_file() and not path.is_symlink()]
        if len(candidates) != 1:
            raise TorrentMetadataAcquisitionError("Magnet 元数据获取完成，但未生成唯一的 .torrent 文件")
        try:
            data = candidates[0].read_bytes()
        except OSError as exc:
            raise TorrentMetadataAcquisitionError("无法读取 Magnet 元数据文件") from exc
        if len(data) > TORRENT_FILE_MAX_BYTES:
            raise TorrentMetadataAcquisitionError("Magnet 元数据超过 10 MB")
        cached, metadata = _cache_bytes(engine_module, data)
        return AcquiredTorrentMetadata(classified.source, classified.kind, cached, metadata)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def acquire_torrent_metadata(
    engine_module,
    source: object,
    *,
    executable: Path | None = None,
    request_get: Callable[..., object] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> AcquiredTorrentMetadata:
    try:
        classified = require_torrent_source(source)
    except Aria2SourceError as exc:
        raise TorrentMetadataAcquisitionError(str(exc)) from exc
    if classified.kind == "torrent_file":
        try:
            metadata = read_local_torrent_metadata(classified.source)
        except TorrentMetadataError as exc:
            raise TorrentMetadataAcquisitionError(str(exc)) from exc
        return AcquiredTorrentMetadata(classified.source, classified.kind, Path(classified.source), metadata)
    if classified.kind == "torrent_url":
        data = fetch_https_torrent_bytes(engine_module, classified.source, request_get=request_get)
        cached, metadata = _cache_bytes(engine_module, data)
        return AcquiredTorrentMetadata(classified.source, classified.kind, cached, metadata)
    if executable is None:
        raise TorrentMetadataAcquisitionError("未检测到 aria2c，无法获取 Magnet 元数据")
    return acquire_magnet_metadata(engine_module, classified.source, Path(executable), runner=runner)


def run_torrent_metadata_acquisition_self_test() -> None:
    import tempfile as _tempfile

    def b(value: bytes) -> bytes:
        return str(len(value)).encode("ascii") + b":" + value

    payload = b"d4:infod6:lengthi5e4:name" + b(b"a.bin") + b"ee"

    class FakeResponse:
        def __init__(self, status_code: int, body: bytes = b"", location: str = "") -> None:
            self.status_code = status_code
            self.body = body
            self.headers = {"Location": location} if location else {"Content-Length": str(len(body))}
        def iter_content(self, chunk_size=65536):
            del chunk_size
            yield self.body
        def close(self):
            return None

    with _tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        calls: list[str] = []

        class FakeEngine:
            @staticmethod
            def state_dir() -> Path:
                return root / "state"
            @staticmethod
            def app_dir() -> Path:
                return root
            @staticmethod
            def _validated_source_url(value: str) -> str:
                calls.append(value)
                if "127.0.0.1" in value or "localhost" in value:
                    raise ValueError("private address blocked")
                return value

        responses = iter([
            FakeResponse(302, location="https://cdn.example.com/final.torrent"),
            FakeResponse(200, payload),
        ])
        data = fetch_https_torrent_bytes(
            FakeEngine,
            "https://downloads.example.com/demo.torrent",
            request_get=lambda *args, **kwargs: next(responses),
        )
        assert data == payload
        assert calls == ["https://downloads.example.com/demo.torrent", "https://cdn.example.com/final.torrent"]

        blocked = iter([FakeResponse(302, location="https://127.0.0.1/private.torrent")])
        try:
            fetch_https_torrent_bytes(
                FakeEngine,
                "https://downloads.example.com/demo.torrent",
                request_get=lambda *args, **kwargs: next(blocked),
            )
        except TorrentMetadataAcquisitionError:
            pass
        else:
            raise AssertionError("private redirect escaped validation")

        acquired = acquire_torrent_metadata(
            FakeEngine,
            "https://downloads.example.com/demo.torrent",
            request_get=lambda *args, **kwargs: FakeResponse(200, payload),
        )
        assert acquired.original_kind == "torrent_url"
        assert acquired.torrent_path.exists()
        assert acquired.metadata.files[0].path == "a.bin"

        command = _magnet_metadata_command(Path("aria2c"), root / "tmp", "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567")
        assert "--bt-metadata-only=true" in command
        assert "--bt-save-metadata=true" in command
        assert command[-2] == "--"


if __name__ == "__main__":
    run_torrent_metadata_acquisition_self_test()
    print("torrent_metadata_acquisition self-test: OK")
