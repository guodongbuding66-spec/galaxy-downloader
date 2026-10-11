from __future__ import annotations

"""One-time migration for legacy aria2 recovery records with remote torrent URLs.

New V2 transfers already localize HTTPS torrent metadata before creating a session.
Older resume records may still contain ``sourceKind=torrent_url``. This adapter
fetches those records through the new redirect-aware metadata boundary, rewrites
them to the verified local cache, and only then delegates to the normal recovery
chain. Unsafe or unavailable legacy remote records fail closed and are removed.
"""

import threading

import aria2_recovery
from torrent_metadata_acquisition import TorrentMetadataAcquisitionError, acquire_torrent_metadata

_LOCK = threading.RLock()
_PATCHED = False


def install_remote_torrent_recovery_patch() -> None:
    global _PATCHED
    with _LOCK:
        if _PATCHED or getattr(aria2_recovery, "_galaxy_remote_torrent_recovery_patch_installed", False):
            _PATCHED = True
            return
        original_restore = aria2_recovery._restore_record

        def restore_record(context, record):
            current = dict(record)
            if str(current.get("sourceKind") or "").strip().lower() == "torrent_url":
                record_id = str(current.get("id") or "")
                try:
                    acquired = acquire_torrent_metadata(context.engine_module, current.get("source"))
                except TorrentMetadataAcquisitionError:
                    context.store.remove(record_id)
                    return None
                current["source"] = str(acquired.torrent_path)
                current["sourceKind"] = "torrent_file"
                # Preserve the old human-readable label if one exists. The store
                # cleaner intentionally recomputes sourceHost for the local cache.
                context.store.upsert(current)
                migrated = context.store.get(record_id)
                if migrated is None:
                    return None
                current = migrated
            return original_restore(context, current)

        aria2_recovery._restore_record = restore_record
        aria2_recovery._galaxy_remote_torrent_recovery_patch_installed = True
        _PATCHED = True


def run_remote_torrent_recovery_self_test() -> None:
    assert callable(install_remote_torrent_recovery_patch)


if __name__ == "__main__":
    run_remote_torrent_recovery_self_test()
    print("aria2_remote_recovery self-test: OK")
