from __future__ import annotations

"""Apply Galaxy's shared download bandwidth preference to aria2 commands.

Galaxy already persists one user-visible download limit in KiB/s.  This adapter
keeps that setting as the single source of truth and injects aria2's
``--max-download-limit`` option at command-build time.  Because the adapter is
installed before the transfer/recovery presenters, newly created and restored
aria2 sessions use the same current persisted limit without duplicating it into
resume state.
"""

import threading
from typing import Iterable

import aria2_transfer

MAX_ARIA2_BANDWIDTH_KBPS = 10_000_000
_LOCK = threading.RLock()
_LIMIT_KBPS = 0
_PATCHED = False


def normalize_aria2_bandwidth_kbps(value: object) -> int:
    if value in (None, "", False):
        return 0
    try:
        limit = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0
    if limit <= 0:
        return 0
    return min(limit, MAX_ARIA2_BANDWIDTH_KBPS)


def current_aria2_bandwidth_kbps() -> int:
    with _LOCK:
        return int(_LIMIT_KBPS)


def _inject_download_limit(command: Iterable[str], limit_kbps: object) -> list[str]:
    result = [str(item) for item in command]
    limit = normalize_aria2_bandwidth_kbps(limit_kbps)
    if not limit:
        return result
    if any(item.startswith("--max-download-limit") for item in result):
        return result
    try:
        index = result.index("--")
    except ValueError:
        index = len(result)
    result.insert(index, f"--max-download-limit={limit}K")
    return result


def install_aria2_bandwidth_command_patch() -> None:
    """Patch aria2 command construction once, preserving the original builder."""
    global _PATCHED
    with _LOCK:
        if _PATCHED or getattr(aria2_transfer, "_galaxy_bandwidth_patch_installed", False):
            _PATCHED = True
            return
        original = aria2_transfer.build_aria2_command

        def build_aria2_command(executable, options):
            command = original(executable, options)
            return _inject_download_limit(command, current_aria2_bandwidth_kbps())

        aria2_transfer.build_aria2_command = build_aria2_command
        aria2_transfer._galaxy_bandwidth_patch_installed = True
        _PATCHED = True


def configure_aria2_bandwidth(value: object) -> int:
    """Install the adapter and set the process-wide limit used by aria2 tasks."""
    global _LIMIT_KBPS
    limit = normalize_aria2_bandwidth_kbps(value)
    install_aria2_bandwidth_command_patch()
    with _LOCK:
        _LIMIT_KBPS = limit
    return limit


def run_aria2_bandwidth_self_test() -> None:
    assert normalize_aria2_bandwidth_kbps(None) == 0
    assert normalize_aria2_bandwidth_kbps("0") == 0
    assert normalize_aria2_bandwidth_kbps("512") == 512
    assert normalize_aria2_bandwidth_kbps("12.9") == 12
    assert normalize_aria2_bandwidth_kbps("bad") == 0
    assert normalize_aria2_bandwidth_kbps(MAX_ARIA2_BANDWIDTH_KBPS + 1) == MAX_ARIA2_BANDWIDTH_KBPS

    base = ["aria2c", "--continue=true", "--", "https://example.com/file.zip"]
    assert _inject_download_limit(base, 0) == base
    limited = _inject_download_limit(base, 512)
    assert limited == [
        "aria2c",
        "--continue=true",
        "--max-download-limit=512K",
        "--",
        "https://example.com/file.zip",
    ]
    assert _inject_download_limit(limited, 1024) == limited

    configure_aria2_bandwidth(2048)
    assert current_aria2_bandwidth_kbps() == 2048
    configure_aria2_bandwidth(0)
    assert current_aria2_bandwidth_kbps() == 0


if __name__ == "__main__":
    run_aria2_bandwidth_self_test()
    print("aria2_bandwidth self-test: OK")
