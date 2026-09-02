from __future__ import annotations

from collections.abc import Callable
from typing import Any

_AFTER_BUILD_ATTR = "_galaxy_after_build_ui_hooks"
_QUEUE_TICK_ATTR = "_galaxy_queue_tick_hooks"
_JOB_LINES_ATTR = "_galaxy_job_line_hooks"
_PRESENTER_ATTR = "_galaxy_desktop_presenters"
_HISTORY_BUTTON_ATTR = "_galaxy_history_button_hooks"

DesktopHook = Callable[[Any], None]
JobLines = list[tuple[str, str]]
JobLinesHook = Callable[[Any, JobLines], JobLines]
HookRecord = tuple[int, str, Callable[..., Any]]
DesktopPresenter = Callable[[Any], None]
PresenterRecord = tuple[int, str, DesktopPresenter]
HistoryButtonHook = Callable[[Any, Any, int, str], str]


def _registry(window_cls: type, attribute: str) -> list[HookRecord]:
    """Return a registry owned by this exact EngineWindow class.

    Using ``__dict__`` avoids accidentally sharing a mutable inherited registry
    if a test or future platform wrapper subclasses EngineWindow.
    """
    value = window_cls.__dict__.get(attribute)
    if value is None:
        value = []
        setattr(window_cls, attribute, value)
    return value


def _register(window_cls: type, attribute: str, name: str, callback: Callable[..., Any], order: int) -> None:
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("desktop hook name must not be empty")
    if not callable(callback):
        raise TypeError(f"desktop hook {clean_name!r} must be callable")

    records = _registry(window_cls, attribute)
    existing = next((record for record in records if record[1] == clean_name), None)
    if existing is not None:
        if existing[0] == int(order) and existing[2] is callback:
            return
        raise RuntimeError(f"desktop hook {clean_name!r} is already registered")

    records.append((int(order), clean_name, callback))
    records.sort(key=lambda record: (record[0], record[1]))


def register_after_build_ui_hook(window_cls: type, name: str, callback: DesktopHook, *, order: int) -> None:
    _register(window_cls, _AFTER_BUILD_ATTR, name, callback, order)


def register_queue_tick_hook(window_cls: type, name: str, callback: DesktopHook, *, order: int) -> None:
    _register(window_cls, _QUEUE_TICK_ATTR, name, callback, order)


def register_job_lines_hook(window_cls: type, name: str, callback: JobLinesHook, *, order: int) -> None:
    _register(window_cls, _JOB_LINES_ATTR, name, callback, order)


def _presenter_registry(window_cls: type) -> dict[str, list[PresenterRecord]]:
    value = window_cls.__dict__.get(_PRESENTER_ATTR)
    if value is None:
        value = {}
        setattr(window_cls, _PRESENTER_ATTR, value)
    return value


def register_desktop_presenter(
    window_cls: type,
    slot: str,
    name: str,
    callback: DesktopPresenter,
    *,
    order: int,
) -> None:
    clean_slot = str(slot or "").strip()
    clean_name = str(name or "").strip()
    if not clean_slot:
        raise ValueError("desktop presenter slot must not be empty")
    if not clean_name:
        raise ValueError("desktop presenter name must not be empty")
    if not callable(callback):
        raise TypeError(f"desktop presenter {clean_name!r} must be callable")

    records = _presenter_registry(window_cls).setdefault(clean_slot, [])
    existing = next((record for record in records if record[1] == clean_name), None)
    if existing is not None:
        if existing[0] == int(order) and existing[2] is callback:
            return
        raise RuntimeError(f"desktop presenter {clean_slot}:{clean_name} is already registered")
    records.append((int(order), clean_name, callback))
    records.sort(key=lambda record: (record[0], record[1]))


def show_desktop_presenter(window: Any, slot: str) -> None:
    clean_slot = str(slot or "").strip()
    records = list(_presenter_registry(type(window)).get(clean_slot, ()))
    if not records:
        raise RuntimeError(f"desktop presenter slot {clean_slot!r} is not registered")
    records[-1][2](window)


def registered_desktop_presenter(window_cls: type, slot: str) -> str | None:
    records = list(_presenter_registry(window_cls).get(str(slot or "").strip(), ()))
    return records[-1][1] if records else None


def register_history_button_hook(window_cls: type, name: str, callback: HistoryButtonHook, *, order: int) -> None:
    _register(window_cls, _HISTORY_BUTTON_ATTR, name, callback, order)


def run_history_button_hooks(window: Any, engine_module: Any, history_count: int, text: str) -> str:
    rendered = str(text)
    for _order, name, callback in list(_registry(type(window), _HISTORY_BUTTON_ATTR)):
        next_text = callback(window, engine_module, int(history_count), rendered)
        if not isinstance(next_text, str):
            raise TypeError(f"desktop history-button hook {name!r} must return a string")
        rendered = next_text
    return rendered


def registered_history_button_hooks(window_cls: type) -> tuple[str, ...]:
    return tuple(record[1] for record in _registry(window_cls, _HISTORY_BUTTON_ATTR))


def _run(window: Any, attribute: str) -> None:
    records = list(_registry(type(window), attribute))
    for _order, _name, callback in records:
        callback(window)


def run_after_build_ui_hooks(window: Any) -> None:
    _run(window, _AFTER_BUILD_ATTR)


def run_queue_tick_hooks(window: Any) -> None:
    _run(window, _QUEUE_TICK_ATTR)


def run_job_lines_hooks(window: Any, lines: JobLines) -> JobLines:
    rendered = list(lines)
    for _order, name, callback in list(_registry(type(window), _JOB_LINES_ATTR)):
        next_lines = callback(window, list(rendered))
        if not isinstance(next_lines, list):
            raise TypeError(f"desktop job-line hook {name!r} must return a list")
        rendered = next_lines
    return rendered


def registered_after_build_ui_hooks(window_cls: type) -> tuple[str, ...]:
    return tuple(record[1] for record in _registry(window_cls, _AFTER_BUILD_ATTR))


def registered_queue_tick_hooks(window_cls: type) -> tuple[str, ...]:
    return tuple(record[1] for record in _registry(window_cls, _QUEUE_TICK_ATTR))


def registered_job_lines_hooks(window_cls: type) -> tuple[str, ...]:
    return tuple(record[1] for record in _registry(window_cls, _JOB_LINES_ATTR))
