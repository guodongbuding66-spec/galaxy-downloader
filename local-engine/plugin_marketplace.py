from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import urllib.request
import uuid
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

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
MAX_ARCHIVE_MEMBER_BYTES = 100_000_000
MAX_MARKETPLACE_ENTRIES = 200
_PLATFORM_IDS = frozenset({"windows", "macos", "linux", "any"})
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _syntactic_https_url(value: object) -> str:
    raw = str(value or "").strip()
    try:
        parsed = urlparse(raw)
        _ = parsed.port
    except ValueError as exc:
        raise PluginMarketplaceError("plugin marketplace URL is invalid") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise PluginMarketplaceError("plugin marketplace URLs must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise PluginMarketplaceError("plugin marketplace URL contains unsupported credentials or fragment")
    if len(raw) > 2_000:
        raise PluginMarketplaceError("plugin marketplace URL is too long")
    return raw


def _safe_fetch_url(value: object) -> str:
    raw = _syntactic_https_url(value)
    try:
        validated = validated_public_http_url(raw)
    except Exception as exc:
        raise PluginMarketplaceError(str(exc)) from exc
    if not validated.lower().startswith("https://"):
        raise PluginMarketplaceError("plugin marketplace URLs must use HTTPS")
    return validated


def _clean_entry(value: object) -> MarketplaceEntry | None:
    if not isinstance(value, dict):
        return None
    plugin_id = str(value.get("id") or "").strip().lower()
    name = " ".join(str(value.get("name") or "").split()).strip()[:100]
    version = str(value.get("version") or "").strip()
    digest = str(value.get("sha256") or "").strip().lower()
    description = " ".join(str(value.get("description") or "").split()).strip()[:600]
    if not PLUGIN_ID_RE.fullmatch(plugin_id) or not name or not VERSION_RE.fullmatch(version):
        return None
    if not _HEX64_RE.fullmatch(digest):
        return None
    try:
        package_url = _syntactic_https_url(value.get("packageUrl"))
    except PluginMarketplaceError:
        return None

    raw_capabilities = value.get("capabilities")
    if not isinstance(raw_capabilities, list):
        return None
    capabilities: list[str] = []
    for raw in raw_capabilities:
        capability = str(raw or "").strip().lower()
        if capability not in ALLOWED_CAPABILITIES:
            return None
        if capability not in capabilities:
            capabilities.append(capability)
    if not capabilities:
        return None

    platforms: list[str] = []
    raw_platforms = value.get("platforms")
    if raw_platforms is not None and not isinstance(raw_platforms, list):
        return None
    for raw in raw_platforms or []:
        platform = str(raw or "").strip().lower()
        if platform not in _PLATFORM_IDS:
            return None
        if platform not in platforms:
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
    if not isinstance(value, dict):
        raise PluginMarketplaceError("plugin marketplace index must be an object")
    try:
        schema = int(value.get("schema") or 0)
    except (TypeError, ValueError) as exc:
        raise PluginMarketplaceError("unsupported plugin marketplace index schema") from exc
    if schema != MARKETPLACE_SCHEMA:
        raise PluginMarketplaceError("unsupported plugin marketplace index schema")
    source = value.get("plugins")
    if not isinstance(source, list):
        raise PluginMarketplaceError("plugin marketplace index must contain a plugins array")
    result: list[MarketplaceEntry] = []
    seen: set[str] = set()
    for raw in source:
        entry = _clean_entry(raw)
        if entry is None or entry.plugin_id in seen:
            continue
        seen.add(entry.plugin_id)
        result.append(entry)
        if len(result) >= MAX_MARKETPLACE_ENTRIES:
            break
    return tuple(result)


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _safe_fetch_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_bytes(url: object, *, max_bytes: int, timeout: int = 30) -> bytes:
    validated = _safe_fetch_url(url)
    request = urllib.request.Request(
        validated,
        headers={"User-Agent": "GalaxyLocalEngine/2.0"},
        method="GET",
    )
    opener = urllib.request.build_opener(_ValidatedRedirectHandler())
    safe_limit = max(1, min(int(max_bytes), MAX_PACKAGE_BYTES))
    safe_timeout = max(5, min(int(timeout), 120))
    try:
        with opener.open(request, timeout=safe_timeout) as response:  # noqa: S310
            _safe_fetch_url(response.geturl())
            try:
                declared = int(response.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                declared = 0
            if declared < 0 or declared > safe_limit:
                raise PluginMarketplaceError("marketplace response exceeds the safety limit")
            chunks: list[bytes] = []
            total = 0
            while True:
                block = response.read(min(1024 * 1024, safe_limit - total + 1))
                if not block:
                    break
                total += len(block)
                if total > safe_limit:
                    raise PluginMarketplaceError("marketplace response exceeds the safety limit")
                chunks.append(block)
            return b"".join(chunks)
    except PluginMarketplaceError:
        raise
    except Exception as exc:
        raise PluginMarketplaceError(str(exc)) from exc


def refresh_marketplace(engine_module, index_url: object = DEFAULT_MARKETPLACE_URL) -> tuple[MarketplaceEntry, ...]:
    source_url = _syntactic_https_url(index_url or DEFAULT_MARKETPLACE_URL)
    data = _fetch_bytes(source_url, max_bytes=MAX_INDEX_BYTES, timeout=30)
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PluginMarketplaceError("plugin marketplace returned invalid JSON") from exc
    entries = parse_marketplace_index(raw)
    cache = _marketplace_cache_path(engine_module)
    temporary = cache.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                {
                    "schema": MARKETPLACE_SCHEMA,
                    "source": source_url,
                    "plugins": [item.public_payload() for item in entries],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(cache)
    except OSError:
        with suppress(OSError):
            temporary.unlink()
        raise
    return entries


def load_marketplace(engine_module) -> tuple[MarketplaceEntry, ...]:
    cache = _marketplace_cache_path(engine_module)
    if cache.is_symlink():
        return ()
    try:
        if not cache.is_file() or cache.stat().st_size > MAX_INDEX_BYTES:
            return ()
        raw = json.loads(cache.read_text(encoding="utf-8"))
        return parse_marketplace_index(raw)
    except (OSError, TypeError, ValueError, PluginMarketplaceError):
        return ()


def get_marketplace_entry(engine_module, plugin_id: object) -> MarketplaceEntry | None:
    clean = str(plugin_id or "").strip().lower()
    if not PLUGIN_ID_RE.fullmatch(clean):
        return None
    return next((item for item in load_marketplace(engine_module) if item.plugin_id == clean), None)


def _safe_archive_member(name: object) -> PurePosixPath:
    normalized = str(name or "").replace("\\", "/")
    if not normalized or normalized.startswith("/") or "\x00" in normalized:
        raise PluginMarketplaceError("plugin archive contains an unsafe path")
    path = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise PluginMarketplaceError("plugin archive contains an unsafe path")
    if path.parts and re.match(r"^[A-Za-z]:", path.parts[0]):
        raise PluginMarketplaceError("plugin archive contains an unsafe drive path")
    return path


def _zip_member_is_special(member: zipfile.ZipInfo) -> bool:
    mode = (member.external_attr >> 16) & 0xFFFF
    return any(
        predicate(mode)
        for predicate in (stat.S_ISLNK, stat.S_ISCHR, stat.S_ISBLK, stat.S_ISFIFO, stat.S_ISSOCK)
    )


def _extract_verified_zip(package: bytes, destination: Path) -> None:
    if len(package) <= 0 or len(package) > MAX_PACKAGE_BYTES:
        raise PluginMarketplaceError("plugin package size is invalid")
    if destination.exists() and destination.is_symlink():
        raise PluginMarketplaceError("plugin staging directory cannot be a symbolic link")
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve(strict=False)
    try:
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            members = archive.infolist()
            if not members or len(members) > MAX_ARCHIVE_FILES:
                raise PluginMarketplaceError("plugin archive file count is invalid")
            expanded = 0
            for member in members:
                if member.flag_bits & 0x1:
                    raise PluginMarketplaceError("encrypted plugin archives are not supported")
                if _zip_member_is_special(member):
                    raise PluginMarketplaceError("plugin archive contains unsupported special files")
                relative = _safe_archive_member(member.filename)
                if member.file_size < 0 or member.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise PluginMarketplaceError("plugin archive member exceeds the safety limit")
                expanded += member.file_size
                if expanded > MAX_ARCHIVE_EXPANDED_BYTES:
                    raise PluginMarketplaceError("plugin archive expands beyond the safety limit")
                target = destination.joinpath(*relative.parts)
                try:
                    target.resolve(strict=False).relative_to(destination_root)
                except (OSError, RuntimeError, ValueError) as exc:
                    raise PluginMarketplaceError("plugin archive escaped the staging directory") from exc
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(member, "r") as source, target.open("xb") as output:
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        written += len(block)
                        if written > member.file_size + 1024 or written > MAX_ARCHIVE_MEMBER_BYTES:
                            raise PluginMarketplaceError("plugin archive member actual size is invalid")
                        output.write(block)
    except zipfile.BadZipFile as exc:
        raise PluginMarketplaceError("plugin package is not a valid ZIP archive") from exc


def _plugin_root(extracted: Path) -> Path:
    manifest = extracted / PLUGIN_MANIFEST
    if manifest.is_file() and not manifest.is_symlink():
        return extracted
    candidates = [
        item
        for item in extracted.iterdir()
        if item.is_dir()
        and not item.is_symlink()
        and (item / PLUGIN_MANIFEST).is_file()
        and not (item / PLUGIN_MANIFEST).is_symlink()
    ]
    if len(candidates) != 1:
        raise PluginMarketplaceError("plugin package must contain exactly one plugin manifest")
    return candidates[0]


def _validate_package_root(root: Path, entry: MarketplaceEntry) -> str:
    manifest = root / PLUGIN_MANIFEST
    if manifest.is_symlink():
        raise PluginMarketplaceError("plugin manifest cannot be a symbolic link")
    try:
        if not manifest.is_file() or manifest.stat().st_size > 64 * 1024:
            raise PluginMarketplaceError("plugin package contains an invalid manifest")
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except PluginMarketplaceError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise PluginMarketplaceError("plugin package contains an invalid manifest") from exc
    if not isinstance(raw, dict):
        raise PluginMarketplaceError("plugin manifest must be an object")
    plugin_id = str(raw.get("id") or "").strip().lower()
    version = str(raw.get("version") or "").strip()
    executable = str(raw.get("executable") or "").strip()
    raw_capabilities = raw.get("capabilities")
    if not isinstance(raw_capabilities, list):
        raise PluginMarketplaceError("plugin package capabilities are invalid")
    capabilities = tuple(dict.fromkeys(str(item or "").strip().lower() for item in raw_capabilities))
    if plugin_id != entry.plugin_id or version != entry.version:
        raise PluginMarketplaceError("plugin package identity does not match marketplace metadata")
    if set(capabilities) != set(entry.capabilities) or len(capabilities) != len(entry.capabilities):
        raise PluginMarketplaceError("plugin package capabilities do not match marketplace metadata")
    if not executable or Path(executable).name != executable or "/" in executable or "\\" in executable:
        raise PluginMarketplaceError("plugin package executable path is unsafe")
    executable_path = root / executable
    if not executable_path.is_file() or executable_path.is_symlink():
        raise PluginMarketplaceError("plugin package executable is missing or unsafe")
    if os.name != "nt":
        try:
            executable_path.chmod(executable_path.stat().st_mode | stat.S_IXUSR)
        except OSError as exc:
            raise PluginMarketplaceError(str(exc)) from exc
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
    if root.is_symlink():
        raise PluginMarketplaceError("plugin root cannot be a symbolic link")
    staging = root / f".marketplace-{entry.plugin_id}-{uuid.uuid4().hex}"
    prepared = root / f".prepared-{entry.plugin_id}-{uuid.uuid4().hex}"
    backup = root / f".backup-{entry.plugin_id}-{uuid.uuid4().hex}"
    target = root / entry.plugin_id
    if target.exists() and target.is_symlink():
        raise PluginMarketplaceError("installed plugin target cannot be a symbolic link")
    staging.mkdir(parents=True, exist_ok=False)
    moved_existing = False
    try:
        _extract_verified_zip(package, staging)
        source_root = _plugin_root(staging)
        _validate_package_root(source_root, entry)
        if source_root == staging:
            staging.replace(prepared)
        else:
            source_root.replace(prepared)
            shutil.rmtree(staging, ignore_errors=True)
        if target.exists():
            if not target.is_dir():
                raise PluginMarketplaceError("installed plugin target is not a directory")
            target.replace(backup)
            moved_existing = True
        prepared.replace(target)
        if moved_existing:
            shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(prepared, ignore_errors=True)
        if moved_existing and backup.exists() and not target.exists():
            with suppress(OSError):
                backup.replace(target)
        raise
    finally:
        if backup.exists() and target.exists():
            shutil.rmtree(backup, ignore_errors=True)
    return entry


def uninstall_plugin(engine_module, plugin_id: object) -> bool:
    clean = str(plugin_id or "").strip().lower()
    if not PLUGIN_ID_RE.fullmatch(clean):
        return False
    root = plugins_dir(engine_module)
    target = root / clean
    if not target.is_dir() or target.is_symlink():
        return False
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return False
    shutil.rmtree(target)
    return True


def marketplace_status(engine_module) -> dict[str, Any]:
    entries = load_marketplace(engine_module)
    root = plugins_dir(engine_module)
    installed = {
        item.name
        for item in root.iterdir()
        if item.is_dir() and not item.is_symlink() and PLUGIN_ID_RE.fullmatch(item.name)
    }
    return {
        "source": DEFAULT_MARKETPLACE_URL,
        "cached": bool(entries),
        "entries": [
            {**item.public_payload(), "installed": item.plugin_id in installed}
            for item in entries
        ],
    }


def run_plugin_marketplace_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    def build_package(*, marker: str = "v1", capabilities: tuple[str, ...] = ("metadata", "download")) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                PLUGIN_MANIFEST,
                json.dumps(
                    {
                        "id": "demo.plugin",
                        "name": "Demo",
                        "version": "1.2.3",
                        "executable": "demo.exe" if os.name == "nt" else "demo",
                        "capabilities": list(capabilities),
                    }
                ),
            )
            archive.writestr("demo.exe" if os.name == "nt" else "demo", marker)
        return output.getvalue()

    package = build_package()
    digest = hashlib.sha256(package).hexdigest()
    index = {
        "schema": 1,
        "plugins": [
            {
                "id": "demo.plugin",
                "name": "Demo",
                "version": "1.2.3",
                "packageUrl": "https://example.invalid/demo.zip",
                "sha256": digest,
                "capabilities": ["metadata", "download"],
                "platforms": ["any"],
            }
        ],
    }
    entries = parse_marketplace_index(index)
    assert len(entries) == 1 and entries[0].plugin_id == "demo.plugin"
    assert entries[0].capabilities == ("metadata", "download")
    assert _clean_entry({**index["plugins"][0], "packageUrl": "http://example.invalid/demo.zip"}) is None
    try:
        _safe_archive_member("../escape")
    except PluginMarketplaceError:
        pass
    else:
        raise AssertionError("unsafe plugin archive path was accepted")

    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../escape", "bad")
    with tempfile.TemporaryDirectory() as directory:
        try:
            _extract_verified_zip(unsafe.getvalue(), Path(directory) / "unsafe")
        except PluginMarketplaceError:
            pass
        else:
            raise AssertionError("unsafe plugin archive was extracted")

    symlink_zip = io.BytesIO()
    with zipfile.ZipFile(symlink_zip, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target")
    with tempfile.TemporaryDirectory() as directory:
        try:
            _extract_verified_zip(symlink_zip.getvalue(), Path(directory) / "unsafe-link")
        except PluginMarketplaceError:
            pass
        else:
            raise AssertionError("plugin archive symlink was extracted")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def data_dir() -> Path:
                return root / "data"

            @staticmethod
            def state_dir() -> Path:
                return root / "state"

        index_bytes = json.dumps(index).encode("utf-8")
        with patch("plugin_marketplace._fetch_bytes", return_value=index_bytes):
            assert refresh_marketplace(Engine)[0].plugin_id == "demo.plugin"
        assert load_marketplace(Engine)[0].sha256 == digest

        with patch("plugin_marketplace._fetch_bytes", return_value=package):
            installed = install_marketplace_plugin(Engine, "demo.plugin")
        assert installed.plugin_id == "demo.plugin"
        target = plugins_dir(Engine) / "demo.plugin"
        executable = target / ("demo.exe" if os.name == "nt" else "demo")
        assert executable.read_text(encoding="utf-8") == "v1"
        (target / "old-marker.txt").write_text("old", encoding="utf-8")

        replacement = build_package(marker="v2")
        replacement_digest = hashlib.sha256(replacement).hexdigest()
        replacement_index = {
            "schema": 1,
            "plugins": [{**index["plugins"][0], "sha256": replacement_digest}],
        }
        with patch("plugin_marketplace._fetch_bytes", return_value=json.dumps(replacement_index).encode("utf-8")):
            refresh_marketplace(Engine)
        with patch("plugin_marketplace._fetch_bytes", return_value=replacement):
            install_marketplace_plugin(Engine, "demo.plugin")
        assert executable.read_text(encoding="utf-8") == "v2"
        assert not (target / "old-marker.txt").exists()
        assert marketplace_status(Engine)["entries"][0]["installed"] is True

        bad_index = {"schema": 1, "plugins": [{**replacement_index["plugins"][0], "sha256": "0" * 64}]}
        with patch("plugin_marketplace._fetch_bytes", return_value=json.dumps(bad_index).encode("utf-8")):
            refresh_marketplace(Engine)
        with patch("plugin_marketplace._fetch_bytes", return_value=replacement):
            try:
                install_marketplace_plugin(Engine, "demo.plugin")
            except PluginMarketplaceError as exc:
                assert "SHA-256" in str(exc)
            else:
                raise AssertionError("plugin package with mismatched digest was accepted")

        capability_mismatch = build_package(capabilities=("metadata", "download", "ai"))
        capability_digest = hashlib.sha256(capability_mismatch).hexdigest()
        capability_index = {"schema": 1, "plugins": [{**index["plugins"][0], "sha256": capability_digest}]}
        with patch("plugin_marketplace._fetch_bytes", return_value=json.dumps(capability_index).encode("utf-8")):
            refresh_marketplace(Engine)
        with patch("plugin_marketplace._fetch_bytes", return_value=capability_mismatch):
            try:
                install_marketplace_plugin(Engine, "demo.plugin")
            except PluginMarketplaceError as exc:
                assert "capabilities" in str(exc)
            else:
                raise AssertionError("plugin capability escalation was accepted")

        assert uninstall_plugin(Engine, "demo.plugin") is True
        assert not target.exists()
