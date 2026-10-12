from __future__ import annotations

"""Apply Galaxy global and per-task bandwidth policy to aria2 commands.

The persisted global ``bandwidthLimitKbps`` remains the default for aria2 tasks.
Each aria2 transfer may additionally carry a private task override with three
states: ``None`` inherits the global preference, ``0`` explicitly disables the
limit for that task, and a positive KiB/s value overrides the global preference.
Task overrides are persisted in aria2 recovery state so restart/resume keeps the
same transfer policy without changing the global user preference.
"""

import threading
from typing import Iterable

import aria2_recovery
import aria2_transfer

MAX_ARIA2_BANDWIDTH_KBPS = 10_000_000
_TASK_ATTR = "_galaxy_task_bandwidth_kbps"
_RECOVERY_KEY = "aria2BandwidthOverrideKbps"
_LOCK = threading.RLock()
_LIMIT_KBPS = 0
_PATCHED = False
_RECOVERY_PATCHED = False


class Aria2TaskBandwidthError(ValueError):
    pass


def normalize_aria2_bandwidth_kbps(value: object) -> int:
    """Normalize the persisted global KiB/s limit; zero means unlimited."""
    if value in (None, "", False):
        return 0
    try:
        limit = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0
    if limit <= 0:
        return 0
    return min(limit, MAX_ARIA2_BANDWIDTH_KBPS)


def normalize_aria2_task_bandwidth_kbps(value: object) -> int | None:
    """Normalize task override: None=inherit, 0=unlimited, positive=KiB/s."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "inherit", "global"}:
        return None
    if isinstance(value, bool):
        raise Aria2TaskBandwidthError("aria2 单任务限速必须是 KiB/s 数值、0 或继承全局")
    try:
        limit = int(float(str(value).strip()))
    except (TypeError, ValueError) as exc:
        raise Aria2TaskBandwidthError("aria2 单任务限速必须是 KiB/s 数值、0 或继承全局") from exc
    if limit < 0:
        raise Aria2TaskBandwidthError("aria2 单任务限速不能为负数")
    return min(limit, MAX_ARIA2_BANDWIDTH_KBPS)


def bind_aria2_task_bandwidth(options, value: object):
    override = normalize_aria2_task_bandwidth_kbps(value)
    object.__setattr__(options, _TASK_ATTR, override)
    return options


def aria2_task_bandwidth_for(options: object) -> int | None:
    return normalize_aria2_task_bandwidth_kbps(getattr(options, _TASK_ATTR, None))


def current_aria2_bandwidth_kbps() -> int:
    with _LOCK:
        return int(_LIMIT_KBPS)


def _insert_before_source(command: list[str], value: str) -> None:
    try:
        index = command.index("--")
    except ValueError:
        index = len(command)
    command.insert(index, value)


def _inject_download_limit(command: Iterable[str], limit_kbps: object) -> list[str]:
    """Apply the global limit only when no task-specific flag already exists."""
    result = [str(item) for item in command]
    limit = normalize_aria2_bandwidth_kbps(limit_kbps)
    if not limit:
        return result
    if any(item.startswith("--max-download-limit") for item in result):
        return result
    _insert_before_source(result, f"--max-download-limit={limit}K")
    return result


def _override_download_limit(command: Iterable[str], limit_kbps: object) -> list[str]:
    """Force the per-task limit, including explicit 0 = unrestricted."""
    result = [str(item) for item in command]
    limit = normalize_aria2_task_bandwidth_kbps(limit_kbps)
    if limit is None:
        return result
    result = [item for item in result if not item.startswith("--max-download-limit")]
    value = "0" if limit == 0 else f"{limit}K"
    _insert_before_source(result, f"--max-download-limit={value}")
    return result


def install_aria2_bandwidth_command_patch() -> None:
    """Patch aria2 option normalization and command construction once."""
    global _PATCHED
    with _LOCK:
        if _PATCHED or getattr(aria2_transfer, "_galaxy_bandwidth_patch_installed", False):
            _PATCHED = True
            return
        original_normalize = aria2_transfer.normalize_options
        original_build = aria2_transfer.build_aria2_command

        def normalize_options(options):
            has_override = hasattr(options, _TASK_ATTR)
            override = aria2_task_bandwidth_for(options) if has_override else None
            normalized = original_normalize(options)
            if has_override:
                bind_aria2_task_bandwidth(normalized, override)
            return normalized

        def build_aria2_command(executable, options):
            command = original_build(executable, options)
            if hasattr(options, _TASK_ATTR):
                override = aria2_task_bandwidth_for(options)
                if override is not None:
                    return _override_download_limit(command, override)
            return _inject_download_limit(command, current_aria2_bandwidth_kbps())

        aria2_transfer.normalize_options = normalize_options
        aria2_transfer.build_aria2_command = build_aria2_command
        aria2_transfer._galaxy_bandwidth_patch_installed = True
        _PATCHED = True


def _attach_task_bandwidth_persistence(context, session, record_id: str, override: int | None, *, emit: bool) -> None:
    if override is None:
        return

    def persist_bandwidth(snapshot) -> None:
        if snapshot.state in {"completed", "cancelled"}:
            return
        record = context.store.get(record_id)
        if record is None:
            return
        record[_RECOVERY_KEY] = override
        context.store.upsert(record)

    session.add_recovery_observer(persist_bandwidth, emit=emit)


def install_aria2_bandwidth_recovery_patch() -> None:
    """Persist explicit per-task overrides through the aria2 restart store."""
    global _RECOVERY_PATCHED
    with _LOCK:
        if _RECOVERY_PATCHED or getattr(aria2_recovery, "_galaxy_bandwidth_recovery_patch_installed", False):
            _RECOVERY_PATCHED = True
            return
        original_clean = aria2_recovery._clean_aria2_record
        original_attach = aria2_recovery._attach_session
        original_restore = aria2_recovery._restore_record

        def clean_record(store, value):
            cleaned = original_clean(store, value)
            if cleaned is None:
                return None
            try:
                cleaned[_RECOVERY_KEY] = normalize_aria2_task_bandwidth_kbps(value.get(_RECOVERY_KEY))
            except Aria2TaskBandwidthError:
                return None
            return cleaned

        def attach_session(context, session, source_kind, *, resume_id=None, emit=True):
            record_id = original_attach(context, session, source_kind, resume_id=resume_id, emit=emit)
            override = aria2_task_bandwidth_for(session.options)
            _attach_task_bandwidth_persistence(context, session, record_id, override, emit=emit)
            return record_id

        def restore_record(context, record):
            try:
                override = normalize_aria2_task_bandwidth_kbps(record.get(_RECOVERY_KEY))
            except Aria2TaskBandwidthError:
                context.store.remove(str(record.get("id") or ""))
                return None
            session = original_restore(context, record)
            if session is None:
                return None
            bind_aria2_task_bandwidth(session.options, override)
            _attach_task_bandwidth_persistence(
                context,
                session,
                str(record.get("id") or ""),
                override,
                emit=override is not None,
            )
            return session

        aria2_recovery._clean_aria2_record = clean_record
        aria2_recovery._attach_session = attach_session
        aria2_recovery._restore_record = restore_record
        aria2_recovery._galaxy_bandwidth_recovery_patch_installed = True
        _RECOVERY_PATCHED = True


def install_aria2_bandwidth() -> None:
    install_aria2_bandwidth_command_patch()
    install_aria2_bandwidth_recovery_patch()


def configure_aria2_bandwidth(value: object) -> int:
    """Install the adapter and set the process-wide default used by aria2 tasks."""
    global _LIMIT_KBPS
    limit = normalize_aria2_bandwidth_kbps(value)
    install_aria2_bandwidth()
    with _LOCK:
        _LIMIT_KBPS = limit
    return limit


def run_aria2_bandwidth_self_test() -> None:
    from pathlib import Path
    import tempfile

    assert normalize_aria2_bandwidth_kbps(None) == 0
    assert normalize_aria2_bandwidth_kbps("0") == 0
    assert normalize_aria2_bandwidth_kbps("512") == 512
    assert normalize_aria2_bandwidth_kbps("12.9") == 12
    assert normalize_aria2_bandwidth_kbps("bad") == 0
    assert normalize_aria2_bandwidth_kbps(MAX_ARIA2_BANDWIDTH_KBPS + 1) == MAX_ARIA2_BANDWIDTH_KBPS
    assert normalize_aria2_task_bandwidth_kbps(None) is None
    assert normalize_aria2_task_bandwidth_kbps("inherit") is None
    assert normalize_aria2_task_bandwidth_kbps(0) == 0
    assert normalize_aria2_task_bandwidth_kbps("512") == 512

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
    assert "--max-download-limit=0" in _override_download_limit(limited, 0)
    overridden = _override_download_limit(limited, 2048)
    assert "--max-download-limit=2048K" in overridden
    assert "--max-download-limit=512K" not in overridden

    install_aria2_bandwidth()
    configure_aria2_bandwidth(2048)
    assert current_aria2_bandwidth_kbps() == 2048

    with tempfile.TemporaryDirectory() as directory:
        destination = Path(directory)
        inherited = aria2_transfer.Aria2TransferOptions("https://example.com/a.zip", destination)
        command = aria2_transfer.build_aria2_command(Path("aria2c"), inherited)
        assert "--max-download-limit=2048K" in command

        unlimited = aria2_transfer.Aria2TransferOptions("https://example.com/b.zip", destination)
        bind_aria2_task_bandwidth(unlimited, 0)
        normalized = aria2_transfer.normalize_options(unlimited)
        assert aria2_task_bandwidth_for(normalized) == 0
        command = aria2_transfer.build_aria2_command(Path("aria2c"), normalized)
        assert "--max-download-limit=0" in command
        assert "--max-download-limit=2048K" not in command

        task_limited = aria2_transfer.Aria2TransferOptions("https://example.com/c.zip", destination)
        bind_aria2_task_bandwidth(task_limited, 512)
        command = aria2_transfer.build_aria2_command(Path("aria2c"), task_limited)
        assert "--max-download-limit=512K" in command
        assert "--max-download-limit=2048K" not in command

    configure_aria2_bandwidth(0)
    assert current_aria2_bandwidth_kbps() == 0

    for bad in (-1, True, "bad"):
        try:
            normalize_aria2_task_bandwidth_kbps(bad)
        except Aria2TaskBandwidthError:
            pass
        else:
            raise AssertionError(f"invalid task bandwidth accepted: {bad!r}")


if __name__ == "__main__":
    run_aria2_bandwidth_self_test()
    print("aria2_bandwidth self-test: OK")
