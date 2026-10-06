from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from runtime_storage import KNOWN_STATE_FILES, state_dir as runtime_state_dir

BACKUP_SCHEMA = "galaxy-local-engine-state-backup/v1"
MANIFEST_NAME = "manifest.json"
STATE_PREFIX = "state/"
CURRENT_STATE_FILES = tuple(dict.fromkeys((*KNOWN_STATE_FILES, "download-profiles.json")))
EXCLUDED_BACKUP_FILES = frozenset({"engine.log"})
SQLITE_SUFFIXES = frozenset({".sqlite", ".sqlite3", ".db"})
MAX_MEMBER_BYTES = 4 * 1024**3
MAX_TOTAL_BYTES = 16 * 1024**3
_CHUNK = 1024 * 1024


class StateBackupError(RuntimeError):
    pass


def backup_file_names() -> tuple[str, ...]:
    return tuple(name for name in CURRENT_STATE_FILES if name not in EXCLUDED_BACKUP_FILES)


def _regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _digest(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while True:
            block = f.read(_CHUNK)
            if not block:
                break
            h.update(block)
            size += len(block)
    return h.hexdigest(), size


def _snapshot(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() not in SQLITE_SUFFIXES:
        shutil.copy2(source, destination)
        return
    # sqlite3 online backup gives a consistent snapshot even while WAL pages are active.
    # A direct filesystem path is portable across Windows/macOS/Linux and avoids file: URI differences.
    with sqlite3.connect(str(source), timeout=10.0) as source_db:
        with sqlite3.connect(str(destination), timeout=10.0) as destination_db:
            source_db.backup(destination_db)


def create_state_backup(engine_module, archive_path: str | os.PathLike[str]) -> dict[str, object]:
    state_root = runtime_state_dir(engine_module)
    destination = Path(archive_path).expanduser()
    if not destination.name:
        raise StateBackupError("Backup path must name a file.")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="galaxy-state-backup-") as temporary_dir:
        stage = Path(temporary_dir) / "state"
        stage.mkdir()
        records: list[dict[str, object]] = []
        for name in backup_file_names():
            source = state_root / name
            if not source.exists():
                continue
            if not _regular(source):
                raise StateBackupError(f"Refusing to back up non-regular state file: {name}")
            staged = stage / name
            _snapshot(source, staged)
            sha256, size = _digest(staged)
            records.append({"name": name, "size": size, "sha256": sha256})

        manifest = {
            "schema": BACKUP_SCHEMA,
            "createdUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "completeSnapshot": True,
            "files": records,
        }
        fd, tmp_name = tempfile.mkstemp(
            dir=str(destination.parent), prefix=f".{destination.name}.", suffix=".tmp"
        )
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                for record in records:
                    name = str(record["name"])
                    archive.write(stage / name, STATE_PREFIX + name)
            os.replace(tmp, destination)
        except Exception:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

    return {
        "path": str(destination.resolve(strict=False)),
        "files": len(records),
        "bytes": sum(int(item["size"]) for item in records),
        "schema": BACKUP_SCHEMA,
    }


def _safe_archive_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/"):
        return False
    return all(part not in ("", ".", "..") for part in Path(name).parts)


def _manifest(archive: zipfile.ZipFile) -> dict[str, object]:
    infos = archive.infolist()
    if len(infos) > len(backup_file_names()) + 1:
        raise StateBackupError("Backup contains too many members.")
    seen: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        if name in seen:
            raise StateBackupError(f"Duplicate backup member: {name}")
        if info.is_dir() or not _safe_archive_name(name):
            raise StateBackupError(f"Unsafe or unexpected backup member: {name}")
        if info.file_size < 0 or info.file_size > MAX_MEMBER_BYTES:
            raise StateBackupError(f"Backup member is too large: {name}")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise StateBackupError("Backup expands beyond the allowed size limit.")
        seen.add(name)

    if MANIFEST_NAME not in seen:
        raise StateBackupError("Backup manifest is missing.")
    try:
        payload = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateBackupError("Backup manifest is invalid.") from exc
    if not isinstance(payload, dict) or payload.get("schema") != BACKUP_SCHEMA:
        raise StateBackupError("Backup schema is unsupported.")
    if payload.get("completeSnapshot") is not True:
        raise StateBackupError("Backup is not a complete state snapshot.")
    records = payload.get("files")
    if not isinstance(records, list):
        raise StateBackupError("Backup manifest file list is invalid.")

    allowed = set(backup_file_names())
    names: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise StateBackupError("Invalid backup file record.")
        name, size, sha256 = record.get("name"), record.get("size"), record.get("sha256")
        if not isinstance(name, str) or name not in allowed or name in names:
            raise StateBackupError(f"Unexpected backup state file: {name!r}")
        if not isinstance(size, int) or not 0 <= size <= MAX_MEMBER_BYTES:
            raise StateBackupError(f"Invalid backup size for {name}.")
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise StateBackupError(f"Invalid backup checksum for {name}.")
        if STATE_PREFIX + name not in seen:
            raise StateBackupError(f"Missing backup member: {STATE_PREFIX + name}")
        names.add(name)

    expected = {MANIFEST_NAME, *(STATE_PREFIX + name for name in names)}
    if seen != expected:
        raise StateBackupError(f"Backup contains unexpected members: {', '.join(sorted(seen - expected))}")
    return payload


def _validate_and_stage(path: Path, stage: Path | None = None) -> tuple[dict[str, object], dict[str, Path]]:
    try:
        archive = zipfile.ZipFile(path, "r", allowZip64=True)
    except (OSError, zipfile.BadZipFile) as exc:
        raise StateBackupError("Backup archive cannot be opened.") from exc

    staged: dict[str, Path] = {}
    with archive:
        payload = _manifest(archive)
        records = payload["files"]
        assert isinstance(records, list)
        for record in records:
            assert isinstance(record, dict)
            name = str(record["name"])
            info = archive.getinfo(STATE_PREFIX + name)
            if info.file_size != int(record["size"]):
                raise StateBackupError(f"Backup size mismatch for {name}.")
            h = hashlib.sha256()
            size = 0
            destination = stage / name if stage is not None else None
            output = destination.open("wb") if destination is not None else None
            try:
                with archive.open(info) as source:
                    while True:
                        block = source.read(_CHUNK)
                        if not block:
                            break
                        size += len(block)
                        if size > MAX_MEMBER_BYTES:
                            raise StateBackupError(f"Backup member exceeded size limit: {name}")
                        h.update(block)
                        if output is not None:
                            output.write(block)
            finally:
                if output is not None:
                    output.close()
            if size != int(record["size"]) or h.hexdigest().lower() != str(record["sha256"]).lower():
                raise StateBackupError(f"Backup checksum mismatch for {name}.")
            if destination is not None:
                staged[name] = destination
    return payload, staged


def validate_state_backup(archive_path: str | os.PathLike[str]) -> dict[str, object]:
    source = Path(archive_path).expanduser()
    payload, _ = _validate_and_stage(source)
    records = payload["files"]
    assert isinstance(records, list)
    return {
        "path": str(source.resolve(strict=False)),
        "files": len(records),
        "bytes": sum(int(item["size"]) for item in records if isinstance(item, dict)),
        "schema": BACKUP_SCHEMA,
        "valid": True,
    }


def restore_state_backup(engine_module, archive_path: str | os.PathLike[str]) -> dict[str, object]:
    source = Path(archive_path).expanduser()
    state_root = runtime_state_dir(engine_module)
    state_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="galaxy-state-restore-", dir=str(state_root.parent)) as temp_dir:
        root = Path(temp_dir)
        stage, rollback = root / "stage", root / "rollback"
        stage.mkdir()
        rollback.mkdir()
        payload, staged = _validate_and_stage(source, stage)

        existing: list[str] = []
        for name in backup_file_names():
            current = state_root / name
            if not current.exists():
                continue
            if not _regular(current):
                raise StateBackupError(f"Refusing to replace non-regular state file: {name}")
            shutil.copy2(current, rollback / name)
            existing.append(name)

        try:
            for name in backup_file_names():
                target = state_root / name
                if name in staged:
                    os.replace(staged[name], target)
                elif target.exists():
                    target.unlink()
        except Exception as exc:
            try:
                for name in backup_file_names():
                    target = state_root / name
                    if target.exists():
                        target.unlink()
                for name in existing:
                    os.replace(rollback / name, state_root / name)
            except Exception as rollback_exc:
                raise StateBackupError(
                    f"State restore failed and rollback also failed: {rollback_exc}"
                ) from exc
            raise StateBackupError("State restore failed; previous state was restored.") from exc

    records = payload["files"]
    assert isinstance(records, list)
    return {
        "path": str(source.resolve(strict=False)),
        "files": len(records),
        "bytes": sum(int(item["size"]) for item in records if isinstance(item, dict)),
        "schema": BACKUP_SCHEMA,
        "restored": True,
    }


def run_state_backup_self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        state.mkdir()
        (state / "workspace-options.json").write_text('{"historyEnabled":true}', encoding="utf-8")
        (state / "download-profiles.json").write_text('{"version":1,"profiles":[]}', encoding="utf-8")
        (state / "telegram-upload-secret.json").write_text('{"botToken":"NEVER"}', encoding="utf-8")
        (state / "unknown-secret.txt").write_text("NEVER", encoding="utf-8")
        (state / "engine.log").write_text("diagnostic", encoding="utf-8")
        with sqlite3.connect(str(state / "media-library.sqlite3")) as db:
            db.execute("create table item(value text)")
            db.execute("insert into item values ('before')")
            db.commit()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root
            @staticmethod
            def state_dir() -> Path:
                return state

        backup = root / "backup.galaxy-state.zip"
        assert create_state_backup(Engine, backup)["files"] == 3
        assert validate_state_backup(backup)["valid"] is True
        with zipfile.ZipFile(backup) as archive:
            members = set(archive.namelist())
        assert STATE_PREFIX + "download-profiles.json" in members
        assert STATE_PREFIX + "engine.log" not in members
        assert STATE_PREFIX + "telegram-upload-secret.json" not in members
        assert STATE_PREFIX + "unknown-secret.txt" not in members

        (state / "workspace-options.json").write_text('{"historyEnabled":false}', encoding="utf-8")
        (state / "download-profiles.json").unlink()
        (state / "desktop-features.json").write_text("{}", encoding="utf-8")
        with sqlite3.connect(str(state / "media-library.sqlite3")) as db:
            db.execute("update item set value='after'")
            db.commit()

        assert restore_state_backup(Engine, backup)["restored"] is True
        assert (state / "workspace-options.json").read_text(encoding="utf-8") == '{"historyEnabled":true}'
        assert (state / "download-profiles.json").exists()
        assert not (state / "desktop-features.json").exists()
        assert (state / "telegram-upload-secret.json").read_text(encoding="utf-8") == '{"botToken":"NEVER"}'
        assert (state / "unknown-secret.txt").read_text(encoding="utf-8") == "NEVER"
        assert (state / "engine.log").read_text(encoding="utf-8") == "diagnostic"
        with sqlite3.connect(str(state / "media-library.sqlite3")) as db:
            assert db.execute("select value from item").fetchone()[0] == "before"

        corrupt = root / "corrupt.zip"
        shutil.copy2(backup, corrupt)
        with zipfile.ZipFile(corrupt, "a") as archive:
            archive.writestr("unexpected.txt", "no")
        try:
            validate_state_backup(corrupt)
        except StateBackupError:
            pass
        else:
            raise AssertionError("Unexpected archive member was not rejected.")
