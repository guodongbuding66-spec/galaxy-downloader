from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one {label}, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    hooks = Path("local-engine/desktop_hooks.py")
    replace_once(
        hooks,
        '_PRESENTER_ATTR = "_galaxy_desktop_presenters"\n',
        '_PRESENTER_ATTR = "_galaxy_desktop_presenters"\n_HISTORY_BUTTON_ATTR = "_galaxy_history_button_hooks"\n',
        "history button registry attribute",
    )
    replace_once(
        hooks,
        'PresenterRecord = tuple[int, str, DesktopPresenter]\n',
        'PresenterRecord = tuple[int, str, DesktopPresenter]\nHistoryButtonHook = Callable[[Any, Any, int, str], str]\n',
        "history button hook type",
    )
    anchor = '''def registered_desktop_presenter(window_cls: type, slot: str) -> str | None:
    records = list(_presenter_registry(window_cls).get(str(slot or "").strip(), ()))
    return records[-1][1] if records else None


def _run(window: Any, attribute: str) -> None:
'''
    replacement = '''def registered_desktop_presenter(window_cls: type, slot: str) -> str | None:
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
'''
    replace_once(hooks, anchor, replacement, "history button hook implementation")

    extras = Path("local-engine/desktop_extras.py")
    replace_once(
        extras,
        '    run_job_lines_hooks,\n    show_desktop_presenter,\n',
        '    run_history_button_hooks,\n    run_job_lines_hooks,\n    show_desktop_presenter,\n',
        "history button dispatcher import",
    )
    replace_once(
        extras,
        '    button.configure(text=f"历史 {count}")\n',
        '    text = run_history_button_hooks(window, engine_module, count, f"历史 {count}")\n    button.configure(text=text)\n',
        "history button hook dispatch",
    )

    center = Path("local-engine/task_center.py")
    replace_once(
        center,
        'from desktop_hooks import register_after_build_ui_hook, register_desktop_presenter\n',
        'from desktop_hooks import register_after_build_ui_hook, register_desktop_presenter, register_history_button_hook\n',
        "task center history hook import",
    )
    old_wrapper = '''    original_sync_history = extras._sync_history_button

    def sync_history_button(window, module, *, force: bool = False) -> None:
        original_sync_history(window, module, force=force)
        button = getattr(window, "_history_button", None)
        if button is None:
            return
        try:
            total = len(load_history(module)) + len(_pending_snapshot(window)) + len(_resume_rows(window)) + (1 if bool(getattr(window, "running", False)) else 0)
        except Exception:
            total = 0
        button.configure(text=f"任务 {total}")

    extras._sync_history_button = sync_history_button


'''
    new_hook = '''    def history_button_hook(window, _module, history_count: int, _text: str) -> str:
        try:
            total = history_count + len(_pending_snapshot(window)) + len(_resume_rows(window)) + (1 if bool(getattr(window, "running", False)) else 0)
        except Exception:
            total = history_count
        return f"任务 {total}"

    register_history_button_hook(window_cls, "task-center", history_button_hook, order=150)

'''
    replace_once(center, old_wrapper, new_hook, "task center history sync wrapper")
    replace_once(
        center,
        '        sync_history_button(window, engine_module, force=True)\n',
        '        extras._sync_history_button(window, engine_module, force=True)\n',
        "task center forced history sync",
    )

    test = Path("scripts/test-local-desktop-hooks.py")
    replace_once(
        test,
        'def test_single_desktop_method_owner() -> None:\n',
        '''def test_history_button_registry(hooks) -> None:
    class FakeWindow:
        pass

    calls: list[str] = []

    def first(_window, _module, count, text):
        calls.append("first")
        return f"{text} / {count}"

    def task_center(_window, _module, count, _text):
        calls.append("task-center")
        return f"任务 {count + 3}"

    hooks.register_history_button_hook(FakeWindow, "task-center", task_center, order=150)
    hooks.register_history_button_hook(FakeWindow, "first", first, order=110)
    rendered = hooks.run_history_button_hooks(FakeWindow(), object(), 4, "历史 4")
    assert calls == ["first", "task-center"], calls
    assert rendered == "任务 7", rendered
    assert hooks.registered_history_button_hooks(FakeWindow) == ("first", "task-center")


def test_single_desktop_method_owner() -> None:
''',
        "history button registry test",
    )
    replace_once(
        test,
        '        "manager._show_queue_manager =",\n    )\n',
        '        "manager._show_queue_manager =",\n        "original_sync_history",\n        "extras._sync_history_button =",\n    )\n',
        "history sync takeover guards",
    )
    replace_once(
        test,
        '    assert "show_desktop_presenter" in texts["desktop_extras.py"]\n',
        '    assert "show_desktop_presenter" in texts["desktop_extras.py"]\n    assert "run_history_button_hooks" in texts["desktop_extras.py"]\n',
        "history dispatcher wiring guard",
    )
    replace_once(
        test,
        '    assert "register_desktop_presenter" in texts["task_center.py"]\n',
        '    assert "register_desktop_presenter" in texts["task_center.py"]\n    assert "register_history_button_hook" in texts["task_center.py"]\n',
        "task center history hook wiring guard",
    )
    replace_once(
        test,
        '    test_presenter_registry(hooks)\n    test_single_desktop_method_owner()\n',
        '    test_presenter_registry(hooks)\n    test_history_button_registry(hooks)\n    test_single_desktop_method_owner()\n',
        "history registry test execution",
    )


if __name__ == "__main__":
    main()
