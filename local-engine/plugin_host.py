from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

PLUGIN_MANIFEST = "galaxy-plugin.json"
PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?$")
ALLOWED_CAPABILITIES = frozenset({"parse", "download", "batch", "metadata"})
MAX_PLUGINS = 50
MAX_MANIFEST_BYTES = 64 * 1024
MAX_PLUGIN_REQUEST_BYTES = 256_000
MAX_PLUGIN_RESPONSE_BYTES = 2_000_000
MAX_PLUGIN_STDERR_BYTES = 256_000
_SAFE_ENV_KEYS = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LANG",
        "LC_ALL",
    }
)


class PluginHostError(RuntimeError):
    pass


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    executable: str
    capabilities: tuple[str, ...]
    root: Path

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "capabilities": list(self.capabilities),
        }


def plugins_dir(engine_module) -> Path:
    accessor = getattr(engine_module, "data_dir", None)
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir()) / "data"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "plugins"
    if target.exists() and target.is_symlink():
        raise PluginHostError("plugin root cannot be a symbolic link")
    target.mkdir(parents=True, exist_ok=True)
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise PluginHostError("plugin root escaped Galaxy data directory") from exc
    return target


def _safe_child(root: Path, name: object) -> Path:
    raw = str(name or "").strip()
    if not raw or Path(raw).is_absolute() or "/" in raw or "\\" in raw or raw in {".", ".."}:
        raise PluginHostError("plugin executable must be a single file name")
    candidate = (root / raw).resolve(strict=False)
    try:
        candidate.relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise PluginHostError("plugin executable escaped plugin directory") from exc
    return candidate


def _parse_manifest(path: Path) -> PluginManifest:
    try:
        if path.is_symlink() or not path.is_file():
            raise PluginHostError("plugin manifest must be a regular file")
        size = path.stat().st_size
        if size <= 0 or size > MAX_MANIFEST_BYTES:
            raise PluginHostError("plugin manifest size is invalid")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except PluginHostError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise PluginHostError(f"invalid plugin manifest: {path}") from exc
    if not isinstance(raw, dict):
        raise PluginHostError("plugin manifest must be an object")
    plugin_id = str(raw.get("id") or "").strip().lower()
    name = " ".join(str(raw.get("name") or "").split()).strip()[:100]
    version = str(raw.get("version") or "").strip()
    executable = str(raw.get("executable") or "").strip()
    capabilities_raw = raw.get("capabilities")
    if not PLUGIN_ID_RE.fullmatch(plugin_id):
        raise PluginHostError("invalid plugin id")
    if not name:
        raise PluginHostError("plugin name is required")
    if not VERSION_RE.fullmatch(version):
        raise PluginHostError("invalid plugin version")
    if not isinstance(capabilities_raw, list):
        raise PluginHostError("plugin capabilities must be a list")
    capabilities: list[str] = []
    for value in capabilities_raw:
        capability = str(value or "").strip().lower()
        if capability not in ALLOWED_CAPABILITIES:
            raise PluginHostError(f"unsupported plugin capability: {capability}")
        if capability not in capabilities:
            capabilities.append(capability)
    if not capabilities:
        raise PluginHostError("plugin must declare at least one capability")
    _safe_child(path.parent, executable)
    return PluginManifest(plugin_id, name, version, executable, tuple(capabilities), path.parent)


def discover_plugins(engine_module) -> tuple[PluginManifest, ...]:
    root = plugins_dir(engine_module)
    manifests: list[PluginManifest] = []
    try:
        directories = sorted(root.iterdir(), key=lambda value: value.name.lower())
    except OSError as exc:
        raise PluginHostError(str(exc)) from exc
    for directory in directories:
        if not directory.is_dir() or directory.is_symlink():
            continue
        manifest_path = directory / PLUGIN_MANIFEST
        try:
            manifest = _parse_manifest(manifest_path)
            executable = _safe_child(directory, manifest.executable)
        except PluginHostError:
            continue
        if not executable.is_file() or executable.is_symlink():
            continue
        if any(item.plugin_id == manifest.plugin_id for item in manifests):
            continue
        manifests.append(manifest)
        if len(manifests) >= MAX_PLUGINS:
            break
    return tuple(manifests)


def get_plugin(engine_module, plugin_id: object) -> PluginManifest | None:
    clean = str(plugin_id or "").strip().lower()
    if not PLUGIN_ID_RE.fullmatch(clean):
        return None
    return next((item for item in discover_plugins(engine_module) if item.plugin_id == clean), None)


def _plugin_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in _SAFE_ENV_KEYS and isinstance(value, str)
    }
    environment["GALAXY_PLUGIN_PROTOCOL"] = "1"
    return environment


def _bounded_pipe_reader(
    stream: BinaryIO,
    limit: int,
    buffer: bytearray,
    overflow: threading.Event,
    process,
) -> None:
    try:
        while True:
            block = stream.read(64 * 1024)
            if not block:
                return
            remaining = limit - len(buffer)
            if remaining > 0:
                buffer.extend(block[:remaining])
            if len(block) > remaining:
                overflow.set()
                with suppress(OSError):
                    process.kill()
                return
    except (OSError, ValueError):
        return


def _run_plugin_process(executable: Path, envelope: bytes, *, timeout_seconds: int) -> tuple[bytes, bytes, int, bool, bool]:
    try:
        timeout = max(5, min(int(timeout_seconds), 1800))
    except (TypeError, ValueError):
        timeout = 300
    try:
        process = subprocess.Popen(
            [str(executable), "--galaxy-run"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_plugin_environment(),
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except OSError as exc:
        raise PluginHostError(str(exc)) from exc
    if process.stdin is None or process.stdout is None or process.stderr is None:
        with suppress(OSError):
            process.kill()
        raise PluginHostError("plugin process pipes are unavailable")

    stdout = bytearray()
    stderr = bytearray()
    stdout_overflow = threading.Event()
    stderr_overflow = threading.Event()
    readers = (
        threading.Thread(
            target=_bounded_pipe_reader,
            args=(process.stdout, MAX_PLUGIN_RESPONSE_BYTES, stdout, stdout_overflow, process),
            daemon=True,
        ),
        threading.Thread(
            target=_bounded_pipe_reader,
            args=(process.stderr, MAX_PLUGIN_STDERR_BYTES, stderr, stderr_overflow, process),
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()
    try:
        process.stdin.write(envelope)
        process.stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        with suppress(OSError, ValueError):
            process.stdin.close()

    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        with suppress(OSError):
            process.kill()
        with suppress(OSError, subprocess.TimeoutExpired):
            process.wait(timeout=2)
        for reader in readers:
            reader.join(timeout=1)
        raise PluginHostError("plugin timed out") from exc
    for reader in readers:
        reader.join(timeout=1)
    return bytes(stdout), bytes(stderr), int(return_code), stdout_overflow.is_set(), stderr_overflow.is_set()


def invoke_plugin(
    engine_module,
    plugin_id: object,
    capability: object,
    request: dict[str, Any],
    *,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    clean_capability = str(capability or "").strip().lower()
    manifest = get_plugin(engine_module, plugin_id)
    if manifest is None:
        raise PluginHostError("plugin not found")
    if clean_capability not in manifest.capabilities:
        raise PluginHostError("plugin did not declare requested capability")
    if not isinstance(request, dict):
        raise PluginHostError("plugin request must be an object")

    envelope = json.dumps(
        {"protocol": 1, "capability": clean_capability, "request": request},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(envelope) > MAX_PLUGIN_REQUEST_BYTES:
        raise PluginHostError("plugin request is too large")

    executable = _safe_child(manifest.root, manifest.executable)
    if not executable.is_file() or executable.is_symlink():
        raise PluginHostError("plugin executable is unavailable")
    stdout, stderr, return_code, stdout_overflow, stderr_overflow = _run_plugin_process(
        executable,
        envelope,
        timeout_seconds=timeout_seconds,
    )
    if stdout_overflow:
        raise PluginHostError("plugin response is too large")
    if stderr_overflow:
        raise PluginHostError("plugin error output is too large")
    if return_code != 0:
        detail = stderr.decode("utf-8", errors="replace")[-1200:]
        raise PluginHostError(detail or f"plugin exited with {return_code}")
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PluginHostError("plugin returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise PluginHostError("plugin response must be an object")
    return payload


def plugin_host_status(engine_module) -> dict[str, Any]:
    return {
        "protocol": 1,
        "plugins": [item.public_payload() for item in discover_plugins(engine_module)],
        "capabilities": sorted(ALLOWED_CAPABILITIES),
    }


def run_plugin_host_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def data_dir() -> Path:
                return root / "data"

        plugin = plugins_dir(Engine) / "demo"
        plugin.mkdir()
        executable_name = "demo.exe" if os.name == "nt" else "demo"
        (plugin / executable_name).write_bytes(b"not-executed")
        (plugin / PLUGIN_MANIFEST).write_text(
            json.dumps(
                {
                    "id": "demo.plugin",
                    "name": "Demo Plugin",
                    "version": "1.0.0",
                    "executable": executable_name,
                    "capabilities": ["metadata", "download"],
                }
            ),
            encoding="utf-8",
        )
        discovered = discover_plugins(Engine)
        assert len(discovered) == 1
        assert discovered[0].plugin_id == "demo.plugin"
        assert discovered[0].capabilities == ("metadata", "download")
        try:
            _safe_child(plugin, "../escape")
        except PluginHostError:
            pass
        else:
            raise AssertionError("unsafe plugin executable was accepted")

        with patch.dict(
            os.environ,
            {
                "PATH": os.environ.get("PATH", ""),
                "OPENAI_API_KEY": "must-not-leak",
                "GALAXY_TEST_TOKEN": "must-not-leak",
            },
            clear=False,
        ):
            environment = _plugin_environment()
            assert "OPENAI_API_KEY" not in environment
            assert "GALAXY_TEST_TOKEN" not in environment
            assert environment["GALAXY_PLUGIN_PROTOCOL"] == "1"

        class RecordingStdin:
            def __init__(self) -> None:
                self.data = bytearray()

            def write(self, value: bytes) -> int:
                self.data.extend(value)
                return len(value)

            def flush(self) -> None:
                return None

            def close(self) -> None:
                return None

        class FakeProcess:
            def __init__(self, *_args, **kwargs) -> None:
                import io

                self.stdin = RecordingStdin()
                self.stdout = io.BytesIO(b'{"ok":true}')
                self.stderr = io.BytesIO(b"")
                self.returncode = 0
                self.killed = False
                self.environment = kwargs.get("env", {})

            def wait(self, timeout=None) -> int:
                return self.returncode

            def kill(self) -> None:
                self.killed = True
                self.returncode = -9

        with patch("plugin_host.subprocess.Popen", side_effect=FakeProcess) as popen:
            payload = invoke_plugin(Engine, "demo.plugin", "metadata", {"id": 1})
            assert payload == {"ok": True}
            assert popen.call_args.kwargs["shell"] is False
            assert "OPENAI_API_KEY" not in popen.call_args.kwargs["env"]

        oversized = b"x" * (MAX_PLUGIN_RESPONSE_BYTES + 1)

        class OversizedProcess(FakeProcess):
            def __init__(self, *_args, **kwargs) -> None:
                import io

                super().__init__(*_args, **kwargs)
                self.stdout = io.BytesIO(oversized)

        with patch("plugin_host.subprocess.Popen", side_effect=OversizedProcess):
            try:
                invoke_plugin(Engine, "demo.plugin", "metadata", {})
            except PluginHostError as exc:
                assert "too large" in str(exc)
            else:
                raise AssertionError("oversized plugin response was accepted")
