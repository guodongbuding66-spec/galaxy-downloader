from __future__ import annotations

from collections.abc import Callable
from typing import Any

_AFTER_BUILD_ATTR = "_galaxy_after_build_ui_hooks"
_QUEUE_TICK_ATTR = "_galaxy_queue_tick_hooks"

DesktopHook = Callable[[Any], None]
HookRecord = tuple[int, str, DesktopHook]


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


def _register(window_cls: type, attribute: str, name: str, callback: DesktopHook, order: int) -> None:
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


def _run(window: Any, attribute: str) -> None:
    records = list(_registry(type(window), attribute))
    for _order, _name, callback in records:
        callback(window)


def run_after_build_ui_hooks(window: Any) -> None:
    _run(window, _AFTER_BUILD_ATTR)


def run_queue_tick_hooks(window: Any) -> None:
    _run(window, _QUEUE_TICK_ATTR)


def registered_after_build_ui_hooks(window_cls: type) -> tuple[str, ...]:
    return tuple(record[1] for record in _registry(window_cls, _AFTER_BUILD_ATTR))


def registered_queue_tick_hooks(window_cls: type) -> tuple[str, ...]:
    return tuple(record[1] for record in _registry(window_cls, _QUEUE_TICK_ATTR))
