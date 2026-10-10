from __future__ import annotations

"""Controllable aria2 transfer sessions for Galaxy Local Engine.

Upstream provenance
-------------------
Upstream: https://github.com/OpenSelena/omniget
Upstream path: src-tauri/omniget-core/src/core/tools/aria2.rs
Upstream revision: 73289076c7b4eade5eb85ab6f3948e30cec96a5e
License: GPL-3.0
Galaxy modifications: Ported the aria2 command/progress model to Python and added
pause/resume/cancel/retry lifecycle handling for the native Galaxy engine (2026-10-10).

Lifecycle design also follows the host-neutral queue semantics used by VidBee:
Upstream: https://github.com/nexmoe/VidBee
Upstream path: packages/task-queue/src/api/index.ts
Upstream revision: feeea6b2b5f451e62774c87c25f3056d583f494f
License: MIT
Galaxy modifications: Adapted queued/running/paused/completed/failed/cancelled
state semantics and bounded retry behavior; no TypeScript runtime code is required.
"""

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlparse

from aria2_source_policy import (
    Aria2SourceError,
    MAX_ARIA2_SOURCE_LENGTH,
    classify_torrent_source,
    validate_magnet_uri,
)

ARIA2_PROGRESS_RE = re.compile(
    r"\((?P<percent>\d+)%\).*?DL:(?P<speed>[^\s\]]+)",
    re.IGNORECASE,
)
ARIA2_CONNECTIONS_RE = re.compile(r"\bCN:(?P<connections>\d+)", re.IGNORECASE)
ARIA2_ETA_RE = re.compile(r"\bETA:(?P<eta>[^\s\]]+)", re.IGNORECASE)
SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
ACTIVE_STATES = frozenset({"queued", "running", "retrying", "pausing", "cancelling"})


class Aria2TransferError(RuntimeError):
    pass


@dataclass(frozen=True)
class Aria2Progress:
    percent: int = 0
    speed: str = ""
    eta: str = ""
    connections: int = 0


@dataclass(frozen=True)
class Aria2TransferOptions:
    source: str
    destination: Path
    file_name: str = ""
    connections: int = 16
    sha256: str = ""
    headers: tuple[str, ...] = ()
    seed_time_minutes: int = 0
    max_attempts: int = 3


@dataclass(frozen=True)
class Aria2TransferSnapshot:
    state: str
    attempt: int
    max_attempts: int
    progress: Aria2Progress
    destination: Path
    error: str = ""
    returncode: int | None = None


@dataclass(frozen=True)
class Aria2TransferResult:
    destination: Path
    state: str
    attempts: int
    returncode: int


def parse_aria2_progress(line: object) -> Aria2Progress | None:
    """Parse aria2's compact status line.

    Example: ``[#2089b0 12MiB/100MiB(12%) CN:16 DL:5.0MiB ETA:10s]``.
    This intentionally accepts lines where ETA is absent near completion.
    """

    text = str(line or "").strip()
    match = ARIA2_PROGRESS_RE.search(text)
    if not match:
        return None
    connection_match = ARIA2_CONNECTIONS_RE.search(text)
    eta_match = ARIA2_ETA_RE.search(text)
    try:
        percent = max(0, min(100, int(match.group("percent") or 0)))
        connections = max(0, int(connection_match.group("connections") or 0)) if connection_match else 0
    except (TypeError, ValueError):
        return None
    return Aria2Progress(
        percent=percent,
        speed=str(match.group("speed") or ""),
        eta=str(eta_match.group("eta") or "") if eta_match else "",
        connections=connections,
    )


def _safe_source(value: object) -> str:
    source = str(value or "")
    if len(source) > MAX_ARIA2_SOURCE_LENGTH:
        raise Aria2TransferError(f"aria2 source 过长；最多允许 {MAX_ARIA2_SOURCE_LENGTH} 个字符")
    if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in source):
        raise Aria2TransferError("aria2 source 包含控制字符")
    source = source.strip()
    if not source:
        raise Aria2TransferError("aria2 source 不能为空")
    if source.lower().startswith("magnet:"):
        try:
            source = validate_magnet_uri(source)
        except Aria2SourceError as exc:
            raise Aria2TransferError(str(exc)) from exc
    return source


def _is_torrent_source(source: str) -> bool:
    try:
        return classify_torrent_source(source) is not None
    except Aria2SourceError:
        return False


def _reject_fragment_manifest(source: str) -> None:
    """Keep HLS/DASH manifests on yt-dlp/FFmpeg, never aria2.

    OmniGet's current security line explicitly avoids handing fragmented
    manifests to aria2. Galaxy keeps the same boundary rather than treating
    aria2 as a generic external downloader for HLS/DASH URLs.
    """

    if source.lower().startswith("magnet:"):
        return
    try:
        path = urlparse(source).path.lower()
    except ValueError:
        path = source.lower()
    if path.endswith((".m3u8", ".mpd")):
        raise Aria2TransferError("HLS/DASH 清单必须交给 yt-dlp/FFmpeg，不能直接交给 aria2c")


def _safe_file_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if any(char in text for char in ("\r", "\n", "\x00")):
        raise Aria2TransferError("输出文件名包含非法字符")
    name = Path(text.replace("\\", "/")).name.strip(" .")
    if not name or name in {".", ".."}:
        raise Aria2TransferError("输出文件名无效")
    return name[:240]


def _safe_headers(values: Iterable[object]) -> tuple[str, ...]:
    headers: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if any(char in text for char in ("\r", "\n", "\x00")):
            raise Aria2TransferError("HTTP Header 包含非法换行")
        headers.append(text[:4096])
        if len(headers) >= 32:
            break
    return tuple(headers)


def normalize_options(options: Aria2TransferOptions) -> Aria2TransferOptions:
    source = _safe_source(options.source)
    _reject_fragment_manifest(source)
    destination = Path(options.destination).expanduser()
    if destination.exists() and destination.is_symlink():
        raise Aria2TransferError("aria2 下载目录不能是符号链接")
    destination.mkdir(parents=True, exist_ok=True)
    try:
        connections = max(1, min(int(options.connections), 16))
        max_attempts = max(1, min(int(options.max_attempts), 5))
        seed_time = max(0, min(int(options.seed_time_minutes), 60))
    except (TypeError, ValueError) as exc:
        raise Aria2TransferError("aria2 数值参数无效") from exc
    sha256 = str(options.sha256 or "").strip()
    if sha256 and not SHA256_RE.fullmatch(sha256):
        raise Aria2TransferError("SHA-256 必须是 64 位十六进制")
    return Aria2TransferOptions(
        source=source,
        destination=destination,
        file_name=_safe_file_name(options.file_name),
        connections=connections,
        sha256=sha256.lower(),
        headers=_safe_headers(options.headers),
        seed_time_minutes=seed_time,
        max_attempts=max_attempts,
    )


def build_aria2_command(executable: Path, options: Aria2TransferOptions) -> list[str]:
    """Build the aria2 command used by both HTTP and torrent sessions."""

    opts = normalize_options(options)
    command = [
        str(executable),
        "--dir",
        str(opts.destination),
        "-x",
        str(opts.connections),
        "-s",
        str(opts.connections),
        "-k",
        "1M",
        "--continue=true",
        "--auto-file-renaming=false",
        "--allow-overwrite=true",
        "--summary-interval=1",
        "--console-log-level=warn",
        "--download-result=hide",
        "--file-allocation=none",
    ]
    if _is_torrent_source(opts.source):
        command.extend(("--bt-seed-unverified=false", f"--seed-time={opts.seed_time_minutes}"))
    if opts.file_name:
        command.extend(("--out", opts.file_name))
    if opts.sha256:
        command.append(f"--checksum=sha-256={opts.sha256}")
    for header in opts.headers:
        command.append(f"--header={header}")
    command.extend(("--", opts.source))
    return command


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


class Aria2TransferSession:
    """One controllable aria2 transfer with bounded retry and resumable pause.

    Pause intentionally terminates the current aria2 process while leaving its
    partial file / ``.aria2`` control file intact. Resume launches the same
    command again with ``--continue=true``. This mirrors Galaxy's media pause
    policy: resumable stop, not process suspension.
    """

    def __init__(
        self,
        executable: Path,
        options: Aria2TransferOptions,
        *,
        on_update: Callable[[Aria2TransferSnapshot], None] | None = None,
        popen_factory: Callable[..., subprocess.Popen[str]] | None = None,
        retry_base_seconds: float = 1.0,
    ) -> None:
        self.executable = Path(executable)
        self.options = normalize_options(options)
        self._listener = on_update
        self._popen_factory = popen_factory or subprocess.Popen
        self._retry_base_seconds = max(0.0, min(float(retry_base_seconds), 30.0))
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._terminal_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None
        self._state = "queued"
        self._attempt = 0
        self._progress = Aria2Progress()
        self._error = ""
        self._returncode: int | None = None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    def set_listener(self, listener: Callable[[Aria2TransferSnapshot], None] | None) -> None:
        with self._lock:
            self._listener = listener
        self._emit()

    def snapshot(self) -> Aria2TransferSnapshot:
        with self._lock:
            return Aria2TransferSnapshot(
                state=self._state,
                attempt=self._attempt,
                max_attempts=self.options.max_attempts,
                progress=self._progress,
                destination=self.options.destination,
                error=self._error,
                returncode=self._returncode,
            )

    def _emit(self) -> None:
        snapshot = self.snapshot()
        with self._lock:
            listener = self._listener
        if listener is not None:
            try:
                listener(snapshot)
            except Exception:
                pass

    def _set_state(self, state: str, *, error: str | None = None, returncode: int | None = None) -> None:
        with self._lock:
            self._state = state
            if error is not None:
                self._error = error[:4000]
            if returncode is not None:
                self._returncode = int(returncode)
            if state in TERMINAL_STATES:
                self._terminal_event.set()
        self._emit()

    def start(self) -> "Aria2TransferSession":
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self
            if self._state in TERMINAL_STATES:
                if self._state == "completed":
                    return self
                self._terminal_event.clear()
            self._stop_event.clear()
            self._pause_event.clear()
            self._error = ""
            self._returncode = None
            self._state = "queued"
            self._thread = threading.Thread(target=self._run, name="GalaxyAria2Transfer", daemon=True)
            thread = self._thread
        self._emit()
        thread.start()
        return self

    def _terminate_process(self) -> None:
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
        except OSError:
            pass

    def pause(self) -> bool:
        with self._lock:
            if self._state not in {"running", "retrying"}:
                return False
            self._pause_event.set()
            self._state = "pausing"
        self._emit()
        self._terminate_process()
        return True

    def resume(self) -> bool:
        with self._lock:
            if self._state != "paused":
                return False
            self._pause_event.clear()
            self._stop_event.clear()
            self._state = "queued"
            self._error = ""
            self._returncode = None
            self._thread = threading.Thread(target=self._run, name="GalaxyAria2Transfer", daemon=True)
            thread = self._thread
        self._emit()
        thread.start()
        return True

    def retry(self) -> bool:
        with self._lock:
            if self._state != "failed":
                return False
            self._attempt = 0
            self._progress = Aria2Progress()
            self._terminal_event.clear()
        return bool(self.start())

    def cancel(self) -> bool:
        with self._lock:
            if self._state in TERMINAL_STATES:
                return False
            self._pause_event.clear()
            self._stop_event.set()
            thread_alive = bool(self._thread and self._thread.is_alive())
            if self._state == "paused" or not thread_alive:
                self._state = "cancelled"
                self._terminal_event.set()
                immediate = True
            else:
                self._state = "cancelling"
                immediate = False
        self._emit()
        if not immediate:
            self._terminate_process()
        return True

    def wait(self, timeout: float | None = None) -> Aria2TransferSnapshot:
        self._terminal_event.wait(timeout=timeout)
        return self.snapshot()

    def join(self, timeout: float | None = None) -> None:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def _controlled_state_after_exit(self) -> str | None:
        if self._stop_event.is_set():
            return "cancelled"
        if self._pause_event.is_set():
            return "paused"
        return None

    def _run(self) -> None:
        while True:
            controlled = self._controlled_state_after_exit()
            if controlled is not None:
                self._set_state(controlled)
                return

            with self._lock:
                self._attempt += 1
                attempt = self._attempt
            self._set_state("running", error="")
            returncode, detail = self._run_once()

            controlled = self._controlled_state_after_exit()
            if controlled is not None:
                self._set_state(controlled, returncode=returncode)
                return
            if returncode == 0:
                with self._lock:
                    if self._progress.percent < 100:
                        self._progress = Aria2Progress(
                            percent=100,
                            speed=self._progress.speed,
                            eta="",
                            connections=self._progress.connections,
                        )
                self._set_state("completed", returncode=0)
                return

            if attempt >= self.options.max_attempts:
                self._set_state("failed", error=detail or f"aria2c exited with {returncode}", returncode=returncode)
                return

            self._set_state("retrying", error=detail or f"aria2c exited with {returncode}", returncode=returncode)
            delay = min(30.0, self._retry_base_seconds * (2 ** max(0, attempt - 1)))
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                controlled = self._controlled_state_after_exit()
                if controlled is not None:
                    self._set_state(controlled, returncode=returncode)
                    return
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def _run_once(self) -> tuple[int, str]:
        command = build_aria2_command(self.executable, self.options)
        try:
            process = self._popen_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                shell=False,
                creationflags=_creation_flags(),
            )
        except OSError as exc:
            if isinstance(exc, FileNotFoundError) or getattr(exc, "errno", None) == 2:
                return 127, "未检测到 aria2c；请安装或配置 aria2c 后重试。"
            return 127, f"无法启动 aria2c：{exc}"
        with self._lock:
            self._process = process
        last_line = ""
        try:
            stream = process.stdout
            if stream is not None:
                for line in stream:
                    text = str(line or "").strip()
                    if text:
                        last_line = text[-4000:]
                    progress = parse_aria2_progress(text)
                    if progress is not None:
                        with self._lock:
                            self._progress = progress
                        self._emit()
                    if self._stop_event.is_set() or self._pause_event.is_set():
                        self._terminate_process()
            try:
                returncode = int(process.wait())
            except (OSError, ValueError):
                returncode = int(process.poll() or 1)
            return returncode, last_line
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None


def run_aria2_transfer_self_test() -> None:
    parsed = parse_aria2_progress("[#2089b0 12MiB/100MiB(12%) CN:16 DL:5.0MiB ETA:10s]")
    assert parsed == Aria2Progress(percent=12, speed="5.0MiB", eta="10s", connections=16)
    assert parse_aria2_progress("Download complete") is None

    options = normalize_options(
        Aria2TransferOptions(
            source="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
            destination=Path("downloads"),
            connections=99,
            max_attempts=99,
            seed_time_minutes=0,
        )
    )
    assert options.connections == 16
    assert options.max_attempts == 5
    command = build_aria2_command(Path("aria2c"), options)
    assert "--continue=true" in command
    assert "--seed-time=0" in command
    assert command[-2] == "--"
    assert command[-1].startswith("magnet:")

    remote_torrent = build_aria2_command(
        Path("aria2c"),
        Aria2TransferOptions(
            source="https://downloads.example.com/demo.torrent?token=abc#fragment",
            destination=Path("downloads"),
        ),
    )
    assert "--seed-time=0" in remote_torrent
    assert remote_torrent[-1].endswith("?token=abc#fragment")

    try:
        normalize_options(
            Aria2TransferOptions(
                source="magnet:?xt=urn:btih:1234",
                destination=Path("downloads"),
            )
        )
    except Aria2TransferError:
        pass
    else:
        raise AssertionError("invalid BTIH magnet was accepted by the base aria2 layer")

    try:
        normalize_options(
            Aria2TransferOptions(
                source="https://example.com/file.zip\nInjected",
                destination=Path("downloads"),
            )
        )
    except Aria2TransferError:
        pass
    else:
        raise AssertionError("source control characters were accepted")

    try:
        normalize_options(
            Aria2TransferOptions(
                source="https://media.example/video/master.m3u8",
                destination=Path("downloads"),
            )
        )
    except Aria2TransferError:
        pass
    else:
        raise AssertionError("HLS manifest was incorrectly accepted by aria2 layer")

    try:
        normalize_options(
            Aria2TransferOptions(
                source="https://example.com/file.zip",
                destination=Path("downloads"),
                headers=("X-Test: ok\r\nInjected: 1",),
            )
        )
    except Aria2TransferError:
        pass
    else:
        raise AssertionError("header injection was accepted")

    class FakeProcess:
        def __init__(self, lines: list[str], returncode: int) -> None:
            self.stdout = iter(lines)
            self._returncode = returncode
            self.terminated = False

        def wait(self) -> int:
            return self._returncode

        def poll(self) -> int | None:
            return self._returncode

        def terminate(self) -> None:
            self.terminated = True
            self._returncode = 143

    calls = 0

    def fake_popen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return FakeProcess(["temporary failure\n"], 2)
        return FakeProcess(["[#1 1MiB/1MiB(100%) CN:4 DL:2MiB]\n"], 0)

    session = Aria2TransferSession(
        Path("aria2c"),
        Aria2TransferOptions(
            source="https://example.com/file.zip",
            destination=Path("downloads"),
            max_attempts=2,
        ),
        popen_factory=fake_popen,
        retry_base_seconds=0,
    )
    session.start()
    snapshot = session.wait(timeout=2)
    assert snapshot.state == "completed"
    assert snapshot.attempt == 2
    assert snapshot.progress.percent == 100

    def missing_popen(*_args, **_kwargs):
        raise FileNotFoundError(2, "aria2c not found")

    missing = Aria2TransferSession(
        Path("aria2c"),
        Aria2TransferOptions(
            source="https://example.com/file3.zip",
            destination=Path("downloads"),
            max_attempts=1,
        ),
        popen_factory=missing_popen,
    )
    missing.start()
    missing_snapshot = missing.wait(timeout=2)
    assert missing_snapshot.state == "failed"
    assert missing_snapshot.returncode == 127
    assert "aria2c" in missing_snapshot.error and "配置" in missing_snapshot.error

    paused = Aria2TransferSession(
        Path("aria2c"),
        Aria2TransferOptions(source="https://example.com/file2.zip", destination=Path("downloads")),
    )
    paused._set_state("paused")
    assert paused.cancel() is True
    assert paused.snapshot().state == "cancelled"


if __name__ == "__main__":
    run_aria2_transfer_self_test()
    print("aria2_transfer self-test: OK")
