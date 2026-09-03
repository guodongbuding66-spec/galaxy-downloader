from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PLUGIN_MANIFEST = "galaxy-plugin.json"
PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?$")
ALLOWED_CAPABILITIES = frozenset({"parse", "download", "batch", "metadata"})
MAX_PLUGIN_REQUEST_BYTES = 256_000
MAX_PLUGIN_RESPONSE_BYTES = 2_000_000


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
    root = Path(accessor()) if callable(accessor) else Path(engine_module.app_dir())
    target = root / "plugins"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _safe_child(root: Path, name: object) -> Path:
    raw = str(name or "").strip()
    if not raw or Path(raw).is_absolute() or "/" in raw or "\\" in raw or raw in {".", ".."}:
        raise PluginHostError("plugin executable must be a single file name")
    candidate = (root / raw).resolve(strict=False)
    try:
        candidate.relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise PluginHostError("plugin executable escaped plugin directory") from exc
    return candidate


def _parse_manifest(path: Path) -> PluginManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
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
    for directory in sorted(root.iterdir(), key=lambda value: value.name.lower()):
        if not directory.is_dir() or directory.is_symlink():
            continue
        manifest_path = directory / PLUGIN_MANIFEST
        if not manifest_path.is_file() or manifest_path.is_symlink():
            continue
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
        if len(manifests) >= 50:
            break
    return tuple(manifests)


def get_plugin(engine_module, plugin_id: object) -> PluginManifest | None:
    clean = str(plugin_id or "").strip().lower()
    return next((item for item in discover_plugins(engine_module) if item.plugin_id == clean), None)


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
    try:
        result = subprocess.run(
            [str(executable), "--galaxy-run"],
            input=envelope,
            capture_output=True,
            timeout=max(5, min(int(timeout_seconds), 1800)),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise PluginHostError("plugin timed out") from exc
    except OSError as exc:
        raise PluginHostError(str(exc)) from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[-1200:]
        raise PluginHostError(detail or f"plugin exited with {result.returncode}")
    if len(result.stdout) > MAX_PLUGIN_RESPONSE_BYTES:
        raise PluginHostError("plugin response is too large")
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
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
            json.dumps({
                "id": "demo.plugin",
                "name": "Demo Plugin",
                "version": "1.0.0",
                "executable": executable_name,
                "capabilities": ["metadata", "download"],
            }),
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
