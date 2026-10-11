from __future__ import annotations

"""Selective Torrent file adapter for Galaxy aria2 sessions.

The stable aria2 core remains unchanged. This adapter binds a validated tuple of
one-based Torrent file indexes to ``Aria2TransferOptions``, preserves the binding
through option normalization, injects aria2's ``--select-file`` argument, and
extends restart recovery records with the same selection.
"""

import threading
from dataclasses import replace
from pathlib import Path
from typing import Iterable

import aria2_recovery
import aria2_transfer

MAX_SELECTED_FILES = 20_000
MAX_FILE_INDEX = 1_000_000
_LOCK = threading.RLock()
_TRANSFER_PATCHED = False
_RECOVERY_PATCHED = False


class Aria2FileSelectionError(ValueError):
    pass


def normalize_selected_files(values: object) -> tuple[int, ...]:
    if values in (None, "", (), [], set()):
        return ()
    if isinstance(values, str):
        raw_values: Iterable[object] = [part.strip() for part in values.split(",") if part.strip()]
    elif isinstance(values, Iterable):
        raw_values = values
    else:
        raise Aria2FileSelectionError("Torrent 文件选择必须是索引列表")

    selected: set[int] = set()
    for value in raw_values:
        if isinstance(value, bool):
            raise Aria2FileSelectionError("Torrent 文件索引无效")
        try:
            index = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise Aria2FileSelectionError("Torrent 文件索引必须是整数") from exc
        if index < 1 or index > MAX_FILE_INDEX:
            raise Aria2FileSelectionError(f"Torrent 文件索引必须在 1–{MAX_FILE_INDEX} 范围内")
        selected.add(index)
        if len(selected) > MAX_SELECTED_FILES:
            raise Aria2FileSelectionError(f"一次最多选择 {MAX_SELECTED_FILES} 个 Torrent 文件")
    return tuple(sorted(selected))


def _selection_arg(values: object) -> str:
    selected = normalize_selected_files(values)
    if not selected:
        return ""
    ranges: list[str] = []
    start = previous = selected[0]
    for index in selected[1:]:
        if index == previous + 1:
            previous = index
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = index
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def selected_files_for(options: object) -> tuple[int, ...]:
    return normalize_selected_files(getattr(options, "_galaxy_selected_files", ()))


def bind_selected_files(options, values: object):
    selected = normalize_selected_files(values)
    object.__setattr__(options, "_galaxy_selected_files", selected)
    return options


def _adapter_state(options: object) -> dict[str, object]:
    """Capture Galaxy adapter fields that dataclasses.replace() would discard."""
    try:
        values = vars(options)
    except TypeError:
        return {}
    return {name: value for name, value in values.items() if str(name).startswith("_galaxy_")}


def _restore_adapter_state(options: object, state: dict[str, object]) -> None:
    for name, value in state.items():
        object.__setattr__(options, name, value)


def _inject_select_file(command: Iterable[str], selected_files: object) -> list[str]:
    result = [str(item) for item in command]
    arg = _selection_arg(selected_files)
    if not arg:
        return result
    if any(item.startswith("--select-file=") for item in result):
        return result
    try:
        index = result.index("--")
    except ValueError:
        index = len(result)
    result.insert(index, f"--select-file={arg}")
    return result


def install_transfer_selection_patch() -> None:
    global _TRANSFER_PATCHED
    with _LOCK:
        if _TRANSFER_PATCHED or getattr(aria2_transfer, "_galaxy_file_selection_patch_installed", False):
            _TRANSFER_PATCHED = True
            return
        original_normalize = aria2_transfer.normalize_options
        original_build = aria2_transfer.build_aria2_command

        def normalize_options(options):
            selected = selected_files_for(options)
            normalized = original_normalize(options)
            return bind_selected_files(normalized, selected)

        def build_aria2_command(executable, options):
            command = original_build(executable, options)
            return _inject_select_file(command, selected_files_for(options))

        aria2_transfer.normalize_options = normalize_options
        aria2_transfer.build_aria2_command = build_aria2_command
        aria2_transfer._galaxy_file_selection_patch_installed = True
        _TRANSFER_PATCHED = True


def _attach_selection_persistence(context, session, record_id: str, selected: tuple[int, ...], *, emit: bool) -> None:
    if not selected:
        return

    def persist_selection(snapshot) -> None:
        if snapshot.state in {"completed", "cancelled"}:
            return
        record = context.store.get(record_id)
        if record is None:
            return
        record["selectedFiles"] = list(selected)
        context.store.upsert(record)

    session.add_recovery_observer(persist_selection, emit=emit)


def install_recovery_selection_patch() -> None:
    global _RECOVERY_PATCHED
    with _LOCK:
        if _RECOVERY_PATCHED or getattr(aria2_recovery, "_galaxy_file_selection_patch_installed", False):
            _RECOVERY_PATCHED = True
            return
        original_clean = aria2_recovery._clean_aria2_record
        original_attach = aria2_recovery._attach_session
        original_restore = aria2_recovery._restore_record
        original_create = aria2_recovery.create_recoverable_aria2_session

        def clean_record(store, value):
            cleaned = original_clean(store, value)
            if cleaned is None:
                return None
            try:
                cleaned["selectedFiles"] = list(normalize_selected_files(value.get("selectedFiles")))
            except Aria2FileSelectionError:
                return None
            return cleaned

        def attach_session(context, session, source_kind, *, resume_id=None, emit=True):
            record_id = original_attach(context, session, source_kind, resume_id=resume_id, emit=emit)
            selected = selected_files_for(session.options)
            _attach_selection_persistence(context, session, record_id, selected, emit=emit)
            return record_id

        def restore_record(context, record):
            session = original_restore(context, record)
            if session is None:
                return None
            try:
                selected = normalize_selected_files(record.get("selectedFiles"))
                bind_selected_files(session.options, selected)
            except Aria2FileSelectionError:
                context.store.remove(str(record.get("id") or ""))
                return None
            _attach_selection_persistence(context, session, str(record.get("id") or ""), selected, emit=False)
            return session

        def create_recoverable_aria2_session(
            engine_module,
            executable,
            options,
            *,
            source_kind,
            on_update=None,
            max_retry_delay_seconds=1.0,
        ):
            adapter_state = _adapter_state(options)
            prepared = options
            # aria2_recovery uses dataclasses.replace() when allocating a stable
            # GID. Dynamic Galaxy adapter fields are not dataclass fields. Clone
            # them generically here so file selection, per-task bandwidth and
            # future adapters survive the same allocation path.
            if adapter_state and not getattr(options, "aria2_gid", ""):
                prepared = replace(options, aria2_gid=aria2_recovery._new_aria2_gid())
                _restore_adapter_state(prepared, adapter_state)
            session = original_create(
                engine_module,
                executable,
                prepared,
                source_kind=source_kind,
                on_update=on_update,
                max_retry_delay_seconds=max_retry_delay_seconds,
            )
            if adapter_state:
                _restore_adapter_state(session.options, adapter_state)
            return session

        aria2_recovery._clean_aria2_record = clean_record
        aria2_recovery._attach_session = attach_session
        aria2_recovery._restore_record = restore_record
        aria2_recovery.create_recoverable_aria2_session = create_recoverable_aria2_session
        aria2_recovery._galaxy_file_selection_patch_installed = True
        _RECOVERY_PATCHED = True


def install_aria2_file_selection() -> None:
    install_transfer_selection_patch()
    install_recovery_selection_patch()


def run_aria2_file_selection_self_test() -> None:
    assert normalize_selected_files(None) == ()
    assert normalize_selected_files([3, 1, 2, 2, "5"]) == (1, 2, 3, 5)
    assert _selection_arg((1, 2, 3, 5, 7, 8, 9)) == "1-3,5,7-9"
    base = ["aria2c", "--continue=true", "--", "bundle.torrent"]
    assert _inject_select_file(base, ()) == base
    selected = _inject_select_file(base, (1, 2, 5))
    assert selected == ["aria2c", "--continue=true", "--select-file=1-2,5", "--", "bundle.torrent"]
    assert _inject_select_file(selected, (9,)) == selected

    options = aria2_transfer.Aria2TransferOptions(source="https://example.com/a.torrent", destination=Path("downloads"))
    bind_selected_files(options, (2, 4))
    object.__setattr__(options, "_galaxy_probe_adapter", "kept")
    install_aria2_file_selection()
    normalized = aria2_transfer.normalize_options(options)
    assert selected_files_for(normalized) == (2, 4)
    command = aria2_transfer.build_aria2_command(Path("aria2c"), normalized)
    assert "--select-file=2,4" in command

    recoverable = aria2_recovery.create_recoverable_aria2_session(
        object(),
        Path("aria2c"),
        options,
        source_kind="torrent_url",
    )
    assert selected_files_for(recoverable.options) == (2, 4)
    assert getattr(recoverable.options, "_galaxy_probe_adapter", "") == "kept"
    assert recoverable.options.aria2_gid

    for bad in ((0,), (-1,), (MAX_FILE_INDEX + 1,), (True,), ("x",)):
        try:
            normalize_selected_files(bad)
        except Aria2FileSelectionError:
            pass
        else:
            raise AssertionError(f"invalid selection accepted: {bad}")


if __name__ == "__main__":
    run_aria2_file_selection_self_test()
    print("aria2_file_selection self-test: OK")
