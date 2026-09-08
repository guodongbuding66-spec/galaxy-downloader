from __future__ import annotations

import importlib
import re
import threading
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from desktop_hooks import register_history_button_hook

_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_WINDOWS_PATH_RE = re.compile(r"(?i)(?<![A-Za-z0-9])[A-Za-z]:[\\/](?:[^\s\r\n]+)")
_POSIX_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9:])/(?:Users|home|tmp|var|private|opt|mnt|Volumes|run|etc)/(?:[^\s\r\n]+)"
)
_HEADER_RE = re.compile(r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*[^\r\n]+")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/=]{8,}")
_FILE_URL_RE = re.compile(r"(?i)\bfile://[^\s\r\n]+")

MAX_TASKS_PER_PROVIDER = 500
MAX_TOTAL_PROVIDER_TASKS = 2_000
MAX_TITLE_CHARS = 220
MAX_DETAIL_CHARS = 600
MAX_ADVICE_CHARS = 600
MAX_LABEL_CHARS = 120
MAX_WHEN_CHARS = 80
ALLOWED_STATES = frozenset({"active", "queued", "paused", "interrupted", "completed", "failed", "cancelled"})
ALLOWED_ACTIONS = frozenset({"cancel", "retry"})
_STATE_ALIASES = {"running": "active", "canceled": "cancelled"}


class LocalTaskProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalTaskSnapshot:
    task_id: str
    state: str
    title: str
    provider_label: str
    task_type: str = "本机任务"
    progress_percent: float | None = None
    when: str = ""
    detail: str = ""
    advice: str = ""
    failure_label: str = ""
    actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class LocalTaskActionResult:
    ok: bool
    changed: bool
    message: str


SnapshotCallback = Callable[[], Iterable[LocalTaskSnapshot]]
ActionCallback = Callable[[str, str], LocalTaskActionResult]


@dataclass(frozen=True)
class _ProviderRecord:
    provider: str
    label: str
    snapshot: SnapshotCallback
    action: ActionCallback | None


def _clean_identifier(value: object, pattern: re.Pattern[str], label: str) -> str:
    text = str(value or "").strip()
    if not pattern.fullmatch(text):
        raise LocalTaskProviderError(f"invalid {label}")
    return text


def _public_text(value: object, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    text = _FILE_URL_RE.sub("[local path hidden]", text)
    text = _WINDOWS_PATH_RE.sub("[local path hidden]", text)
    text = _POSIX_PATH_RE.sub("[local path hidden]", text)
    text = _HEADER_RE.sub(lambda match: f"{match.group(1)}: [redacted]", text)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    return text[:limit]


def _clean_state(value: object) -> str:
    state = str(value or "").strip().lower()
    state = _STATE_ALIASES.get(state, state)
    if state not in ALLOWED_STATES:
        raise LocalTaskProviderError("invalid local task state")
    return state


def _clean_actions(values: Sequence[object]) -> tuple[str, ...]:
    actions: list[str] = []
    for value in values:
        action = str(value or "").strip().lower()
        if action not in ALLOWED_ACTIONS:
            raise LocalTaskProviderError("invalid local task action")
        if action not in actions:
            actions.append(action)
    return tuple(actions)


def _clean_snapshot(snapshot: LocalTaskSnapshot, fallback_label: str) -> LocalTaskSnapshot:
    if not isinstance(snapshot, LocalTaskSnapshot):
        raise LocalTaskProviderError("provider snapshot must use LocalTaskSnapshot")
    progress: float | None
    if snapshot.progress_percent is None:
        progress = None
    else:
        try:
            progress = float(snapshot.progress_percent)
        except (TypeError, ValueError) as exc:
            raise LocalTaskProviderError("invalid local task progress") from exc
        if progress != progress or progress in {float("inf"), float("-inf")}:
            raise LocalTaskProviderError("invalid local task progress")
        progress = max(0.0, min(progress, 100.0))

    return LocalTaskSnapshot(
        task_id=_clean_identifier(snapshot.task_id, _TASK_ID_RE, "local task id"),
        state=_clean_state(snapshot.state),
        title=_public_text(snapshot.title, MAX_TITLE_CHARS) or "本机任务",
        provider_label=_public_text(snapshot.provider_label or fallback_label, MAX_LABEL_CHARS) or fallback_label,
        task_type=_public_text(snapshot.task_type, MAX_LABEL_CHARS) or "本机任务",
        progress_percent=progress,
        when=_public_text(snapshot.when, MAX_WHEN_CHARS),
        detail=_public_text(snapshot.detail, MAX_DETAIL_CHARS),
        advice=_public_text(snapshot.advice, MAX_ADVICE_CHARS),
        failure_label=_public_text(snapshot.failure_label, MAX_LABEL_CHARS),
        actions=_clean_actions(snapshot.actions),
    )


def _task_row(provider: str, snapshot: LocalTaskSnapshot) -> dict[str, object]:
    if snapshot.progress_percent is not None:
        when = f"{snapshot.progress_percent:.1f}%"
    else:
        when = snapshot.when or "—"
    return {
        "key": f"x:{provider}:{snapshot.task_id}",
        "kind": "provider",
        "state": snapshot.state,
        "sourceHost": snapshot.provider_label,
        "sourceUrl": "",
        "videoQuality": snapshot.task_type,
        "when": when,
        "label": snapshot.title,
        "detail": snapshot.detail,
        "advice": snapshot.advice,
        "failureLabel": snapshot.failure_label,
        "providerName": provider,
        "providerTaskId": snapshot.task_id,
        "providerActions": snapshot.actions,
    }


class LocalTaskProviderRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._providers: dict[str, _ProviderRecord] = {}

    def register(
        self,
        provider: str,
        *,
        label: str,
        snapshot: SnapshotCallback,
        action: ActionCallback | None = None,
    ) -> None:
        clean_provider = _clean_identifier(provider, _PROVIDER_RE, "provider id")
        clean_label = _public_text(label, MAX_LABEL_CHARS)
        if not clean_label:
            raise LocalTaskProviderError("provider label must not be empty")
        if not callable(snapshot):
            raise LocalTaskProviderError("provider snapshot callback must be callable")
        if action is not None and not callable(action):
            raise LocalTaskProviderError("provider action callback must be callable")
        record = _ProviderRecord(clean_provider, clean_label, snapshot, action)
        with self._lock:
            existing = self._providers.get(clean_provider)
            if existing is not None:
                if existing == record:
                    return
                raise LocalTaskProviderError(f"local task provider already registered: {clean_provider}")
            self._providers[clean_provider] = record

    def unregister(self, provider: str) -> bool:
        clean_provider = _clean_identifier(provider, _PROVIDER_RE, "provider id")
        with self._lock:
            return self._providers.pop(clean_provider, None) is not None

    def provider_names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._providers))

    def _records(self) -> tuple[_ProviderRecord, ...]:
        with self._lock:
            return tuple(self._providers[key] for key in sorted(self._providers))

    @staticmethod
    def _snapshots(record: _ProviderRecord) -> tuple[LocalTaskSnapshot, ...]:
        try:
            raw = list(record.snapshot())
        except Exception as exc:  # provider internals must not escape into Task Center
            raise LocalTaskProviderError("local task provider snapshot failed") from exc
        if len(raw) > MAX_TASKS_PER_PROVIDER:
            raw = raw[:MAX_TASKS_PER_PROVIDER]
        cleaned: list[LocalTaskSnapshot] = []
        seen: set[str] = set()
        for item in raw:
            task = _clean_snapshot(item, record.label)
            if task.task_id in seen:
                raise LocalTaskProviderError("duplicate local task id")
            seen.add(task.task_id)
            cleaned.append(task)
        return tuple(cleaned)

    def rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for record in self._records():
            try:
                snapshots = self._snapshots(record)
            except LocalTaskProviderError:
                continue
            for snapshot in snapshots:
                rows.append(_task_row(record.provider, snapshot))
                if len(rows) >= MAX_TOTAL_PROVIDER_TASKS:
                    return rows
        return rows

    def perform_action(self, provider: str, task_id: str, action: str) -> LocalTaskActionResult:
        clean_provider = _clean_identifier(provider, _PROVIDER_RE, "provider id")
        clean_task_id = _clean_identifier(task_id, _TASK_ID_RE, "local task id")
        clean_action = str(action or "").strip().lower()
        if clean_action not in ALLOWED_ACTIONS:
            return LocalTaskActionResult(False, False, "不支持这个本机任务操作。")
        with self._lock:
            record = self._providers.get(clean_provider)
        if record is None:
            return LocalTaskActionResult(False, False, "本机任务 Provider 不可用。")
        if record.action is None:
            return LocalTaskActionResult(False, False, "这个本机任务不支持操作。")
        try:
            current = next(
                (item for item in self._snapshots(record) if item.task_id == clean_task_id),
                None,
            )
        except LocalTaskProviderError:
            return LocalTaskActionResult(False, False, "本机任务状态暂时不可用。")
        if current is None:
            return LocalTaskActionResult(False, False, "本机任务不存在或已结束。")
        if clean_action not in current.actions:
            return LocalTaskActionResult(False, False, "当前状态不允许这个本机任务操作。")
        try:
            result = record.action(clean_task_id, clean_action)
        except Exception:
            return LocalTaskActionResult(False, False, "本机任务操作失败。")
        if not isinstance(result, LocalTaskActionResult):
            return LocalTaskActionResult(False, False, "本机任务操作返回了无效结果。")
        return LocalTaskActionResult(
            bool(result.ok),
            bool(result.changed),
            _public_text(result.message, MAX_DETAIL_CHARS),
        )


_REGISTRY = LocalTaskProviderRegistry()


def register_local_task_provider(
    provider: str,
    *,
    label: str,
    snapshot: SnapshotCallback,
    action: ActionCallback | None = None,
) -> None:
    _REGISTRY.register(provider, label=label, snapshot=snapshot, action=action)


def unregister_local_task_provider(provider: str) -> bool:
    return _REGISTRY.unregister(provider)


def local_task_provider_names() -> tuple[str, ...]:
    return _REGISTRY.provider_names()


def local_task_rows() -> list[dict[str, object]]:
    return _REGISTRY.rows()


def perform_local_task_action(provider: str, task_id: str, action: str) -> LocalTaskActionResult:
    return _REGISTRY.perform_action(provider, task_id, action)


def install_local_task_provider_bridge(engine_module, *, task_center_module=None):
    """Append provider rows to the existing Task Center without replacing its UI.

    The bridge patches only Task Center's row aggregator. Provider callbacks stay
    inside this module and never become row values. A later workflow may consume
    `perform_local_task_action()` for explicit Cancel/Retry controls.
    """
    task_center = task_center_module or importlib.import_module("task_center")
    if not getattr(task_center, "_galaxy_local_task_provider_rows_installed", False):
        original_rows = task_center._task_rows

        def rows_with_local_providers(window, module):
            rows = list(original_rows(window, module))
            rows.extend(local_task_rows())
            return rows

        task_center._task_rows = rows_with_local_providers
        task_center._galaxy_local_task_provider_rows_installed = True

    window_cls = engine_module.EngineWindow
    if not getattr(window_cls, "_galaxy_local_task_provider_bridge_installed", False):
        def history_button_hook(window, _module, history_count: int, text: str) -> str:
            try:
                return f"任务 {len(task_center._task_rows(window, engine_module))}"
            except Exception:
                return text or f"任务 {max(0, int(history_count))}"

        register_history_button_hook(
            window_cls,
            "local-task-providers",
            history_button_hook,
            order=175,
        )
        window_cls._galaxy_local_task_provider_bridge_installed = True
    return window_cls


def run_local_task_provider_self_test() -> None:
    registry = LocalTaskProviderRegistry()
    registry.register(
        "demo",
        label="Demo",
        snapshot=lambda: [
            LocalTaskSnapshot(
                "task-1",
                "running",
                "Demo task",
                "Demo",
                progress_percent=25,
                actions=("cancel",),
            )
        ],
        action=lambda task_id, action: LocalTaskActionResult(task_id == "task-1" and action == "cancel", True, "ok"),
    )
    rows = registry.rows()
    assert len(rows) == 1
    assert rows[0]["state"] == "active"
    assert rows[0]["when"] == "25.0%"
    assert registry.perform_action("demo", "task-1", "cancel").ok is True
