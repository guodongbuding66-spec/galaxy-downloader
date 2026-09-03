from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

DISCOVERY_PORT = 38977
P2P_MAGIC = "GALAXY_P2P1"
P2P_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
P2P_CODE_LENGTH = 12
P2P_MAX_FILE_BYTES = 50 * 1024 * 1024 * 1024
P2P_DEFAULT_TTL_SECONDS = 10 * 60
TORRENT_FILE_MAX_BYTES = 10 * 1024 * 1024
MAX_TRANSFER_LOG_BYTES = 256_000
MAGNET_RE = re.compile(r"^magnet:\?xt=urn:btih:[A-Za-z0-9]{32,64}(?:&[^\s]*)?$", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class TransferError(RuntimeError):
    pass


@dataclass(frozen=True)
class TorrentResult:
    destination: Path
    message: str

    def public_payload(self) -> dict[str, str]:
        return {"destination": str(self.destination), "message": self.message}


@dataclass(frozen=True)
class P2PReceiveResult:
    path: Path
    size_bytes: int
    sha256: str

    def public_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        data["sizeBytes"] = data.pop("size_bytes")
        return data


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _managed_download_dir(engine_module, name: str) -> Path:
    root = Path(engine_module.default_download_dir())
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    if target.exists() and target.is_symlink():
        raise TransferError(f"{name} 目录不能是符号链接")
    target.mkdir(parents=True, exist_ok=True)
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise TransferError("Transfer 目录越界") from exc
    return target


def find_aria2c(engine_module) -> Path | None:
    names = ("aria2c.exe", "aria2c") if os.name == "nt" else ("aria2c",)
    roots: list[Path] = []
    accessor = getattr(engine_module, "tools_dir", None)
    if callable(accessor):
        with suppress(OSError, RuntimeError, TypeError, ValueError):
            tools = Path(accessor())
            roots.extend((tools / "aria2" / "bin", tools / "aria2", tools / "bin", tools))
    accessor = getattr(engine_module, "app_dir", None)
    if callable(accessor):
        with suppress(OSError, RuntimeError, TypeError, ValueError):
            app = Path(accessor())
            roots.extend((app / "bin", app))
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
    resolved = shutil.which("aria2c")
    if not resolved:
        return None
    candidate = Path(resolved)
    return candidate if candidate.is_file() and not candidate.is_symlink() else None


def _torrent_source(value: object) -> str:
    text = str(value or "").strip()
    if MAGNET_RE.fullmatch(text):
        return text
    raw = Path(text).expanduser()
    if raw.is_symlink():
        raise TransferError("torrent 文件不能是符号链接")
    try:
        path = raw.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise TransferError("请输入 magnet 链接或选择 .torrent 文件") from exc
    if not path.is_file() or path.suffix.lower() != ".torrent":
        raise TransferError("请输入 magnet 链接或选择 .torrent 文件")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise TransferError(str(exc)) from exc
    if size <= 0 or size > TORRENT_FILE_MAX_BYTES:
        raise TransferError("torrent 文件为空或超过 10 MB")
    return str(path)


def _bounded_log(path: Path) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > MAX_TRANSFER_LOG_BYTES:
                handle.seek(max(0, size - MAX_TRANSFER_LOG_BYTES))
            raw = handle.read(MAX_TRANSFER_LOG_BYTES)
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace").strip()[-4000:]


def download_torrent(engine_module, source: object, *, timeout_seconds: int = 24 * 3600) -> TorrentResult:
    executable = find_aria2c(engine_module)
    if executable is None:
        raise TransferError("未检测到 aria2c；Torrent/Magnet 功能需要 aria2c")
    normalized = _torrent_source(source)
    destination = _managed_download_dir(engine_module, "torrents")
    try:
        timeout = max(60, min(int(timeout_seconds), 48 * 3600))
    except (TypeError, ValueError) as exc:
        raise TransferError("Torrent timeout 无效") from exc
    command = [
        str(executable),
        "--dir",
        str(destination),
        "--continue=true",
        "--max-connection-per-server=8",
        "--split=8",
        "--min-split-size=1M",
        "--bt-seed-unverified=false",
        "--seed-time=0",
        "--file-allocation=none",
        "--summary-interval=5",
        "--",
        normalized,
    ]
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="galaxy-aria2-stdout-", delete=False) as stdout_file, tempfile.NamedTemporaryFile(
            prefix="galaxy-aria2-stderr-", delete=False
        ) as stderr_file:
            stdout_path = Path(stdout_file.name)
            stderr_path = Path(stderr_file.name)
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout,
                check=False,
                shell=False,
                creationflags=_creation_flags(),
            )
        if result.returncode != 0:
            detail = _bounded_log(stderr_path) or _bounded_log(stdout_path)
            raise TransferError(detail or f"aria2c exited with {result.returncode}")
    except subprocess.TimeoutExpired as exc:
        raise TransferError("Torrent 下载超时") from exc
    except OSError as exc:
        raise TransferError(str(exc)) from exc
    finally:
        for path in (stdout_path, stderr_path):
            if path is not None:
                with suppress(OSError):
                    path.unlink()
    return TorrentResult(destination, "Torrent/Magnet 下载完成；默认不继续做种")


def _clean_shared_file(path: Path) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise TransferError("请选择普通本地文件；符号链接不允许")
    try:
        source = raw.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise TransferError("共享文件不存在") from exc
    if not source.is_file():
        raise TransferError("请选择普通本地文件")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise TransferError(str(exc)) from exc
    if size <= 0 or size > P2P_MAX_FILE_BYTES:
        raise TransferError("文件为空或超过 50 GB 上限")
    return source


def _sha256_file(path: Path, cancelled: Callable[[], bool] | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            if cancelled is not None and cancelled():
                raise TransferError("操作已取消")
            block = handle.read(4 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def _new_code() -> str:
    return "".join(secrets.choice(P2P_CODE_ALPHABET) for _ in range(P2P_CODE_LENGTH))


def _clean_code(value: object) -> str:
    code = str(value or "").strip().upper()
    if not re.fullmatch(rf"[{P2P_CODE_ALPHABET}]{{{P2P_CODE_LENGTH}}}", code):
        raise TransferError("短码格式无效")
    return code


def _recv_line(sock: socket.socket, *, max_bytes: int = 4096) -> str:
    data = bytearray()
    while len(data) < max_bytes:
        chunk = sock.recv(1)
        if not chunk:
            break
        if chunk == b"\n":
            break
        data.extend(chunk)
    if len(data) >= max_bytes:
        raise TransferError("P2P 控制消息过长")
    try:
        return data.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise TransferError("P2P 控制消息编码无效") from exc


def _safe_received_name(value: object) -> str:
    name = Path(str(value or "file.bin").replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "_", name).strip(" .")[:180]
    return name or "received.bin"


def _is_lan_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(address.is_private or address.is_link_local or address.is_loopback)


def _lan_bind_address() -> str:
    candidates: list[str] = []
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM):
            address = str(item[4][0])
            if address not in candidates:
                candidates.append(address)
    except OSError:
        pass
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect chooses a routing interface but sends no packet.
        probe.connect(("192.0.2.1", 9))
        address = str(probe.getsockname()[0])
        if address not in candidates:
            candidates.append(address)
    except OSError:
        pass
    finally:
        probe.close()
    usable = [address for address in candidates if _is_lan_address(address)]
    non_loopback = [address for address in usable if not ipaddress.ip_address(address).is_loopback]
    return non_loopback[0] if non_loopback else usable[0] if usable else "127.0.0.1"


class P2PSenderSession:
    """One-file, one-use LAN sender authenticated with a short-code HMAC."""

    def __init__(
        self,
        source_file: Path,
        *,
        ttl_seconds: int = P2P_DEFAULT_TTL_SECONDS,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.source = _clean_shared_file(source_file)
        self.code = _new_code()
        self.code_hash = _code_hash(self.code)
        try:
            self.ttl_seconds = max(60, min(int(ttl_seconds), 3600))
        except (TypeError, ValueError):
            self.ttl_seconds = P2P_DEFAULT_TTL_SECONDS
        self.on_status = on_status or _ignore_status
        self._stop = threading.Event()
        self._served = threading.Event()
        self._server: socket.socket | None = None
        self.port = 0
        self.bind_address = ""
        self.sha256 = ""
        self._started_at = 0.0
        self._thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    @property
    def served(self) -> bool:
        return self._served.is_set()

    def start(self) -> "P2PSenderSession":
        if self._thread is not None:
            return self
        self.on_status("正在计算文件 SHA-256…")
        self.sha256 = _sha256_file(self.source, self._stop.is_set)
        self.bind_address = _lan_bind_address()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.bind_address, 0))
        server.listen(4)
        server.settimeout(0.5)
        self._server = server
        self.port = int(server.getsockname()[1])
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="galaxy-p2p-sender", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            with suppress(OSError):
                self._server.close()

    def _broadcast_loop(self) -> None:
        payload = json.dumps(
            {
                "magic": P2P_MAGIC,
                "codeHash": self.code_hash,
                "port": self.port,
                "name": _safe_received_name(self.source.name),
                "size": self.source.stat().st_size,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind((self.bind_address, 0))
            while not self._stop.wait(1.0):
                with suppress(OSError):
                    sock.sendto(payload, ("255.255.255.255", DISCOVERY_PORT))
        finally:
            sock.close()

    def _run(self) -> None:
        broadcaster = threading.Thread(target=self._broadcast_loop, name="galaxy-p2p-discovery", daemon=True)
        broadcaster.start()
        self.on_status(f"发送端已就绪，短码 {self.code}")
        try:
            while not self._stop.is_set() and not self._served.is_set():
                if time.monotonic() - self._started_at > self.ttl_seconds:
                    self.on_status("短码已过期")
                    break
                try:
                    client, address = self._server.accept() if self._server else (None, None)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if client is None or address is None:
                    continue
                with client:
                    client.settimeout(20)
                    if not _is_lan_address(str(address[0])):
                        continue
                    try:
                        sent = self._serve_client(client)
                    except (OSError, TransferError):
                        sent = False
                    if sent:
                        self._served.set()
                        self.on_status("文件已发送完成，短码已失效")
        finally:
            self._stop.set()
            if self._server is not None:
                with suppress(OSError):
                    self._server.close()

    def _serve_client(self, client: socket.socket) -> bool:
        hello = _recv_line(client)
        if hello != f"HELLO {self.code_hash}":
            return False
        nonce = secrets.token_hex(24)
        client.sendall(f"CHALLENGE {nonce}\n".encode("ascii"))
        expected = hmac.new(self.code.encode("ascii"), nonce.encode("ascii"), hashlib.sha256).hexdigest()
        auth = _recv_line(client)
        if not hmac.compare_digest(auth, f"AUTH {expected}"):
            return False
        metadata = json.dumps(
            {
                "name": _safe_received_name(self.source.name),
                "size": self.source.stat().st_size,
                "sha256": self.sha256,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        if len(metadata) > 8192:
            raise TransferError("P2P 文件元数据过大")
        client.sendall(f"META {len(metadata)}\n".encode("ascii"))
        client.sendall(metadata)
        with self.source.open("rb") as handle:
            while not self._stop.is_set():
                block = handle.read(1024 * 1024)
                if not block:
                    return True
                client.sendall(block)
        return False


def _ignore_status(_message: str) -> None:
    return None


def discover_p2p_sender(code: object, *, timeout_seconds: int = 10) -> tuple[str, int, dict[str, Any]]:
    clean_code = _clean_code(code)
    expected_hash = _code_hash(clean_code)
    try:
        timeout = max(1, min(int(timeout_seconds), 60))
    except (TypeError, ValueError):
        timeout = 10
    bind_address = _lan_bind_address()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((bind_address, DISCOVERY_PORT))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sock.settimeout(max(0.1, min(1.0, deadline - time.monotonic())))
            try:
                data, address = sock.recvfrom(4096)
            except socket.timeout:
                continue
            sender_host = str(address[0])
            if not _is_lan_address(sender_host):
                continue
            try:
                payload = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if not isinstance(payload, dict) or payload.get("magic") != P2P_MAGIC:
                continue
            if not hmac.compare_digest(str(payload.get("codeHash") or ""), expected_hash):
                continue
            try:
                port = int(payload.get("port") or 0)
            except (TypeError, ValueError):
                continue
            if 1 <= port <= 65535:
                return sender_host, port, payload
        raise TransferError("未在局域网发现匹配短码的发送端")
    finally:
        sock.close()


def receive_p2p_file(
    engine_module,
    code: object,
    *,
    timeout_seconds: int = 15,
    on_progress: Callable[[int, int], None] | None = None,
) -> P2PReceiveResult:
    clean_code = _clean_code(code)
    host, port, _advert = discover_p2p_sender(clean_code, timeout_seconds=timeout_seconds)
    if not _is_lan_address(host):
        raise TransferError("P2P 发送端不在局域网范围")
    expected_hash = _code_hash(clean_code)
    with socket.create_connection((host, port), timeout=10) as client:
        client.settimeout(30)
        client.sendall(f"HELLO {expected_hash}\n".encode("ascii"))
        challenge = _recv_line(client)
        if not challenge.startswith("CHALLENGE "):
            raise TransferError("发送端认证握手失败")
        nonce = challenge.split(" ", 1)[1]
        if not re.fullmatch(r"[a-f0-9]{48}", nonce):
            raise TransferError("发送端 challenge 无效")
        proof = hmac.new(clean_code.encode("ascii"), nonce.encode("ascii"), hashlib.sha256).hexdigest()
        client.sendall(f"AUTH {proof}\n".encode("ascii"))
        meta_line = _recv_line(client)
        if not meta_line.startswith("META "):
            raise TransferError("发送端没有返回文件元数据")
        try:
            meta_size = int(meta_line.split(" ", 1)[1])
        except ValueError as exc:
            raise TransferError("文件元数据长度无效") from exc
        if meta_size <= 0 or meta_size > 8192:
            raise TransferError("文件元数据过大")
        metadata_bytes = bytearray()
        while len(metadata_bytes) < meta_size:
            chunk = client.recv(meta_size - len(metadata_bytes))
            if not chunk:
                raise TransferError("文件元数据不完整")
            metadata_bytes.extend(chunk)
        try:
            metadata = json.loads(metadata_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise TransferError("文件元数据无效") from exc
        if not isinstance(metadata, dict):
            raise TransferError("文件元数据格式无效")
        name = _safe_received_name(metadata.get("name"))
        try:
            size = int(metadata.get("size") or 0)
        except (TypeError, ValueError) as exc:
            raise TransferError("文件大小元数据无效") from exc
        expected_sha = str(metadata.get("sha256") or "").lower()
        if size <= 0 or size > P2P_MAX_FILE_BYTES or not _SHA256_RE.fullmatch(expected_sha):
            raise TransferError("发送端文件元数据未通过校验")

        target_root = _managed_download_dir(engine_module, "received")
        destination = target_root / name
        if destination.exists():
            destination = target_root / f"{destination.stem}-{secrets.token_hex(3)}{destination.suffix}"
        temporary = target_root / f".{destination.name}.{secrets.token_hex(4)}.part"
        digest = hashlib.sha256()
        received = 0
        try:
            with temporary.open("xb") as handle:
                while received < size:
                    chunk = client.recv(min(1024 * 1024, size - received))
                    if not chunk:
                        raise TransferError("P2P 连接提前断开")
                    handle.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if on_progress is not None:
                        on_progress(received, size)
            actual = digest.hexdigest()
            if not hmac.compare_digest(actual, expected_sha):
                raise TransferError("P2P 文件 SHA-256 校验失败")
            temporary.replace(destination)
            return P2PReceiveResult(destination, size, actual)
        except Exception:
            with suppress(OSError):
                temporary.unlink()
            raise


def transfer_status(engine_module) -> dict[str, object]:
    return {
        "torrentReady": find_aria2c(engine_module) is not None,
        "torrentContinuedSeeding": False,
        "p2pLan": True,
        "p2pCloudRelay": False,
        "p2pDiscoveryPort": DISCOVERY_PORT,
        "p2pCodeLength": P2P_CODE_LENGTH,
        "p2pMaxFileBytes": P2P_MAX_FILE_BYTES,
        "p2pBindAddress": _lan_bind_address(),
    }


def run_transfer_center_self_test() -> None:
    assert MAGNET_RE.fullmatch("magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567")
    assert not MAGNET_RE.fullmatch("http://example.com/file.torrent")
    code = _new_code()
    assert len(code) == P2P_CODE_LENGTH
    assert _clean_code(code.lower()) == code
    assert len(_code_hash(code)) == 64
    nonce = "abc"
    proof = hmac.new(code.encode("ascii"), nonce.encode("ascii"), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(proof, proof)
    assert _safe_received_name("../evil.txt") == "evil.txt"
    assert _is_lan_address("192.168.1.10")
    assert _is_lan_address("127.0.0.1")
    assert not _is_lan_address("8.8.8.8")
    assert _is_lan_address(_lan_bind_address())
    try:
        _clean_code("../bad")
    except TransferError:
        pass
    else:
        raise AssertionError("unsafe P2P short code was accepted")
