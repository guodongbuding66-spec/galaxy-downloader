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
EXCLUDED_BACKUP_FILES = frozenset({"engine.log"})
CURRENT_STATE_FILES = tuple(dict.fromkeys((*KNOWN_STATE_FILES, "download-profiles.json")))
SQLITE_SUFFIXES = frozenset({".sqlite", ".sqlite3", ".db"})
MAX_MEMBER_BYTES = 4 * 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024 * 1024
_COPY_CHUNK = 1024 * 1024


class StateBackupError(RuntimeError):
    pass


def backup_file_names() -> tuple[str, ...]:
    return tuple(name for name in CURRENT_STATE_FILES if name not in EXCLUDED_BACKUP_FILES)


def _sha256_path(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_COPY_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _is_regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _snapshot_sqlite(source: Path, destination: Path) -> None:
    source_uri = source.resolve(strict=True).as_uri() + "?mode=ro"
    with sqlite3.connect(source_uri, uri=True, timeout=10.0) as source_db:
        with sqlite3.connect(destination) as destination_db:
            source_db.backup(destination_db)


def _snapshot_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in SQLITE_SUFFIXES:
        _snapshot_sqlite(source, destination)
    else:
        shutil.copy2(source, destination)


def create_state_backup(engine_module, archive_path: str | os.PathLike[str]) -> dict[str, object]:
    source_root = runtime_state_dir(engine_module)
    destination = Path(archive_path).expanduser()
    if not destination.name:
        raise StateBackupError("Backup path must name a file.")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="galaxy-state-backup-") as temporary_dir:
        staging = Path(temporary_dir) / "state"
        staging.mkdir()
        records: list[dict[str, object]] = []
        for name in backup_file_names():
            source = source_root / name
            if not source.exists():
                continue
            if not _is_regular(source):
                raise StateBackupError(f"Refusing to back up non-regular state file: {name}")
            staged = staging / name
            _snapshot_file(source, staged)
            sha256, size = _sha256_path(staged)
            records.append({"name": name, "sha256": sha256, "size": size})

        manifest = {
            "schema": BACKUP_SCHEMA,
            "createdUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "completeSnapshot": True,
            "files": records,
        }
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                for record in records:
                    name = str(record["name"])
                    archive.write(staging / name, STATE_PREFIX + name)
            os.replace(temporary, destination)
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    return {
        "path": str(destination.resolve(strict=False)),
        "files": len(records),
        "bytes": sum(int(record["size"]) for record in records),
        "schema": BACKUP_SCHEMA,
    }


def _safe_member_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/") or name.startswith("../"):
        return False
    return all(part not in ("", ".", "..") for part in Path(name).parts)


def _load_manifest(archive: zipfile.ZipFile) -> dict[str, object]:
    infos = archive.infolist()
    if len(infos) > len(backup_file_names()) + 1:
        raise StateBackupError("Backup contains too many members.")
    seen: set[str] = set()
    total = 0
    for info in infos:
        if info.filename in seen:
            raise StateBackupError(f"Backup contains duplicate member: {info.filename}")
        seen.add(info.filename)
        if not _safe_member_name(info.filename) or info.is_dir():
            raise StateBackupError(f"Unsafe or unexpected backup member: {info.filename}")
        if info.file_size < 0 or info.file_size > MAX_MEMBER_BYTES:
            raise StateBackupError(f"Backup member is too large: {info.filename}")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise StateBackupError("Backup expands beyond the allowed size limit.")
    if MANIFEST_NAME not in seen:
        raise StateBackupError("Backup manifest is missing.")
    try:
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateBackupError("Backup manifest is invalid.") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != BACKUP_SCHEMA:
        raise StateBackupError("Backup schema is unsupported.")
    if manifest.get("completeSnapshot") is not True:
        raise StateBackupError("Backup is not a complete state snapshot.")
    records = manifest.get("files")
    if not isinstance(records, list):
        raise StateBackupError("Backup manifest file list is invalid.")
    allowed = set(backup_file_names())
    record_names: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise StateBackupError("Backup manifest contains an invalid file record.")
        name, sha256, size = record.get("name"), record.get("sha256"), record.get("size")
        if not isinstance(name, str) or name not in allowed or name in record_names:
            raise StateBackupError(f"Backup manifest contains an unexpected state file: {name!r}")
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise StateBackupError(f"Backup manifest checksum is invalid for {name}.")
        if not isinstance(size, int) or size < 0 or size > MAX_MEMBER_BYTES:
            raise StateBackupError(f"Backup manifest size is invalid for {name}.")
        if STATE_PREFIX + name not in seen:
            raise StateBackupError(f"Backup member is missing: {STATE_PREFIX + name}")
        record_names.add(name)
    expected = {MANIFEST_NAME, *(STATE_PREFIX + name for name in record_names)}
    if seen != expected:
        raise StateBackupError(f"Backup contains unexpected members: {', '.join(sorted(seen - expected))}")
    return manifest


def _validate_and_stage(archive_path: Path, staging: Path | None = None) -> tuple[dict[str, object], dict[str, Path]]:
    staged: dict[str, Path] = {}
    try:
        archive = zipfile.ZipFile(archive_path, "r", allowZip64=True)
    except (OSError, zipfile.BadZipFile) as exc:
        raise StateBackupError("Backup archive cannot be opened.") from exc
    with archive:
        manifest = _load_manifest(archive)
        records = manifest["files"]
        assert isinstance(records, list)
        for record in records:
            assert isinstance(record, dict)
            name = str(record["name"])
            info = archive.getinfo(STATE_PREFIX + name)
            if info.file_size != int(record["size"]):
                raise StateBackupError(f"Backup size mismatch for {name}.")
            digest = hashlib.sha256()
            size = 0
            target = staging / name if staging is not None else None
            output = None
            try:
                if target is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    output = target.open("wb")
                with archive.open(info, "r") as source:
                    while chunk := source.read(_COPY_CHUNK):
                        size += len(chunk)
                        if size > MAX_MEMBER_BYTES:
                            raise StateBackupError(f"Backup member exceeded size limit: {name}")
                        digest.update(chunk)
                        if output is not None:
                            output.write(chunk)
            finally:
                if output is not None:
                    output.close()
            if size != int(record["size"]) or digest.hexdigest().lower() != str(record["sha256"]).lower():
                raise StateBackupError(f"Backup checksum mismatch for {name}.")
            if target is not None:
                staged[name] = target
        return manifest, staged


def validate_state_backup(archive_path: str | os.PathLike[str]) -> dict[str, object]:
    source = Path(archive_path).expanduser()
    manifest, _ = _validate_and_stage(source)
    records = manifest["files"]
    assert isinstance(records, list)
    return {
        "path": str(source.resolve(strict=False)),
        "files": len(records),
        "bytes": sum(int(record["size"]) for record in records if isinstance(record, dict)),
        "schema": BACKUP_SCHEMA,
        "valid": True,
    }


def restore_state_backup(engine_module, archive_path: str | os.PathLike[str]) -> dict[str, object]:
    source = Path(archive_path).expanduser()
    target_root = runtime_state_dir(engine_module)
    target_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="galaxy-state-restore-", dir=str(target_root.parent)) as temporary:
        temporary_root = Path(temporary)
        staging, rollback = temporary_root / "staging", temporary_root / "rollback"
        staging.mkdir()
        rollback.mkdir()
        manifest, staged = _validate_and_stage(source, staging)
        current_names: list[str] = []
        for name in backup_file_names():
            current = target_root / name
            if not current.exists():
                continue
            if not _is_regular(current):
                raise StateBackupError(f"Refusing to replace non-regular state file: {name}")
            shutil.copy2(current, rollback / name)
            current_names.append(name)
        try:
            for name in backup_file_names():
                target = target_root / name
                if name in staged:
                    os.replace(staged[name], target)
                elif target.exists():
                    target.unlink()
        except Exception as exc:
            try:
                for name in backup_file_names():
                    target = target_root / name
                    if target.exists():
                        target.unlink()
                for name in current_names:
                    os.replace(rollback / name, target_root / name)
            except Exception as rollback_exc:
                raise StateBackupError(f"State restore failed and rollback also failed: {rollback_exc}") from exc
            raise StateBackupError("State restore failed; previous state was restored.") from exc
    records = manifest["files"]
    assert isinstance(records, list)
    return {
        "path": str(source.resolve(strict=False)),
        "files": len(records),
        "bytes": sum(int(record["size"]) for record in records if isinstance(record, dict)),
        "schema": BACKUP_SCHEMA,
        "restored": True,
    }


def run_state_backup_self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        state.mkdir()
        (state / "workspace-options.json").write_text('{"historyEnabled":true}', encoding="utf-8")
        (state / "download-profiles.json").write_text('{"version":1,"profiles":[{"id":"demo"}]}', encoding="utf-8")
        (state / "telegram-upload-secret.json").write_text('{"botToken":"NEVER"}', encoding="utf-8")
        (state / "unknown-secret.txt").write_text("NEVER", encoding="utf-8")
        (state / "engine.log").write_text("private diagnostic text", encoding="utf-8")
        with sqlite3.connect(state / "media-library.sqlite3") as database:
            database.execute("create table item (id integer primary key, value text)")
            database.execute("insert into item(value) values ('before')")
            database.commit()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root
            @staticmethod
            def state_dir() -> Path:
                return state

        archive = root / "backup.galaxy-state.zip"
        result = create_state_backup(Engine, archive)
        assert result["files"] == 3
        assert validate_state_backup(archive)["valid"] is True
        with zipfile.ZipFile(archive, "r") as backup:
            members = set(backup.namelist())
            assert STATE_PREFIX + "download-profiles.json" in members
            assert STATE_PREFIX + "engine.log" not in members
            assert STATE_PREFIX + "telegram-upload-secret.json" not in members
            assert STATE_PREFIX + "unknown-secret.txt" not in members

        (state / "workspace-options.json").write_text('{"historyEnabled":false}', encoding="utf-8")
        (state / "download-profiles.json").unlink()
        (state / "desktop-features.json").write_text('{"clipboardMonitorEnabled":true}', encoding="utf-8")
        with sqlite3.connect(state / "media-library.sqlite3") as database:
            database.execute("update item set value='after'")
            database.commit()
        assert restore_state_backup(Engine, archive)["restored"] is True
        assert (state / "workspace-options.json").read_text(encoding="utf-8") == '{"historyEnabled":true}'
        assert (state / "download-profiles.json").exists()
        assert not (state / "desktop-features.json").exists()
        assert (state / "telegram-upload-secret.json").read_text(encoding="utf-8") == '{"botToken":"NEVER"}'
        assert (state / "unknown-secret.txt").read_text(encoding="utf-8") == "NEVER"
        assert (state / "engine.log").read_text(encoding="utf-8") == "private diagnostic text"
        with sqlite3.connect(state / "media-library.sqlite3") as database:
            assert database.execute("select value from item").fetchone()[0] == "before"

        corrupt = root / "corrupt.zip"
        shutil.copy2(archive, corrupt)
        with zipfile.ZipFile(corrupt, "a") as backup:
            backup.writestr("unexpected.txt", "no")
        try:
            validate_state_backup(corrupt)
        except StateBackupError:
            pass
        else:
            raise AssertionError("Unexpected archive member was not rejected.")
