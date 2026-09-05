from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
CHROME_MANIFEST = ROOT / "manifest.json"
FIREFOX_MANIFEST = ROOT / "manifest.firefox.json"
RUNTIME_FILES = (
    "background.js",
    "candidate-browser.js",
    "content.js",
    "dynamic-scan.js",
    "element-actions.js",
    "media-core.js",
    "page-probe.js",
)
DEFAULT_OUTPUT = ROOT / "dist" / "GalaxyMediaCapture-Firefox.xpi"


class FirefoxPackageError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise FirefoxPackageError(f"invalid JSON manifest: {path.name}") from exc
    if not isinstance(payload, dict):
        raise FirefoxPackageError(f"manifest must be an object: {path.name}")
    return payload


def _version_tuple(value: object) -> tuple[int, ...]:
    parts = str(value or "").strip().split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError as exc:
        raise FirefoxPackageError(f"invalid Firefox minimum version: {value}") from exc


def validate_manifests(chrome: dict[str, Any], firefox: dict[str, Any]) -> None:
    for key in ("manifest_version", "name", "version", "description", "permissions", "host_permissions", "content_scripts", "action"):
        if chrome.get(key) != firefox.get(key):
            raise FirefoxPackageError(f"Firefox manifest drifted from shared Chrome field: {key}")

    chrome_background = chrome.get("background") or {}
    firefox_background = firefox.get("background") or {}
    if chrome_background.get("service_worker") != "background.js":
        raise FirefoxPackageError("Chrome manifest must keep background.service_worker=background.js")
    if firefox_background.get("service_worker"):
        raise FirefoxPackageError("Firefox manifest must not declare background.service_worker")
    if firefox_background.get("scripts") != ["background.js"] or firefox_background.get("type") != "module":
        raise FirefoxPackageError("Firefox background must use the shared background.js module via background.scripts")

    gecko = ((firefox.get("browser_specific_settings") or {}).get("gecko") or {})
    extension_id = str(gecko.get("id") or "").strip()
    if "@" not in extension_id or len(extension_id) > 80:
        raise FirefoxPackageError("Firefox manifest requires a stable browser_specific_settings.gecko.id")
    if _version_tuple(gecko.get("strict_min_version")) < (128, 0):
        raise FirefoxPackageError("Firefox 128+ is required for content_scripts.world=MAIN")
    required_collection = ((gecko.get("data_collection_permissions") or {}).get("required") or [])
    if required_collection != ["none"]:
        raise FirefoxPackageError("Firefox AMO metadata must explicitly declare no required data collection")

    referenced = {"background.js"}
    for entry in firefox.get("content_scripts") or []:
        if isinstance(entry, dict):
            referenced.update(str(item) for item in entry.get("js") or [])
    missing = sorted(referenced - set(RUNTIME_FILES))
    if missing:
        raise FirefoxPackageError(f"Firefox manifest references unpackaged scripts: {', '.join(missing)}")


def firefox_source(name: str) -> bytes:
    path = ROOT / name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FirefoxPackageError(f"missing runtime source: {name}") from exc
    # Firefox exposes Promise-first WebExtension APIs through browser.*. The
    # shared Chromium source stays unchanged; only the Firefox artifact swaps
    # the API namespace. Protocol strings such as chrome-extension: are not
    # touched because the transform is restricted to the exact `chrome.` token.
    rendered = text.replace("chrome.", "browser.").replace("Chrome 下载", "浏览器下载")
    if "chrome." in rendered:
        raise FirefoxPackageError(f"unconverted Chrome API namespace remains in {name}")
    return rendered.encode("utf-8")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build(output: Path) -> Path:
    chrome = _load_json(CHROME_MANIFEST)
    firefox = _load_json(FIREFOX_MANIFEST)
    validate_manifests(chrome, firefox)

    output = output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    manifest_bytes = (json.dumps(firefox, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(_zip_info("manifest.json"), manifest_bytes)
        for name in RUNTIME_FILES:
            archive.writestr(_zip_info(name), firefox_source(name))

    expected = {"manifest.json", *RUNTIME_FILES}
    with zipfile.ZipFile(output, "r") as archive:
        names = set(archive.namelist())
        if names != expected:
            raise FirefoxPackageError(f"unexpected Firefox package contents: {sorted(names ^ expected)}")
        packaged_manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        validate_manifests(chrome, packaged_manifest)
        for name in RUNTIME_FILES:
            source = archive.read(name).decode("utf-8")
            if "chrome." in source:
                raise FirefoxPackageError(f"packaged Firefox source still uses chrome.*: {name}")

    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Firefox Galaxy Media Capture XPI from the shared extension source tree.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Target .xpi path")
    args = parser.parse_args()
    target = build(Path(args.output))
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
