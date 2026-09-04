from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from platform_paths import resolve_platform_paths
from plugin_host import (
    ALLOWED_CAPABILITIES,
    PLUGIN_ID_RE,
    PluginHostError,
    get_plugin,
    plugin_enabled,
    plugin_host_status,
    set_plugin_enabled,
)
from plugin_marketplace import (
    DEFAULT_MARKETPLACE_URL,
    MarketplaceEntry,
    PluginMarketplaceError,
    install_marketplace_plugin,
    load_marketplace,
    refresh_marketplace,
    uninstall_plugin,
)

_WINDOWS_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s\"'<>|]+")
_POSIX_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_:])/(?:home|Users|root|tmp|var|mnt|srv|opt|private)(?:/[^\s\"'<>|,;:]+)+"
)


class HeadlessPluginApiError(RuntimeError):
    status = 400
    code = "PLUGIN_INVALID_REQUEST"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class HeadlessPluginNotFoundError(HeadlessPluginApiError):
    status = 404
    code = "PLUGIN_NOT_FOUND"


class HeadlessPluginConflictError(HeadlessPluginApiError):
    status = 409
    code = "PLUGIN_CONFLICT"


def _safe_directory(value: Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    if raw.exists() and raw.is_symlink():
        raise HeadlessPluginApiError(f"{label} cannot be a symbolic link")
    resolved = raw.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _clean_plugin_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not PLUGIN_ID_RE.fullmatch(clean):
        raise HeadlessPluginApiError("invalid plugin id", code="PLUGIN_ID_INVALID")
    return clean


def _safe_detail(value: object, *, roots: Iterable[Path] = ()) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    candidates: set[str] = set()
    for root in (*tuple(roots), Path.home()):
        try:
            resolved = Path(root).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        candidates.add(str(resolved))
        candidates.add(resolved.as_posix())
    for candidate in sorted((item for item in candidates if item), key=len, reverse=True):
        text = text.replace(candidate, "[LOCAL_PATH]")
    text = _WINDOWS_PATH_RE.sub("[LOCAL_PATH]", text)
    text = _POSIX_PATH_RE.sub("[LOCAL_PATH]", text)
    return text[:1200]


def _translate_error(exc: Exception, *, roots: Iterable[Path] = ()) -> HeadlessPluginApiError:
    if isinstance(exc, HeadlessPluginApiError):
        return exc
    detail = _safe_detail(exc, roots=roots)
    lowered = detail.lower()
    if isinstance(exc, (PluginHostError, PluginMarketplaceError)):
        if "not found" in lowered or "not present" in lowered:
            return HeadlessPluginNotFoundError(detail or "plugin not found")
        if "disabled" in lowered:
            return HeadlessPluginConflictError(detail or "plugin is disabled", code="PLUGIN_DISABLED")
        if "sha-256" in lowered or "identity" in lowered or "capabilities do not match" in lowered:
            return HeadlessPluginConflictError(
                detail or "plugin package verification failed",
                code="PLUGIN_PACKAGE_MISMATCH",
            )
        return HeadlessPluginApiError(detail or "plugin operation failed")
    return HeadlessPluginApiError(detail or "plugin operation failed")


@dataclass(frozen=True)
class HeadlessPluginContext:
    program_path: Path
    data_path: Path
    state_path: Path
    downloads_path: Path

    def app_dir(self) -> Path:
        return self.program_path

    def data_dir(self) -> Path:
        self.data_path.mkdir(parents=True, exist_ok=True)
        return self.data_path

    def state_dir(self) -> Path:
        self.state_path.mkdir(parents=True, exist_ok=True)
        return self.state_path

    def default_download_dir(self) -> Path:
        self.downloads_path.mkdir(parents=True, exist_ok=True)
        return self.downloads_path


def build_headless_plugin_context(
    download_root: Path,
    *,
    program_dir: Path | None = None,
    data_dir: Path | None = None,
    state_dir: Path | None = None,
) -> HeadlessPluginContext:
    program = Path(program_dir or Path(__file__).resolve().parent).expanduser().resolve(strict=False)
    paths = resolve_platform_paths(program_dir=program)
    data = _safe_directory(Path(data_dir or paths.data_dir), label="plugin data directory")
    state = _safe_directory(Path(state_dir or paths.state_dir), label="plugin state directory")
    downloads = _safe_directory(Path(download_root), label="plugin download root")
    return HeadlessPluginContext(program, data, state, downloads)


def _version_key(value: object) -> tuple[int, int, int, int]:
    text = str(value or "").strip()
    base = text.split("+", 1)[0]
    core, sep, suffix = base.partition("-")
    parts = core.split(".")
    if len(parts) != 3:
        return (0, 0, 0, 0)
    try:
        major, minor, patch = (max(0, int(item)) for item in parts)
    except ValueError:
        return (0, 0, 0, 0)
    return (major, minor, patch, 1 if not sep or not suffix else 0)


def _public_marketplace_entry(
    entry: MarketplaceEntry,
    *,
    installed_version: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    package_host = ""
    try:
        package_host = str(urlsplit(entry.package_url).hostname or "")[:160]
    except ValueError:
        package_host = ""
    installed = bool(installed_version)
    return {
        "id": entry.plugin_id,
        "name": entry.name,
        "version": entry.version,
        "capabilities": list(entry.capabilities),
        "description": entry.description,
        "platforms": list(entry.platforms),
        "sha256": entry.sha256,
        "packageHost": package_host,
        "installed": installed,
        "installedVersion": installed_version,
        "enabled": bool(enabled) if installed else False,
        "updateAvailable": bool(
            installed
            and installed_version != entry.version
            and _version_key(entry.version) >= _version_key(installed_version)
        ),
    }


class HeadlessPluginApi:
    def __init__(
        self,
        download_root: Path,
        *,
        context: HeadlessPluginContext | None = None,
        program_dir: Path | None = None,
        data_dir: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.context = context or build_headless_plugin_context(
            download_root,
            program_dir=program_dir,
            data_dir=data_dir,
            state_dir=state_dir,
        )

    @property
    def _roots(self) -> tuple[Path, ...]:
        return (
            self.context.program_path,
            self.context.data_path,
            self.context.state_path,
            self.context.downloads_path,
        )

    def status(self) -> dict[str, Any]:
        try:
            status = plugin_host_status(self.context)
            installed = status.get("plugins") if isinstance(status, dict) else []
            marketplace = load_marketplace(self.context)
        except Exception as exc:
            raise _translate_error(exc, roots=self._roots) from exc
        installed_rows = [dict(item) for item in installed or [] if isinstance(item, dict)]
        by_id = {str(item.get("id") or ""): item for item in installed_rows}
        market_rows = [
            _public_marketplace_entry(
                entry,
                installed_version=str(by_id.get(entry.plugin_id, {}).get("version") or ""),
                enabled=bool(by_id.get(entry.plugin_id, {}).get("enabled", True)),
            )
            for entry in marketplace
        ]
        update_count = sum(1 for item in market_rows if item["updateAvailable"])
        return {
            "protocol": 2,
            "capabilities": sorted(ALLOWED_CAPABILITIES),
            "plugins": installed_rows,
            "marketplaceCached": bool(marketplace),
            "marketplaceSource": DEFAULT_MARKETPLACE_URL,
            "updatesAvailable": update_count,
        }

    def plugin_detail(self, plugin_id: object) -> dict[str, Any]:
        clean = _clean_plugin_id(plugin_id)
        try:
            manifest = get_plugin(self.context, clean, include_disabled=True)
            if manifest is None:
                raise HeadlessPluginNotFoundError("plugin not found")
            enabled = plugin_enabled(self.context, clean)
            marketplace = next((item for item in load_marketplace(self.context) if item.plugin_id == clean), None)
        except Exception as exc:
            raise _translate_error(exc, roots=self._roots) from exc
        result: dict[str, Any] = {"plugin": manifest.public_payload(enabled=enabled)}
        if marketplace is not None:
            result["marketplace"] = _public_marketplace_entry(
                marketplace,
                installed_version=manifest.version,
                enabled=enabled,
            )
        return result

    def set_enabled(self, plugin_id: object, enabled: object) -> dict[str, Any]:
        clean = _clean_plugin_id(plugin_id)
        if not isinstance(enabled, bool):
            raise HeadlessPluginApiError("enabled must be a boolean", code="PLUGIN_ENABLED_INVALID")
        try:
            value = set_plugin_enabled(self.context, clean, enabled)
            manifest = get_plugin(self.context, clean, include_disabled=True)
            if manifest is None:
                raise HeadlessPluginNotFoundError("plugin not found")
            return {"plugin": manifest.public_payload(enabled=value)}
        except Exception as exc:
            raise _translate_error(exc, roots=self._roots) from exc

    def marketplace(self) -> dict[str, Any]:
        try:
            entries = load_marketplace(self.context)
            status = plugin_host_status(self.context)
        except Exception as exc:
            raise _translate_error(exc, roots=self._roots) from exc
        installed_rows = status.get("plugins") if isinstance(status, dict) else []
        by_id = {
            str(item.get("id") or ""): item
            for item in installed_rows or []
            if isinstance(item, dict)
        }
        return {
            "source": DEFAULT_MARKETPLACE_URL,
            "cached": bool(entries),
            "entries": [
                _public_marketplace_entry(
                    entry,
                    installed_version=str(by_id.get(entry.plugin_id, {}).get("version") or ""),
                    enabled=bool(by_id.get(entry.plugin_id, {}).get("enabled", True)),
                )
                for entry in entries
            ],
        }

    def refresh_marketplace(self) -> dict[str, Any]:
        try:
            entries = refresh_marketplace(self.context)
        except Exception as exc:
            raise _translate_error(exc, roots=self._roots) from exc
        return {
            "source": DEFAULT_MARKETPLACE_URL,
            "refreshed": True,
            "count": len(entries),
            "entries": [_public_marketplace_entry(item) for item in entries],
        }

    def install(self, plugin_id: object) -> dict[str, Any]:
        clean = _clean_plugin_id(plugin_id)
        try:
            entry = install_marketplace_plugin(self.context, clean)
            manifest = get_plugin(self.context, clean, include_disabled=True)
            if manifest is None:
                raise HeadlessPluginConflictError(
                    "plugin package installed but manifest was not discoverable",
                    code="PLUGIN_INSTALL_INCOMPLETE",
                )
            enabled = plugin_enabled(self.context, clean)
        except Exception as exc:
            raise _translate_error(exc, roots=self._roots) from exc
        return {
            "plugin": manifest.public_payload(enabled=enabled),
            "marketplace": _public_marketplace_entry(
                entry,
                installed_version=manifest.version,
                enabled=enabled,
            ),
        }

    def update(self, plugin_id: object) -> dict[str, Any]:
        clean = _clean_plugin_id(plugin_id)
        try:
            current = get_plugin(self.context, clean, include_disabled=True)
            if current is None:
                raise HeadlessPluginNotFoundError("plugin not found")
            entry = next((item for item in load_marketplace(self.context) if item.plugin_id == clean), None)
            if entry is None:
                raise HeadlessPluginNotFoundError("plugin is not present in the cached marketplace index")
            if current.version == entry.version:
                return {
                    "plugin": current.public_payload(enabled=plugin_enabled(self.context, clean)),
                    "updated": False,
                    "reason": "already-current",
                }
            if _version_key(entry.version) < _version_key(current.version):
                raise HeadlessPluginConflictError(
                    "marketplace version is older than the installed plugin",
                    code="PLUGIN_DOWNGRADE_BLOCKED",
                )
            installed = install_marketplace_plugin(self.context, clean)
            manifest = get_plugin(self.context, clean, include_disabled=True)
            if manifest is None:
                raise HeadlessPluginConflictError(
                    "plugin update completed but manifest was not discoverable",
                    code="PLUGIN_UPDATE_INCOMPLETE",
                )
            enabled = plugin_enabled(self.context, clean)
        except Exception as exc:
            raise _translate_error(exc, roots=self._roots) from exc
        return {
            "plugin": manifest.public_payload(enabled=enabled),
            "marketplace": _public_marketplace_entry(
                installed,
                installed_version=manifest.version,
                enabled=enabled,
            ),
            "updated": True,
        }

    def remove(self, plugin_id: object) -> dict[str, Any]:
        clean = _clean_plugin_id(plugin_id)
        try:
            manifest = get_plugin(self.context, clean, include_disabled=True)
            if manifest is None:
                raise HeadlessPluginNotFoundError("plugin not found")
            removed = uninstall_plugin(self.context, clean)
            if not removed:
                raise HeadlessPluginConflictError("plugin could not be removed", code="PLUGIN_REMOVE_FAILED")
        except Exception as exc:
            raise _translate_error(exc, roots=self._roots) from exc
        return {"pluginId": clean, "removed": True}


def run_headless_plugin_api_self_test() -> None:
    import json
    import os
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        context = HeadlessPluginContext(
            program_path=root,
            data_path=root / "data",
            state_path=root / "state",
            downloads_path=root / "downloads",
        )
        context.data_dir()
        context.state_dir()
        context.default_download_dir()
        plugin_root = context.data_dir() / "plugins" / "demo.plugin"
        plugin_root.mkdir(parents=True)
        executable = "demo.exe" if os.name == "nt" else "demo"
        (plugin_root / executable).write_bytes(b"demo")
        (plugin_root / "galaxy-plugin.json").write_text(
            json.dumps(
                {
                    "id": "demo.plugin",
                    "name": "Demo Plugin",
                    "version": "1.0.0",
                    "executable": executable,
                    "capabilities": ["metadata", "download"],
                }
            ),
            encoding="utf-8",
        )
        api = HeadlessPluginApi(root / "downloads", context=context)
        status = api.status()
        assert status["plugins"][0]["id"] == "demo.plugin"
        assert "root" not in status["plugins"][0] and "executable" not in status["plugins"][0]
        assert api.set_enabled("demo.plugin", False)["plugin"]["enabled"] is False
        assert api.set_enabled("demo.plugin", True)["plugin"]["enabled"] is True

        entry = MarketplaceEntry(
            plugin_id="demo.plugin",
            name="Demo Plugin",
            version="1.1.0",
            package_url="https://packages.example.test/demo.zip?token=must-not-leak",
            sha256="a" * 64,
            capabilities=("metadata", "download"),
            description="Demo",
            platforms=("any",),
        )
        with patch("headless_plugin_api.load_marketplace", return_value=(entry,)):
            market = api.marketplace()
            row = market["entries"][0]
            assert row["updateAvailable"] is True
            serialized = json.dumps(market)
            assert "must-not-leak" not in serialized
            assert "packageUrl" not in serialized

        with patch("headless_plugin_api.refresh_marketplace", return_value=(entry,)):
            refreshed = api.refresh_marketplace()
            assert refreshed["count"] == 1
            assert "must-not-leak" not in json.dumps(refreshed)

        try:
            api.plugin_detail("../escape")
        except HeadlessPluginApiError as exc:
            assert exc.code == "PLUGIN_ID_INVALID"
        else:
            raise AssertionError("invalid plugin id was accepted")

        with patch(
            "headless_plugin_api.refresh_marketplace",
            side_effect=PluginMarketplaceError(str(root / "private" / "registry.json")),
        ):
            try:
                api.refresh_marketplace()
            except HeadlessPluginApiError as exc:
                assert str(root) not in str(exc)
                assert "[LOCAL_PATH]" in str(exc)
            else:
                raise AssertionError("path-leaking marketplace error was not rejected")


if __name__ == "__main__":
    run_headless_plugin_api_self_test()
    print("Headless plugin API self-test passed")
