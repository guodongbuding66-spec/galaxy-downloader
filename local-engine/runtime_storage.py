from __future__ import annotations

import json
import shutil
import threading
from contextlib import suppress
from pathlib import Path

KNOWN_STATE_FILES = (
    "workspace-options.json",
    "desktop-features.json",
    "download-history.json",
    "download-archive.txt",
    "resume-jobs.json",
    "media-library.sqlite3",
    "transcripts.sqlite3",
    "learning.sqlite3",
    "reader.sqlite3",
    "music-library.sqlite3",
    "subscriptions.json",
    "ai-models.json",
    "asr-settings.json",
    "ai-prompts.json",
    "ai-providers.json",
    "ai-history.sqlite3",
    "engine.log",
)
LEGACY_V1_STATE_FILES = frozenset(
    {
        "workspace-options.json",
        "desktop-features.json",
        "download-history.json",
        "download-archive.txt",
        "resume-jobs.json",
        "media-library.sqlite3",
        "subscriptions.json",
        "engine.log",
    }
)
LEGACY_STATE_IMPORT_MARKER = ".portable-state-imported-v1"
STATE_IMPORT_LEDGER = ".portable-state-imported.json"
STATE_IMPORT_LEDGER_VERSION = 1
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


def _load_imported_files(target: Path) -> set[str]:
    ledger = target / STATE_IMPORT_LEDGER
    try:
        payload = json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        payload = None
    if isinstance(payload, dict) and payload.get("version") == STATE_IMPORT_LEDGER_VERSION:
        values = payload.get("files")
        if isinstance(values, list):
            return {str(item) for item in values if str(item) in KNOWN_STATE_FILES}
    if (target / LEGACY_STATE_IMPORT_MARKER).is_file():
        return set(LEGACY_V1_STATE_FILES)
    return set()


def _write_imported_files(target: Path, imported: set[str]) -> None:
    ledger = target / STATE_IMPORT_LEDGER
    temporary = ledger.with_suffix(".tmp")
    payload = {
        "version": STATE_IMPORT_LEDGER_VERSION,
        "files": [name for name in KNOWN_STATE_FILES if name in imported],
    }
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(ledger)
    except OSError:
        with suppress(OSError):
            temporary.unlink()
        raise


def _import_legacy_state_once(engine_module, target: Path) -> None:
    legacy = _legacy_state_dir(engine_module)
    if _same_path(legacy, target):
        return
    with _STATE_MIGRATION_LOCK:
        target.mkdir(parents=True, exist_ok=True)
        imported = _load_imported_files(target)
        pending = [name for name in KNOWN_STATE_FILES if name not in imported]
        if not pending:
            return
        changed = False
        for name in pending:
            source = legacy / name
            destination = target / name
            if destination.exists() or not source.is_file() or source.is_symlink():
                imported.add(name)
                changed = True
                continue
            try:
                shutil.copy2(source, destination)
            except OSError:
                continue
            imported.add(name)
            changed = True
        if changed:
            try:
                _write_imported_files(target, imported)
            except OSError:
                return


def state_dir(engine_module) -> Path:
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
        (legacy / "transcripts.sqlite3").write_bytes(b"transcripts")
        (legacy / "learning.sqlite3").write_bytes(b"learning")
        (legacy / "reader.sqlite3").write_bytes(b"reader")
        (legacy / "music-library.sqlite3").write_bytes(b"music")
        (legacy / "subscriptions.json").write_text('{"version":1,"subscriptions":[]}', encoding="utf-8")
        (legacy / "ai-models.json").write_text('{"whisperModel":"small","summaryModel":"qwen3:4b"}', encoding="utf-8")
        (legacy / "asr-settings.json").write_text('{"version":1,"provider":"faster-whisper","profile":"accurate"}', encoding="utf-8")
        (legacy / "ai-prompts.json").write_text('{"version":1,"prompts":[]}', encoding="utf-8")
        (legacy / "ai-providers.json").write_text('{"version":1,"providers":[]}', encoding="utf-8")
        (legacy / "ai-history.sqlite3").write_bytes(b"ai-history")
        (legacy / "unknown-secret.txt").write_text("do-not-copy", encoding="utf-8")
        installed.mkdir(parents=True)
        (installed / "workspace-options.json").write_text('{"historyEnabled": true}', encoding="utf-8")
        (installed / LEGACY_STATE_IMPORT_MARKER).write_text("1\n", encoding="utf-8")

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
        assert not (installed / "desktop-features.json").exists()
        assert not (installed / "download-history.json").exists()
        assert not (installed / "media-library.sqlite3").exists()
        assert not (installed / "subscriptions.json").exists()
        assert (installed / "transcripts.sqlite3").read_bytes() == b"transcripts"
        assert (installed / "learning.sqlite3").read_bytes() == b"learning"
        assert (installed / "reader.sqlite3").read_bytes() == b"reader"
        assert (installed / "music-library.sqlite3").read_bytes() == b"music"
        assert (installed / "ai-models.json").read_text(encoding="utf-8") == '{"whisperModel":"small","summaryModel":"qwen3:4b"}'
        assert (installed / "asr-settings.json").read_text(encoding="utf-8") == '{"version":1,"provider":"faster-whisper","profile":"accurate"}'
        assert (installed / "ai-prompts.json").read_text(encoding="utf-8") == '{"version":1,"prompts":[]}'
        assert (installed / "ai-providers.json").read_text(encoding="utf-8") == '{"version":1,"providers":[]}'
        assert (installed / "ai-history.sqlite3").read_bytes() == b"ai-history"
        assert not (installed / "unknown-secret.txt").exists()
        ledger = json.loads((installed / STATE_IMPORT_LEDGER).read_text(encoding="utf-8"))
        assert ledger["version"] == STATE_IMPORT_LEDGER_VERSION
        assert set(ledger["files"]) == set(KNOWN_STATE_FILES)

        (installed / "ai-models.json").unlink()
        state_dir(InstalledEngine)
        assert not (installed / "ai-models.json").exists()

        class PortableEngine:
            @staticmethod
            def app_dir() -> Path:
                return program

        portable = state_dir(PortableEngine)
        assert portable == legacy
        assert not (legacy / STATE_IMPORT_LEDGER).exists()
