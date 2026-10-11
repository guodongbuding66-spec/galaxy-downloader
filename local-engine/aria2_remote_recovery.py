from __future__ import annotations

"""One-time migration for legacy aria2 recovery records with remote torrent URLs.

New V2 transfers already localize HTTPS torrent metadata before creating a session.
Older resume records may still contain ``sourceKind=torrent_url``. This adapter
fetches those records through the new redirect-aware metadata boundary, rewrites
them to the verified local cache, and only then delegates to the normal recovery
chain. Unsafe or unavailable legacy remote records fail closed and are removed.
"""

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import aria2_recovery
from torrent_metadata_acquisition import TorrentMetadataAcquisitionError, acquire_torrent_metadata

_LOCK = threading.RLock()
_PATCHED = False


def _migrate_legacy_remote_record(context, record, *, acquire: Callable = acquire_torrent_metadata):
    current = dict(record)
    if str(current.get("sourceKind") or "").strip().lower() != "torrent_url":
        return current
    record_id = str(current.get("id") or "")
    try:
        acquired = acquire(context.engine_module, current.get("source"))
    except TorrentMetadataAcquisitionError:
        context.store.remove(record_id)
        return None
    current["source"] = str(acquired.torrent_path)
    current["sourceKind"] = "torrent_file"
    context.store.upsert(current)
    return context.store.get(record_id)


def install_remote_torrent_recovery_patch() -> None:
    global _PATCHED
    with _LOCK:
        if _PATCHED or getattr(aria2_recovery, "_galaxy_remote_torrent_recovery_patch_installed", False):
            _PATCHED = True
            return
        original_restore = aria2_recovery._restore_record

        def restore_record(context, record):
            current = _migrate_legacy_remote_record(context, record)
            if current is None:
                return None
            return original_restore(context, current)

        aria2_recovery._restore_record = restore_record
        aria2_recovery._galaxy_remote_torrent_recovery_patch_installed = True
        _PATCHED = True


def run_remote_torrent_recovery_self_test() -> None:
    class FakeStore:
        def __init__(self) -> None:
            self.records = {}
            self.removed = []
        def upsert(self, value):
            self.records[str(value["id"])] = dict(value)
            return True
        def get(self, record_id):
            value = self.records.get(str(record_id))
            return dict(value) if value else None
        def remove(self, record_id):
            self.removed.append(str(record_id))
            self.records.pop(str(record_id), None)
            return True

    store = FakeStore()
    context = SimpleNamespace(engine_module=object(), store=store)
    record = {
        "id": "aria2resumeabc",
        "source": "https://downloads.example.com/demo.torrent",
        "sourceKind": "torrent_url",
        "label": "demo.torrent",
    }
    acquired = SimpleNamespace(torrent_path=Path("state/torrent-metadata/verified.torrent"))
    migrated = _migrate_legacy_remote_record(context, record, acquire=lambda *_args: acquired)
    assert migrated is not None
    assert migrated["sourceKind"] == "torrent_file"
    assert migrated["source"] == str(acquired.torrent_path)
    assert migrated["label"] == "demo.torrent"

    failed = {
        "id": "aria2resumebad",
        "source": "https://127.0.0.1/private.torrent",
        "sourceKind": "torrent_url",
    }
    def reject(*_args):
        raise TorrentMetadataAcquisitionError("blocked")
    assert _migrate_legacy_remote_record(context, failed, acquire=reject) is None
    assert "aria2resumebad" in store.removed

    local = {"id": "aria2resumelocal", "source": "demo.torrent", "sourceKind": "torrent_file"}
    assert _migrate_legacy_remote_record(context, local, acquire=reject) == local
    assert callable(install_remote_torrent_recovery_patch)


if __name__ == "__main__":
    run_remote_torrent_recovery_self_test()
    print("aria2_remote_recovery self-test: OK")
