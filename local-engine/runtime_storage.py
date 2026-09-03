from __future__ import annotations

import shutil
import threading
from pathlib import Path

KNOWN_STATE_FILES = (
    "workspace-options.json",
    "desktop-features.json",
    "download-history.json",
    "download-archive.txt",
    "resume-jobs.json",
    "media-library.sqlite3",
    "subscriptions.json",
    "engine.log",
)
STATE_IMPORT_MARKER = ".portable-state-imported-v1"
_STATE_MIGRATION_LOCK = threading.RLock()


def _legacy_state_dir(engine_module) -> Path:
    return engine_module.app_dir() / "state"


def _configured_state_dir(engine_module) -> Path:
    accessor = getattr(engine_module, "state_dir", None)
    if callable(accessor):
        return Path(accessor())
    target = _legacy_state_dir(engine_module)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except (OSError, RuntimeError):
        return left.absolute() == right.absolute()


def _import_legacy_state_once(engine_module, target: Path) -> None:
    legacy = _legacy_state_dir(engine_module)
    if _same_path(legacy, target):
        return

    marker = target / STATE_IMPORT_MARKER
    if marker.exists():
        return

    with _STATE_MIGRATION_LOCK:
        if marker.exists():
            return
        target.mkdir(parents=True, exist_ok=True)

        success = True
        if legacy.is_dir():
            for name in KNOWN_STATE_FILES:
                source = legacy / name
                destination = target / name
                if destination.exists() or not source.is_file() or source.is_symlink():
                    continue
                try:
                    shutil.copy2(source, destination)
                except OSError:
                    success = False

        if not success:
            return

        temporary = marker.with_suffix(".tmp")
        try:
            temporary.write_text("1\n", encoding="utf-8")
            temporary.replace(marker)
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass


def state_dir(engine_module) -> Path:
    """Return Galaxy's mutable state directory with one-time legacy import.

    Portable mode resolves to the historical ``app_dir()/state`` location and
    therefore performs no migration. Installed mode resolves to the per-user
    runtime state directory. On its first use, known state files are copied from
    the legacy portable directory without overwriting anything already present.

    The legacy files are intentionally retained so users can roll back to a
    portable build without data loss. A marker prevents a later user deletion
    (for example clearing history) from being silently undone by another import.
    """
    target = _configured_state_dir(engine_module)
    target.mkdir(parents=True, exist_ok=True)
    _import_legacy_state_once(engine_module, target)
    return target


def run_runtime_storage_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        program = root / "program"
        legacy = program / "state"
        installed = root / "installed" / "state"
        legacy.mkdir(parents=True)
        (legacy / "workspace-options.json").write_text('{"historyEnabled": false}', encoding="utf-8")
        (legacy / "desktop-features.json").write_text('{"clipboardMonitorEnabled": true}', encoding="utf-8")
        (legacy / "download-history.json").write_text('[{"id":"legacy"}]', encoding="utf-8")
        (legacy / "media-library.sqlite3").write_bytes(b"library")
        (legacy / "subscriptions.json").write_text('{"version":1,"subscriptions":[]}', encoding="utf-8")
        (legacy / "unknown-secret.txt").write_text("do-not-copy", encoding="utf-8")
        installed.mkdir(parents=True)
        (installed / "workspace-options.json").write_text('{"historyEnabled": true}', encoding="utf-8")

        class InstalledEngine:
            @staticmethod
            def app_dir() -> Path:
                return program

            @staticmethod
            def state_dir() -> Path:
                installed.mkdir(parents=True, exist_ok=True)
                return installed

        target = state_dir(InstalledEngine)
        assert target == installed
        assert (installed / "workspace-options.json").read_text(encoding="utf-8") == '{"historyEnabled": true}'
        assert (installed / "desktop-features.json").read_text(encoding="utf-8") == '{"clipboardMonitorEnabled": true}'
        assert (installed / "download-history.json").read_text(encoding="utf-8") == '[{"id":"legacy"}]'
        assert (installed / "media-library.sqlite3").read_bytes() == b"library"
        assert (installed / "subscriptions.json").read_text(encoding="utf-8") == '{"version":1,"subscriptions":[]}'
        assert not (installed / "unknown-secret.txt").exists()
        assert (installed / STATE_IMPORT_MARKER).is_file()

        (installed / "download-history.json").unlink()
        state_dir(InstalledEngine)
        assert not (installed / "download-history.json").exists()

        class PortableEngine:
            @staticmethod
            def app_dir() -> Path:
                return program

        portable = state_dir(PortableEngine)
        assert portable == legacy
        assert not (legacy / STATE_IMPORT_MARKER).exists()
