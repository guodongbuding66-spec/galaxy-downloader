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
        '_JOB_LINES_ATTR = "_galaxy_job_line_hooks"\n',
        '_JOB_LINES_ATTR = "_galaxy_job_line_hooks"\n_PRESENTER_ATTR = "_galaxy_desktop_presenters"\n',
        "presenter registry attribute",
    )
    replace_once(
        hooks,
        'HookRecord = tuple[int, str, Callable[..., Any]]\n',
        'HookRecord = tuple[int, str, Callable[..., Any]]\nDesktopPresenter = Callable[[Any], None]\nPresenterRecord = tuple[int, str, DesktopPresenter]\n',
        "presenter type declarations",
    )
    anchor = '''def register_job_lines_hook(window_cls: type, name: str, callback: JobLinesHook, *, order: int) -> None:
    _register(window_cls, _JOB_LINES_ATTR, name, callback, order)


def _run(window: Any, attribute: str) -> None:
'''
    replacement = '''def register_job_lines_hook(window_cls: type, name: str, callback: JobLinesHook, *, order: int) -> None:
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


def _run(window: Any, attribute: str) -> None:
'''
    replace_once(hooks, anchor, replacement, "presenter registry implementation")

    extras = Path("local-engine/desktop_extras.py")
    replace_once(
        extras,
        'from desktop_hooks import register_after_build_ui_hook, register_queue_tick_hook, run_job_lines_hooks\n',
        'from desktop_hooks import (\n    register_after_build_ui_hook,\n    register_desktop_presenter,\n    register_queue_tick_hook,\n    run_job_lines_hooks,\n    show_desktop_presenter,\n)\n',
        "extras presenter imports",
    )
    replace_once(
        extras,
        '    ui._render_queue = _augment_queue_rows(ui._render_queue)\n\n    def after_build_ui(window) -> None:\n',
        '    ui._render_queue = _augment_queue_rows(ui._render_queue)\n    register_desktop_presenter(\n        window_cls,\n        "history",\n        "desktop-extras",\n        lambda window: _show_history(window, engine_module),\n        order=110,\n    )\n\n    def after_build_ui(window) -> None:\n',
        "extras history presenter registration",
    )
    replace_once(
        extras,
        '            command=lambda: _show_history(window, engine_module),\n',
        '            command=lambda: show_desktop_presenter(window, "history"),\n',
        "extras history button routing",
    )

    manager = Path("local-engine/desktop_manager.py")
    replace_once(
        manager,
        'from desktop_hooks import register_after_build_ui_hook, register_job_lines_hook\n',
        'from desktop_hooks import (\n    register_after_build_ui_hook,\n    register_desktop_presenter,\n    register_job_lines_hook,\n    show_desktop_presenter,\n)\n',
        "manager presenter imports",
    )
    replace_once(
        manager,
        '    # Existing v0.11 buttons resolve these module globals when clicked, so\n    # replacing them here upgrades the dialog without touching its stable layout.\n    extras._show_history = _show_history_manager\n',
        '    register_desktop_presenter(\n        window_cls, "history", "desktop-manager", lambda window: _show_history_manager(window, engine_module), order=120\n    )\n    register_desktop_presenter(\n        window_cls, "queue", "desktop-manager", lambda window: _show_queue_manager(window, engine_module), order=120\n    )\n    register_desktop_presenter(\n        window_cls, "settings", "desktop-manager", lambda window: _show_settings(window, engine_module), order=120\n    )\n\n',
        "manager presenter registrations",
    )
    replace_once(
        manager,
        '            command=lambda: _show_settings(window, engine_module),\n',
        '            command=lambda: show_desktop_presenter(window, "settings"),\n',
        "manager settings button routing",
    )
    replace_once(
        manager,
        '            command=lambda: _show_queue_manager(window, engine_module),\n',
        '            command=lambda: show_desktop_presenter(window, "queue"),\n',
        "manager queue button routing",
    )

    runtime = Path("local-engine/desktop_runtime.py")
    replace_once(
        runtime,
        'from desktop_hooks import register_after_build_ui_hook, register_job_lines_hook, register_queue_tick_hook\n',
        'from desktop_hooks import (\n    register_after_build_ui_hook,\n    register_desktop_presenter,\n    register_job_lines_hook,\n    register_queue_tick_hook,\n    show_desktop_presenter,\n)\n',
        "runtime presenter imports",
    )
    replace_once(
        runtime,
        '    # The v0.12 settings button performs a late global lookup, so replacing the\n    # module function upgrades the existing button without rebuilding the header.\n    manager._show_settings = _show_settings\n\n',
        '    register_desktop_presenter(\n        window_cls, "settings", "desktop-runtime", lambda window: _show_settings(window, engine_module), order=130\n    )\n\n',
        "runtime settings presenter registration",
    )
    replace_once(
        runtime,
        '            command=lambda: _show_settings(window, engine_module),\n',
        '            command=lambda: show_desktop_presenter(window, "settings"),\n',
        "runtime storage button routing",
    )

    center = Path("local-engine/task_center.py")
    replace_once(
        center,
        'from desktop_hooks import register_after_build_ui_hook\n',
        'from desktop_hooks import register_after_build_ui_hook, register_desktop_presenter\n',
        "task center presenter import",
    )
    replace_once(
        center,
        '    # Existing buttons use late module-global lookups. Repoint them without\n    # changing the already validated queue/history storage implementations.\n    extras._show_history = _show_task_center\n    manager._show_history_manager = _show_task_center\n    manager._show_queue_manager = _show_task_center\n\n',
        '    register_desktop_presenter(\n        window_cls, "history", "task-center", lambda window: _show_task_center(window, engine_module), order=150\n    )\n    register_desktop_presenter(\n        window_cls, "queue", "task-center", lambda window: _show_task_center(window, engine_module, "等待"), order=150\n    )\n\n',
        "task center presenter registrations",
    )
    replace_once(
        center,
        '    def after_build_ui(window) -> None:\n        history_button = getattr(window, "_history_button", None)\n        if history_button is not None:\n            history_button.configure(command=lambda: _show_task_center(window, engine_module))\n        queue_button = getattr(window, "_queue_manager_button", None)\n        if queue_button is not None:\n            queue_button.configure(text="队列", command=lambda: _show_task_center(window, engine_module, "等待"))\n        sync_history_button(window, engine_module, force=True)\n',
        '    def after_build_ui(window) -> None:\n        queue_button = getattr(window, "_queue_manager_button", None)\n        if queue_button is not None:\n            queue_button.configure(text="队列")\n        sync_history_button(window, engine_module, force=True)\n',
        "task center button routing cleanup",
    )

    test = Path("scripts/test-local-desktop-hooks.py")
    replace_once(
        test,
        'def test_single_desktop_method_owner() -> None:\n',
        '''def test_presenter_registry(hooks) -> None:
    class FakeWindow:
        pass

    calls: list[str] = []
    hooks.register_desktop_presenter(FakeWindow, "history", "extras", lambda _window: calls.append("extras"), order=110)
    hooks.register_desktop_presenter(FakeWindow, "history", "manager", lambda _window: calls.append("manager"), order=120)
    hooks.register_desktop_presenter(FakeWindow, "history", "task-center", lambda _window: calls.append("task-center"), order=150)
    hooks.show_desktop_presenter(FakeWindow(), "history")
    assert calls == ["task-center"], calls
    assert hooks.registered_desktop_presenter(FakeWindow, "history") == "task-center"
    assert hooks.registered_desktop_presenter(FakeWindow, "missing") is None


def test_single_desktop_method_owner() -> None:
''',
        "presenter registry test",
    )
    replace_once(
        test,
        '        "extras._job_lines =",\n    )\n',
        '        "extras._job_lines =",\n        "extras._show_history =",\n        "manager._show_settings =",\n        "manager._show_history_manager =",\n        "manager._show_queue_manager =",\n    )\n',
        "presenter takeover guards",
    )
    replace_once(
        test,
        '    assert "register_after_build_ui_hook" in texts["desktop_extras.py"]\n',
        '    assert "register_after_build_ui_hook" in texts["desktop_extras.py"]\n    assert "register_desktop_presenter" in texts["desktop_extras.py"]\n    assert "show_desktop_presenter" in texts["desktop_extras.py"]\n',
        "extras presenter wiring guard",
    )
    replace_once(
        test,
        '    assert "register_job_lines_hook" in texts["desktop_manager.py"]\n',
        '    assert "register_job_lines_hook" in texts["desktop_manager.py"]\n    assert "register_desktop_presenter" in texts["desktop_manager.py"]\n    assert "show_desktop_presenter" in texts["desktop_manager.py"]\n',
        "manager presenter wiring guard",
    )
    replace_once(
        test,
        '    assert "register_job_lines_hook" in texts["desktop_runtime.py"]\n',
        '    assert "register_job_lines_hook" in texts["desktop_runtime.py"]\n    assert "register_desktop_presenter" in texts["desktop_runtime.py"]\n    assert "show_desktop_presenter" in texts["desktop_runtime.py"]\n',
        "runtime presenter wiring guard",
    )
    replace_once(
        test,
        '    assert "register_after_build_ui_hook" in texts["task_center.py"]\n',
        '    assert "register_after_build_ui_hook" in texts["task_center.py"]\n    assert "register_desktop_presenter" in texts["task_center.py"]\n',
        "task center presenter wiring guard",
    )
    replace_once(
        test,
        '    test_job_line_registry(hooks)\n    test_single_desktop_method_owner()\n',
        '    test_job_line_registry(hooks)\n    test_presenter_registry(hooks)\n    test_single_desktop_method_owner()\n',
        "presenter registry test execution",
    )


if __name__ == "__main__":
    main()
