from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, got {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


hooks = ROOT / "local-engine" / "desktop_hooks.py"
replace_once(
    hooks,
    '_HISTORY_BUTTON_ATTR = "_galaxy_history_button_hooks"\n',
    '_HISTORY_BUTTON_ATTR = "_galaxy_history_button_hooks"\n_QUEUE_ROW_ATTR = "_galaxy_queue_row_hooks"\n',
)
replace_once(
    hooks,
    'HistoryButtonHook = Callable[[Any, Any, int, str], str]\n',
    'HistoryButtonHook = Callable[[Any, Any, int, str], str]\nQueueRowHook = Callable[[Any, Any, Any, int, list[Any]], None]\n',
)
replace_once(
    hooks,
    'def registered_history_button_hooks(window_cls: type) -> tuple[str, ...]:\n    return tuple(record[1] for record in _registry(window_cls, _HISTORY_BUTTON_ATTR))\n\n\ndef _run(window: Any, attribute: str) -> None:\n',
    '''def registered_history_button_hooks(window_cls: type) -> tuple[str, ...]:
    return tuple(record[1] for record in _registry(window_cls, _HISTORY_BUTTON_ATTR))


def register_queue_row_hook(window_cls: type, name: str, callback: QueueRowHook, *, order: int) -> None:
    _register(window_cls, _QUEUE_ROW_ATTR, name, callback, order)


def run_queue_row_hooks(window: Any, row: Any, queued: Any, index: int, pending: list[Any]) -> None:
    for _order, _name, callback in list(_registry(type(window), _QUEUE_ROW_ATTR)):
        callback(window, row, queued, int(index), pending)


def registered_queue_row_hooks(window_cls: type) -> tuple[str, ...]:
    return tuple(record[1] for record in _registry(window_cls, _QUEUE_ROW_ATTR))


def _run(window: Any, attribute: str) -> None:
''',
)

ui = ROOT / "local-engine" / "desktop_ui.py"
replace_once(
    ui,
    'from desktop_hooks import run_after_build_ui_hooks, run_queue_tick_hooks\n',
    'from desktop_hooks import run_after_build_ui_hooks, run_queue_row_hooks, run_queue_tick_hooks\n',
)
replace_once(
    ui,
    '            cancel.pack(side="right", padx=(5, 0))\n    if len(pending) > 8:\n',
    '            cancel.pack(side="right", padx=(5, 0))\n        run_queue_row_hooks(window, row, queued, index - 1, pending)\n    if len(pending) > 8:\n',
)

extras = ROOT / "local-engine" / "desktop_extras.py"
replace_once(
    extras,
    '    register_queue_tick_hook,\n',
    '    register_queue_row_hook,\n    register_queue_tick_hook,\n',
)
start = '''def _augment_queue_rows(original_render: Callable[[Any, list[Any]], None]):
    def render(window, pending: list[Any]) -> None:
        original_render(window, pending)
        if len(pending) < 2:
            return
        panel = window._queue_panel
        rows = [child for child in panel.winfo_children() if isinstance(child, tk.Frame)]
        for index, queued in enumerate(pending[:8]):
            if index >= len(rows):
                break
            row = rows[index]
            job_id = str(getattr(queued, "job_id", "") or "")
            if not job_id:
                continue
            down_disabled = index >= len(pending) - 1
            _tiny_button(
                row,
                "↓",
                lambda value=job_id: getattr(window, "move_queued_job")(value, 1),
                disabled=down_disabled,
            ).pack(side="right", padx=(1, 0))
            _tiny_button(
                row,
                "↑",
                lambda value=job_id: getattr(window, "move_queued_job")(value, -1),
                disabled=index == 0,
            ).pack(side="right", padx=(5, 0))

    return render


'''
replace_once(extras, start, '')
replace_once(
    extras,
    '    ui._render_queue = _augment_queue_rows(ui._render_queue)\n    register_desktop_presenter(\n',
    '''    def queue_row_hook(window, row, queued, index: int, pending: list[Any]) -> None:
        if len(pending) < 2:
            return
        job_id = str(getattr(queued, "job_id", "") or "")
        if not job_id:
            return
        down_disabled = index >= len(pending) - 1
        _tiny_button(
            row,
            "↓",
            lambda value=job_id: getattr(window, "move_queued_job")(value, 1),
            disabled=down_disabled,
        ).pack(side="right", padx=(1, 0))
        _tiny_button(
            row,
            "↑",
            lambda value=job_id: getattr(window, "move_queued_job")(value, -1),
            disabled=index == 0,
        ).pack(side="right", padx=(5, 0))

    register_queue_row_hook(window_cls, "desktop-extras", queue_row_hook, order=110)
    register_desktop_presenter(
''',
)

test = ROOT / "scripts" / "test-local-desktop-hooks.py"
replace_once(
    test,
    '\n\ndef test_job_line_registry(hooks) -> None:\n',
    '''

def test_queue_row_registry(hooks) -> None:
    class FakeWindow:
        pass

    calls: list[tuple[str, int]] = []

    def first(_window, _row, _queued, index, _pending) -> None:
        calls.append(("first", index))

    def second(_window, _row, _queued, index, _pending) -> None:
        calls.append(("second", index))

    hooks.register_queue_row_hook(FakeWindow, "second", second, order=120)
    hooks.register_queue_row_hook(FakeWindow, "first", first, order=110)
    pending = [object(), object(), object()]
    hooks.run_queue_row_hooks(FakeWindow(), object(), pending[1], 1, pending)
    assert calls == [("first", 1), ("second", 1)], calls
    assert hooks.registered_queue_row_hooks(FakeWindow) == ("first", "second")


def test_job_line_registry(hooks) -> None:
''',
)
replace_once(
    test,
    '        "extras._sync_history_button =",\n',
    '        "extras._sync_history_button =",\n        "_augment_queue_rows(",\n        "ui._render_queue =",\n',
)
replace_once(
    test,
    '    queue_tick_owners = sum(text.count("window_cls._galaxy_queue_tick = queue_tick") for text in texts.values())\n    assert build_owners == 1, f"expected one canonical _build_ui owner, got {build_owners}"\n    assert queue_tick_owners == 1, f"expected one canonical _galaxy_queue_tick owner, got {queue_tick_owners}"\n\n    assert "run_after_build_ui_hooks(window)" in texts["desktop_ui.py"]\n',
    '    queue_tick_owners = sum(text.count("window_cls._galaxy_queue_tick = queue_tick") for text in texts.values())\n    queue_render_owners = sum(text.count("def _render_queue(") for text in texts.values())\n    assert build_owners == 1, f"expected one canonical _build_ui owner, got {build_owners}"\n    assert queue_tick_owners == 1, f"expected one canonical _galaxy_queue_tick owner, got {queue_tick_owners}"\n    assert queue_render_owners == 1, f"expected one canonical _render_queue owner, got {queue_render_owners}"\n\n    assert "run_after_build_ui_hooks(window)" in texts["desktop_ui.py"]\n    assert "run_queue_row_hooks(window, row, queued, index - 1, pending)" in texts["desktop_ui.py"]\n',
)
replace_once(
    test,
    '    assert "register_queue_tick_hook" in texts["desktop_extras.py"]\n',
    '    assert "register_queue_row_hook" in texts["desktop_extras.py"]\n    assert "register_queue_tick_hook" in texts["desktop_extras.py"]\n',
)
replace_once(
    test,
    '    test_queue_registry_is_separate(hooks)\n    test_job_line_registry(hooks)\n',
    '    test_queue_registry_is_separate(hooks)\n    test_queue_row_registry(hooks)\n    test_job_line_registry(hooks)\n',
)

print("queue renderer hook convergence applied")
