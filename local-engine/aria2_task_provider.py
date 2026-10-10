from __future__ import annotations

"""Expose aria2 transfers as first-class Galaxy local tasks."""

import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aria2_transfer import Aria2Progress, Aria2TransferSnapshot
from local_task_provider import (
    LocalTaskActionResult,
    LocalTaskSnapshot,
    install_local_task_provider_bridge,
    register_local_task_provider,
)

_PROVIDER_ID = "aria2"
_PROVIDER_LABEL = "aria2"
_MAX_RETAINED_TERMINAL = 40
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_ACTIVE = frozenset({"queued", "running", "retrying", "pausing", "cancelling"})
_STATE_MAP = {
    "queued": "queued", "running": "active", "retrying": "active", "pausing": "active",
    "paused": "paused", "cancelling": "active", "cancelled": "cancelled",
    "completed": "completed", "failed": "failed",
}


@dataclass
class _TrackedSession:
    task_id: str
    session: Any
    title: str


_LOCK = threading.RLock()
_SESSIONS: dict[str, _TrackedSession] = {}


def _title_for_session(session: Any) -> str:
    source = str(getattr(getattr(session, "options", None), "source", "") or "").strip()
    if source.lower().startswith("magnet:"):
        return "Magnet 下载"
    if source.lower().endswith(".torrent"):
        name = Path(source.replace("\\", "/")).name.strip()
        return name[:180] or "Torrent 下载"
    name = str(getattr(getattr(session, "options", None), "file_name", "") or "").strip()
    return name[:180] or "aria2 下载"


def _snapshot(session: Any) -> Aria2TransferSnapshot:
    value = session.snapshot()
    if not isinstance(value, Aria2TransferSnapshot):
        raise TypeError("aria2 session returned an invalid snapshot")
    return value


def _prune_locked() -> None:
    terminal_ids: list[str] = []
    for task_id, record in _SESSIONS.items():
        try:
            if _snapshot(record.session).state in _TERMINAL:
                terminal_ids.append(task_id)
        except Exception:
            terminal_ids.append(task_id)
    overflow = max(0, len(terminal_ids) - _MAX_RETAINED_TERMINAL)
    for task_id in terminal_ids[:overflow]:
        _SESSIONS.pop(task_id, None)


def register_aria2_session(session: Any, *, title: str = "") -> str:
    if session is None or not callable(getattr(session, "snapshot", None)):
        raise TypeError("aria2 session must expose snapshot()")
    task_id = f"aria2-{uuid.uuid4().hex[:16]}"
    record = _TrackedSession(task_id, session, str(title or "").strip()[:180] or _title_for_session(session))
    with _LOCK:
        _SESSIONS[task_id] = record
        _prune_locked()
    return task_id


def aria2_tasks_active() -> bool:
    with _LOCK:
        records = tuple(_SESSIONS.values())
    for record in records:
        try:
            if _snapshot(record.session).state in _ACTIVE:
                return True
        except Exception:
            continue
    return False


def cancel_active_aria2_tasks() -> int:
    with _LOCK:
        records = tuple(_SESSIONS.values())
    changed = 0
    for record in records:
        try:
            snapshot = _snapshot(record.session)
            if snapshot.state in _ACTIVE or snapshot.state == "paused":
                changed += 1 if bool(record.session.cancel()) else 0
        except Exception:
            continue
    return changed


def _detail(snapshot: Aria2TransferSnapshot) -> str:
    progress = snapshot.progress
    parts: list[str] = []
    if progress.speed: parts.append(f"速度 {progress.speed}/s")
    if progress.eta: parts.append(f"剩余 {progress.eta}")
    if progress.connections: parts.append(f"连接 {progress.connections}")
    if snapshot.attempt: parts.append(f"尝试 {snapshot.attempt}/{snapshot.max_attempts}")
    if snapshot.error and snapshot.state in {"failed", "retrying"}: parts.append(snapshot.error[:220])
    return " · ".join(parts) or "aria2c 本机传输"


def _actions(snapshot: Aria2TransferSnapshot) -> tuple[str, ...]:
    if snapshot.state in {"running", "retrying"}:
        return ("pause", "cancel")
    if snapshot.state == "paused":
        return ("resume", "cancel")
    if snapshot.state in {"queued", "pausing", "cancelling"}:
        return ("cancel",)
    if snapshot.state == "failed":
        return ("retry",)
    return ()


def _provider_snapshots() -> tuple[LocalTaskSnapshot, ...]:
    with _LOCK:
        records = tuple(_SESSIONS.values())
    output: list[LocalTaskSnapshot] = []
    for record in records:
        try:
            snapshot = _snapshot(record.session)
        except Exception:
            continue
        state = _STATE_MAP.get(snapshot.state, "failed")
        progress = max(0.0, min(float(snapshot.progress.percent), 100.0))
        failure = "aria2 传输失败" if snapshot.state == "failed" else ""
        advice = ""
        if snapshot.state == "failed":
            advice = "可在任务中心重试；aria2 会复用已保留的部分文件。"
        elif snapshot.state == "paused":
            advice = "已保留断点；可直接从任务中心继续，取消则保留现有部分文件。"
        output.append(LocalTaskSnapshot(
            task_id=record.task_id,
            state=state,
            title=record.title,
            provider_label=_PROVIDER_LABEL,
            task_type="Torrent / aria2",
            progress_percent=progress,
            detail=_detail(snapshot),
            advice=advice,
            failure_label=failure,
            actions=_actions(snapshot),
        ))
    return tuple(output)


def _provider_action(task_id: str, action: str) -> LocalTaskActionResult:
    with _LOCK:
        record = _SESSIONS.get(str(task_id or ""))
    if record is None:
        return LocalTaskActionResult(False, False, "aria2 任务不存在或已清理。")
    try:
        snapshot = _snapshot(record.session)
        if action == "pause" and snapshot.state in {"running", "retrying"}:
            changed = bool(record.session.pause())
            return LocalTaskActionResult(True, changed, "aria2 任务正在暂停并保留断点。")
        if action == "resume" and snapshot.state == "paused":
            changed = bool(record.session.resume())
            return LocalTaskActionResult(True, changed, "aria2 任务已从断点继续。")
        if action == "cancel" and (snapshot.state in _ACTIVE or snapshot.state == "paused"):
            changed = bool(record.session.cancel())
            return LocalTaskActionResult(True, changed, "aria2 任务已请求取消。")
        if action == "retry" and snapshot.state == "failed":
            changed = bool(record.session.retry())
            return LocalTaskActionResult(True, changed, "aria2 任务已重新加入执行。")
    except Exception as exc:
        return LocalTaskActionResult(False, False, f"aria2 任务操作失败：{exc}")
    return LocalTaskActionResult(False, False, "当前 aria2 状态不允许这个操作。")


def _install_close_guard(engine_module) -> None:
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_aria2_close_guard_installed", False):
        return
    original_close = getattr(window_cls, "close_app", None)
    if not callable(original_close):
        return

    def close_with_aria2(window) -> None:
        if not aria2_tasks_active():
            original_close(window)
            return
        if getattr(window, "_galaxy_aria2_close_pending", False):
            return
        window._galaxy_aria2_close_pending = True
        cancel_active_aria2_tasks()
        setter = getattr(window, "set_status", None)
        if callable(setter):
            try: setter("Cancelling", "正在安全停止 aria2/Torrent 传输…")
            except Exception: pass

        def finish_when_idle() -> None:
            if aria2_tasks_active():
                try: window.after(100, finish_when_idle)
                except Exception: pass
                return
            original_close(window)

        try: window.after(100, finish_when_idle)
        except Exception: original_close(window)

    window_cls.close_app = close_with_aria2
    window_cls._galaxy_aria2_close_guard_installed = True


def install_aria2_task_provider(engine_module):
    if getattr(engine_module, "_galaxy_aria2_task_provider_installed", False):
        return engine_module.EngineWindow
    register_local_task_provider(_PROVIDER_ID, label=_PROVIDER_LABEL, snapshot=_provider_snapshots, action=_provider_action)
    install_local_task_provider_bridge(engine_module)
    _install_close_guard(engine_module)
    engine_module._galaxy_aria2_task_provider_installed = True
    return engine_module.EngineWindow


def run_aria2_task_provider_self_test() -> None:
    class _Options:
        source = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
        file_name = ""

    class _FakeSession:
        options = _Options()
        def __init__(self) -> None: self.state = "running"
        def snapshot(self) -> Aria2TransferSnapshot:
            return Aria2TransferSnapshot(self.state, 1, 3, Aria2Progress(42, "3.2MiB", "18s", 16), Path("downloads/torrents"), "temporary" if self.state == "failed" else "", 2 if self.state == "failed" else None)
        def pause(self) -> bool:
            if self.state not in {"running", "retrying"}: return False
            self.state = "paused"; return True
        def resume(self) -> bool:
            if self.state != "paused": return False
            self.state = "running"; return True
        def cancel(self) -> bool: self.state = "cancelled"; return True
        def retry(self) -> bool:
            if self.state != "failed": return False
            self.state = "queued"; return True

    fake = _FakeSession()
    task_id = register_aria2_session(fake)
    try:
        row = [item for item in _provider_snapshots() if item.task_id == task_id][0]
        assert row.state == "active" and row.progress_percent == 42.0
        assert row.actions == ("pause", "cancel")
        paused = _provider_action(task_id, "pause")
        assert paused.ok is True and paused.changed is True and fake.state == "paused"
        paused_row = [item for item in _provider_snapshots() if item.task_id == task_id][0]
        assert paused_row.actions == ("resume", "cancel")
        resumed = _provider_action(task_id, "resume")
        assert resumed.ok is True and resumed.changed is True and fake.state == "running"
        cancelled = _provider_action(task_id, "cancel")
        assert cancelled.ok is True and fake.state == "cancelled"
        fake.state = "failed"
        failed = [item for item in _provider_snapshots() if item.task_id == task_id][0]
        assert failed.state == "failed" and failed.actions == ("retry",)
        retried = _provider_action(task_id, "retry")
        assert retried.ok is True and fake.state == "queued"
    finally:
        with _LOCK:
            _SESSIONS.pop(task_id, None)
