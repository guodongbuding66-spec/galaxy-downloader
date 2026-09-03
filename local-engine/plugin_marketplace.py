from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import urllib.request
import uuid
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plugin_host import ALLOWED_CAPABILITIES, PLUGIN_ID_RE, PLUGIN_MANIFEST, VERSION_RE, plugins_dir
from runtime_storage import state_dir as runtime_state_dir
from url_policy import validated_public_http_url

DEFAULT_MARKETPLACE_URL = (
    "https://raw.githubusercontent.com/guodongbuding66-spec/galaxy-downloader/main/plugins/index.json"
)
MARKETPLACE_CACHE_FILENAME = "plugin-marketplace.json"
MARKETPLACE_SCHEMA = 1
MAX_INDEX_BYTES = 2_000_000
MAX_PACKAGE_BYTES = 100_000_000
MAX_ARCHIVE_FILES = 5_000
MAX_ARCHIVE_EXPANDED_BYTES = 250_000_000
MAX_MARKETPLACE_ENTRIES = 200


class PluginMarketplaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketplaceEntry:
    plugin_id: str
    name: str
    version: str
    package_url: str
    sha256: str
    capabilities: tuple[str, ...]
    description: str = ""
    platforms: tuple[str, ...] = ()

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "packageUrl": self.package_url,
            "sha256": self.sha256,
            "capabilities": list(self.capabilities),
            "description": self.description,
            "platforms": list(self.platforms),
        }


def _marketplace_cache_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / MARKETPLACE_CACHE_FILENAME


def _safe_https_url(value: object) -> str:
    url = validated_public_http_url(str(value or "").strip())
    if not url.lower().startswith("https://"):
        raise PluginMarketplaceError("plugin marketplace URLs must use HTTPS")
    return url


def _clean_entry(value: object) -> MarketplaceEntry | None:
    if not isinstance(value, dict):
        return None
    plugin_id = str(value.get("id") or "").strip().lower()
    name = " ".join(str(value.get("name") or "").split()).strip()[:100]
    version = str(value.get("version") or "").strip()
    package_url = str(value.get("packageUrl") or "").strip()
    digest = str(value.get("sha256") or "").strip().lower()
    description = " ".join(str(value.get("description") or "").split()).strip()[:600]
    if not PLUGIN_ID_RE.fullmatch(plugin_id) or not name or not VERSION_RE.fullmatch(version):
        return None
    if not package_url.lower().startswith("https://") or not digest or len(digest) != 64:
        return None
    if any(character not in "0123456789abcdef" for character in digest):
        return None

    capabilities: list[str] = []
    raw_capabilities = value.get("capabilities")
    if not isinstance(raw_capabilities, list):
        return None
    for raw in raw_capabilities:
        capability = str(raw or "").strip().lower()
        if capability not in ALLOWED_CAPABILITIES:
            return None
        if capability not in capabilities:
            capabilities.append(capability)
    if not capabilities:
        return None

    platforms: list[str] = []
    for raw in value.get("platforms") if isinstance(value.get("platforms"), list) else []:
        platform = str(raw or "").strip().lower()
        if platform in {"windows", "macos", "linux", "any"} and platform not in platforms:
            platforms.append(platform)
    return MarketplaceEntry(
        plugin_id=plugin_id,
        name=name,
        version=version,
        package_url=package_url,
        sha256=digest,
        capabilities=tuple(capabilities),
        description=description,
        platforms=tuple(platforms),
    )


def parse_marketplace_index(value: object) -> tuple[MarketplaceEntry, ...]:
    if not isinstance(value, dict) or int(value.get("schema") or 0) != MARKETPLACE_SCHEMA:
        raise PluginMarketplaceError("unsupported plugin marketplace index schema")
    source = value.get("plugins")
    if not isinstance(source, list):
        raise PluginMarketplaceError("plugin marketplace index must contain a plugins array")
    result: list[MarketplaceEntry] = []
    for raw in source:
        entry = _clean_entry(raw)
        if entry is None or any(existing.plugin_id == entry.plugin_id for existing in result):
            continue
        result.append(entry)
        if len(result) >= MAX_MARKETPLACE_ENTRIES:
            break
    return tuple(result)


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _safe_https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_bytes(url: str, *, max_bytes: int, timeout: int = 30) -> bytes:
    validated = _safe_https_url(url)
    request = urllib.request.Request(
        validated,
        headers={"User-Agent": "GalaxyLocalEngine/1.0"},
        method="GET",
    )
    opener = urllib.request.build_opener(_ValidatedRedirectHandler())
    try:
        with opener.open(request, timeout=max(5, min(int(timeout), 120))) as response:  # noqa: S310
            _safe_https_url(response.geturl())
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > max_bytes:
                raise PluginMarketplaceError("marketplace response exceeds the safety limit")
            chunks: list[bytes] = []
            total = 0
            while True:
                block = response.read(min(1024 * 1024, max_bytes - total + 1))
                if not block:
                    break
                total += len(block)
                if total > max_bytes:
                    raise PluginMarketplaceError("marketplace response exceeds the safety limit")
                chunks.append(block)
            return b"".join(chunks)
    except PluginMarketplaceError:
        raise
    except Exception as exc:
        raise PluginMarketplaceError(str(exc)) from exc


def refresh_marketplace(engine_module, index_url: object = DEFAULT_MARKETPLACE_URL) -> tuple[MarketplaceEntry, ...]:
    data = _fetch_bytes(str(index_url or DEFAULT_MARKETPLACE_URL), max_bytes=MAX_INDEX_BYTES, timeout=30)
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PluginMarketplaceError("plugin marketplace returned invalid JSON") from exc
    entries = parse_marketplace_index(raw)
    cache = _marketplace_cache_path(engine_module)
    temporary = cache.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema": MARKETPLACE_SCHEMA,
                "source": str(index_url or DEFAULT_MARKETPLACE_URL)[:1200],
                "plugins": [item.public_payload() for item in entries],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(cache)
    return entries


def load_marketplace(engine_module) -> tuple[MarketplaceEntry, ...]:
    try:
        raw = json.loads(_marketplace_cache_path(engine_module).read_text(encoding="utf-8"))
        return parse_marketplace_index(raw)
    except (OSError, TypeError, ValueError, PluginMarketplaceError):
        return ()


def get_marketplace_entry(engine_module, plugin_id: object) -> MarketplaceEntry | None:
    clean = str(plugin_id or "").strip().lower()
    return next((item for item in load_marketplace(engine_module) if item.plugin_id == clean), None)


def _safe_archive_member(name: str) -> Path:
    normalized = str(name or "").replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or not normalized or any(part in {"", ".", ".."} for part in path.parts):
        raise PluginMarketplaceError("plugin archive contains an unsafe path")
    return path


def _extract_verified_zip(package: bytes, destination: Path) -> None:
    with tempfile.NamedTemporaryFile(prefix="galaxy-plugin-", suffix=".zip", delete=False) as handle:
        handle.write(package)
        archive_path = Path(handle.name)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_FILES:
                raise PluginMarketplaceError("plugin archive contains too many files")
            expanded = 0
            for member in members:
                _safe_archive_member(member.filename)
                unix_mode = (member.external_attr >> 16) & 0o170000
                if unix_mode in {stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK}:
                    raise PluginMarketplaceError("plugin archive contains unsupported special files")
                expanded += max(0, int(member.file_size))
                if expanded > MAX_ARCHIVE_EXPANDED_BYTES:
                    raise PluginMarketplaceError("plugin archive expands beyond the safety limit")
            archive.extractall(destination)
    except zipfile.BadZipFile as exc:
        raise PluginMarketplaceError("plugin package is not a valid ZIP archive") from exc
    finally:
        with suppress(OSError):
            archive_path.unlink()


def _plugin_root(extracted: Path) -> Path:
    if (extracted / PLUGIN_MANIFEST).is_file():
        return extracted
    candidates = [
        item for item in extracted.iterdir()
        if item.is_dir() and not item.is_symlink() and (item / PLUGIN_MANIFEST).is_file()
    ]
    if len(candidates) != 1:
        raise PluginMarketplaceError("plugin package must contain exactly one plugin manifest")
    return candidates[0]


def _validate_package_root(root: Path, entry: MarketplaceEntry) -> str:
    try:
        raw = json.loads((root / PLUGIN_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise PluginMarketplaceError("plugin package contains an invalid manifest") from exc
    if not isinstance(raw, dict):
        raise PluginMarketplaceError("plugin manifest must be an object")
    plugin_id = str(raw.get("id") or "").strip().lower()
    version = str(raw.get("version") or "").strip()
    executable = str(raw.get("executable") or "").strip()
    capabilities = tuple(dict.fromkeys(str(item or "").strip().lower() for item in raw.get("capabilities", [])))
    if plugin_id != entry.plugin_id or version != entry.version:
        raise PluginMarketplaceError("plugin package identity does not match marketplace metadata")
    if not executable or Path(executable).name != executable:
        raise PluginMarketplaceError("plugin package executable path is unsafe")
    if not capabilities or any(item not in ALLOWED_CAPABILITIES for item in capabilities):
        raise PluginMarketplaceError("plugin package declares unsupported capabilities")
    executable_path = root / executable
    if not executable_path.is_file() or executable_path.is_symlink():
        raise PluginMarketplaceError("plugin package executable is missing or unsafe")
    if os.name != "nt":
        executable_path.chmod(executable_path.stat().st_mode | stat.S_IXUSR)
    return executable


def install_marketplace_plugin(engine_module, plugin_id: object) -> MarketplaceEntry:
    entry = get_marketplace_entry(engine_module, plugin_id)
    if entry is None:
        raise PluginMarketplaceError("plugin is not present in the cached marketplace index")
    package = _fetch_bytes(entry.package_url, max_bytes=MAX_PACKAGE_BYTES, timeout=60)
    actual = hashlib.sha256(package).hexdigest()
    if actual != entry.sha256:
        raise PluginMarketplaceError("plugin package SHA-256 did not match the marketplace index")

    root = plugins_dir(engine_module)
    staging = root / f".marketplace-{entry.plugin_id}-{uuid.uuid4().hex}"
    target = root / entry.plugin_id
    backup = root / f".backup-{entry.plugin_id}-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        _extract_verified_zip(package, staging)
        source_root = _plugin_root(staging)
        _validate_package_root(source_root, entry)
        prepared = root / f".prepared-{entry.plugin_id}-{uuid.uuid4().hex}"
        if source_root == staging:
            staging.replace(prepared)
        else:
            source_root.replace(prepared)
            shutil.rmtree(staging, ignore_errors=True)
        if target.exists():
            target.replace(backup)
        prepared.replace(target)
        shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not target.exists():
            with suppress(OSError):
                backup.replace(target)
        raise
    return entry


def uninstall_plugin(engine_module, plugin_id: object) -> bool:
    clean = str(plugin_id or "").strip().lower()
    if not PLUGIN_ID_RE.fullmatch(clean):
        return False
    target = plugins_dir(engine_module) / clean
    if not target.is_dir() or target.is_symlink():
        return False
    shutil.rmtree(target)
    return True


def marketplace_status(engine_module) -> dict[str, Any]:
    entries = load_marketplace(engine_module)
    installed = {item.name for item in plugins_dir(engine_module).iterdir() if item.is_dir() and not item.is_symlink()}
    return {
        "source": DEFAULT_MARKETPLACE_URL,
        "cached": bool(entries),
        "entries": [
            {**item.public_payload(), "installed": item.plugin_id in installed}
            for item in entries
        ],
    }


def run_plugin_marketplace_self_test() -> None:
    index = {
        "schema": 1,
        "plugins": [
            {
                "id": "demo.plugin",
                "name": "Demo",
                "version": "1.2.3",
                "packageUrl": "https://example.invalid/demo.zip",
                "sha256": "a" * 64,
                "capabilities": ["metadata", "download"],
                "platforms": ["any"],
            }
        ],
    }
    entries = parse_marketplace_index(index)
    assert len(entries) == 1
    assert entries[0].plugin_id == "demo.plugin"
    assert entries[0].capabilities == ("metadata", "download")
    try:
        _safe_archive_member("../escape")
    except PluginMarketplaceError:
        pass
    else:
        raise AssertionError("unsafe plugin archive path was accepted")
