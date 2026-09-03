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
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DISCOVERY_PORT = 38977
P2P_MAGIC = "GALAXY_P2P1"
P2P_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
P2P_CODE_LENGTH = 12
P2P_MAX_FILE_BYTES = 50 * 1024 * 1024 * 1024
P2P_DEFAULT_TTL_SECONDS = 10 * 60
TORRENT_FILE_MAX_BYTES = 10 * 1024 * 1024
MAGNET_RE = re.compile(r"^magnet:\?xt=urn:btih:[A-Za-z0-9]{32,64}(?:&.*)?$", re.IGNORECASE)


class TransferError(RuntimeError):
    pass


@dataclass(frozen=True)
class TorrentResult:
    destination: Path
    message: str


@dataclass(frozen=True)
class P2PReceiveResult:
    path: Path
    size_bytes: int
    sha256: str


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def find_aria2c(engine_module) -> Path | None:
    names = ("aria2c.exe", "aria2c") if os.name == "nt" else ("aria2c",)
    roots: list[Path] = []
    accessor = getattr(engine_module, "tools_dir", None)
    if callable(accessor):
        try:
            tools = Path(accessor())
            roots.extend((tools / "aria2" / "bin", tools / "aria2", tools / "bin", tools))
        except (OSError, RuntimeError, TypeError, ValueError):
            roots = list(roots)
    app_accessor = getattr(engine_module, "app_dir", None)
    if callable(app_accessor):
        try:
            app_root = Path(app_accessor())
            roots.extend((app_root / "bin", app_root))
        except (OSError, RuntimeError, TypeError, ValueError):
            roots = list(roots)
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
    resolved = shutil.which("aria2c")
    if resolved:
        candidate = Path(resolved)
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def _torrent_source(value: object) -> str:
    text = str(value or "").strip()
    if MAGNET_RE.fullmatch(text):
        return text
    path = Path(text).expanduser().resolve(strict=False)
    if not path.is_file() or path.suffix.lower() != ".torrent":
        raise TransferError("请输入 magnet 链接或选择 .torrent 文件")
    if path.is_symlink() or path.stat().st_size > TORRENT_FILE_MAX_BYTES:
        raise TransferError("torrent 文件无效或超过 10 MB")
    return str(path)


def download_torrent(
    engine_module,
    source: object,
    *,
    timeout_seconds: int = 24 * 3600,
) -> TorrentResult:
    executable = find_aria2c(engine_module)
    if executable is None:
        raise TransferError("未检测到 aria2c；Torrent/Magnet 功能需要 aria2c")
    normalized = _torrent_source(source)
    destination = Path(engine_module.default_download_dir()) / "torrents"
    destination.mkdir(parents=True, exist_ok=True)
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
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(60, min(int(timeout_seconds), 48 * 3600)),
            check=False,
            creationflags=_creation_flags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise TransferError("Torrent 下载超时") from exc
    except OSError as exc:
        raise TransferError(str(exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise TransferError(detail[-2000:] or f"aria2c exited with {result.returncode}")
    return TorrentResult(destination, "Torrent/Magnet 下载完成；默认不继续做种")


def _clean_shared_file(path: Path) -> Path:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise TransferError("请选择普通本地文件")
    size = source.stat().st_size
    if size <= 0 or size > P2P_MAX_FILE_BYTES:
        raise TransferError("文件为空或超过 50 GB 上限")
    return source


def _sha256_file(path: Path, cancelled: Callable[[], bool] | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            if cancelled and cancelled():
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
    return data.decode("utf-8", errors="strict").strip()


def _safe_received_name(value: object) -> str:
    name = Path(str(value or "file.bin").replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "_", name).strip(" .")[:180]
    return name or "received.bin"


def _is_lan_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        address.version == 4
        and not address.is_loopback
        and not address.is_unspecified
        and not address.is_multicast
        and (address.is_private or address.is_link_local)
    )


def _lan_ipv4_candidates() -> tuple[str, ...]:
    """Find concrete local IPv4 interfaces without binding services globally."""
    values: list[str] = []
    with suppress(OSError):
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM):
            address = str(item[4][0])
            if _is_lan_ipv4(address) and address not in values:
                values.append(address)
    # UDP connect performs route selection without sending application data.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with suppress(OSError):
            probe.connect(("192.0.2.1", 9))
            address = str(probe.getsockname()[0])
            if _is_lan_ipv4(address) and address not in values:
                values.insert(0, address)
    finally:
        probe.close()
    return tuple(values)


def _preferred_lan_ipv4() -> str:
    candidates = _lan_ipv4_candidates()
    if not candidates:
        raise TransferError("未检测到可用于 P2P 的私有局域网 IPv4 地址")
    return candidates[0]


class P2PSenderSession:
    """One-file, one-use LAN sender discovered by a hashed short code.

    Discovery broadcasts only SHA-256(code), never the code itself. The TCP
    session authenticates with HMAC(code, nonce), then streams a pre-hashed file.
    The service binds only to one concrete private LAN address instead of all
    network interfaces, and expires after the first successful transfer.
    """

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
        self.ttl_seconds = max(60, min(int(ttl_seconds), 3600))
        self.on_status = on_status or (lambda _message: None)
        self._stop = threading.Event()
        self._served = threading.Event()
        self._server: socket.socket | None = None
        self.host = ""
        self.port = 0
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
        self.host = _preferred_lan_ipv4()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, 0))
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
        server = self._server
        if server is not None:
            with suppress(OSError):
                server.close()

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
            sock.bind((self.host, 0))
            while not self._stop.wait(1.0):
                with suppress(OSError):
                    sock.sendto(payload, ("255.255.255.255", DISCOVERY_PORT))
        finally:
            sock.close()

    def _run(self) -> None:
        broadcaster = threading.Thread(target=self._broadcast_loop, daemon=True)
        broadcaster.start()
        self.on_status(f"发送端已就绪，短码 {self.code}")
        try:
            while not self._stop.is_set() and not self._served.is_set():
                if time.monotonic() - self._started_at > self.ttl_seconds:
                    self.on_status("短码已过期")
                    break
                try:
                    client, _address = self._server.accept() if self._server else (None, None)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if client is None:
                    continue
                with client:
                    client.settimeout(20)
                    try:
                        if self._serve_client(client):
                            self._served.set()
                            self.on_status("文件已发送完成，短码已失效")
                    except (OSError, UnicodeError, TransferError, ValueError):
                        continue
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
        client.sendall(f"META {len(metadata)}\n".encode("ascii"))
        client.sendall(metadata)
        with self.source.open("rb") as handle:
            while not self._stop.is_set():
                block = handle.read(1024 * 1024)
                if not block:
                    return True
                client.sendall(block)
        return False


def discover_p2p_sender(code: object, *, timeout_seconds: int = 10) -> tuple[str, int, dict]:
    clean_code = str(code or "").strip().upper()
    if not re.fullmatch(rf"[{P2P_CODE_ALPHABET}]{{{P2P_CODE_LENGTH}}}", clean_code):
        raise TransferError("短码格式无效")
    expected_hash = _code_hash(clean_code)
    local_host = _preferred_lan_ipv4()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((local_host, DISCOVERY_PORT))
        deadline = time.monotonic() + max(1, min(int(timeout_seconds), 60))
        while time.monotonic() < deadline:
            sock.settimeout(max(0.1, min(1.0, deadline - time.monotonic())))
            try:
                data, address = sock.recvfrom(4096)
            except socket.timeout:
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
            sender_host = str(address[0])
            if 1 <= port <= 65535 and _is_lan_ipv4(sender_host):
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
    clean_code = str(code or "").strip().upper()
    host, port, _advert = discover_p2p_sender(clean_code, timeout_seconds=timeout_seconds)
    expected_hash = _code_hash(clean_code)
    with socket.create_connection((host, port), timeout=10) as client:
        client.settimeout(30)
        client.sendall(f"HELLO {expected_hash}\n".encode("ascii"))
        challenge = _recv_line(client)
        if not challenge.startswith("CHALLENGE "):
            raise TransferError("发送端认证握手失败")
        nonce = challenge.split(" ", 1)[1]
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
        name = _safe_received_name(metadata.get("name"))
        size = int(metadata.get("size") or 0)
        expected_sha = str(metadata.get("sha256") or "").lower()
        if size <= 0 or size > P2P_MAX_FILE_BYTES or not re.fullmatch(r"[a-f0-9]{64}", expected_sha):
            raise TransferError("发送端文件元数据未通过校验")

        target_root = Path(engine_module.default_download_dir()) / "received"
        target_root.mkdir(parents=True, exist_ok=True)
        destination = target_root / name
        if destination.exists():
            destination = target_root / f"{destination.stem}-{secrets.token_hex(3)}{destination.suffix}"
        temporary = destination.with_suffix(destination.suffix + ".part")
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
                    if on_progress:
                        on_progress(received, size)
            actual = digest.hexdigest()
            if not hmac.compare_digest(actual, expected_sha):
                raise TransferError("P2P 文件 SHA-256 校验失败")
            temporary.replace(destination)
            return P2PReceiveResult(destination, size, actual)
        except (OSError, TransferError):
            with suppress(OSError):
                temporary.unlink()
            raise


def transfer_status(engine_module) -> dict[str, object]:
    return {
        "torrentReady": find_aria2c(engine_module) is not None,
        "p2pLan": bool(_lan_ipv4_candidates()),
        "p2pDiscoveryPort": DISCOVERY_PORT,
        "p2pCodeLength": P2P_CODE_LENGTH,
    }


def run_transfer_center_self_test() -> None:
    assert MAGNET_RE.fullmatch("magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567")
    assert not MAGNET_RE.fullmatch("http://example.com/file.torrent")
    code = _new_code()
    assert len(code) == P2P_CODE_LENGTH
    assert len(_code_hash(code)) == 64
    nonce = "abc"
    proof = hmac.new(code.encode("ascii"), nonce.encode("ascii"), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(proof, proof)
    assert _safe_received_name("../evil.txt") == "evil.txt"
    assert _is_lan_ipv4("127.0.0.1") is False
    assert _is_lan_ipv4("192.168.1.5") is True
