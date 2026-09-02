from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_registry_order_and_identity(hooks) -> None:
    class FakeWindow:
        pass

    calls: list[str] = []

    def middle(_window) -> None:
        calls.append("middle")

    def first(_window) -> None:
        calls.append("first")

    def last(_window) -> None:
        calls.append("last")

    hooks.register_after_build_ui_hook(FakeWindow, "middle", middle, order=120)
    hooks.register_after_build_ui_hook(FakeWindow, "first", first, order=110)
    hooks.register_after_build_ui_hook(FakeWindow, "last", last, order=150)
    hooks.register_after_build_ui_hook(FakeWindow, "middle", middle, order=120)

    window = FakeWindow()
    hooks.run_after_build_ui_hooks(window)
    assert calls == ["first", "middle", "last"], calls
    assert hooks.registered_after_build_ui_hooks(FakeWindow) == ("first", "middle", "last")

    def replacement(_window) -> None:
        pass

    try:
        hooks.register_after_build_ui_hook(FakeWindow, "middle", replacement, order=120)
    except RuntimeError:
        pass
    else:
        raise AssertionError("duplicate hook name with a different callback must fail")


def test_queue_registry_is_separate(hooks) -> None:
    class FakeWindow:
        pass

    calls: list[str] = []
    hooks.register_queue_tick_hook(FakeWindow, "runtime", lambda _window: calls.append("runtime"), order=130)
    hooks.register_queue_tick_hook(FakeWindow, "extras", lambda _window: calls.append("extras"), order=110)
    hooks.run_queue_tick_hooks(FakeWindow())
    assert calls == ["extras", "runtime"], calls
    assert hooks.registered_after_build_ui_hooks(FakeWindow) == ()
    assert hooks.registered_queue_tick_hooks(FakeWindow) == ("extras", "runtime")


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
    class FakeWindow:
        pass

    calls: list[str] = []

    def manager(_window, lines):
        calls.append("manager")
        return [*lines, ("manager", "1")]

    def runtime(_window, lines):
        calls.append("runtime")
        return [*lines, ("runtime", "2")]

    def recovery(_window, lines):
        calls.append("recovery")
        return [(name, "effective" if name == "runtime" else value) for name, value in lines]

    hooks.register_job_lines_hook(FakeWindow, "recovery-display", recovery, order=140)
    hooks.register_job_lines_hook(FakeWindow, "desktop-runtime", runtime, order=130)
    hooks.register_job_lines_hook(FakeWindow, "desktop-manager", manager, order=120)
    rendered = hooks.run_job_lines_hooks(FakeWindow(), [("base", "0")])
    assert calls == ["manager", "runtime", "recovery"], calls
    assert rendered == [("base", "0"), ("manager", "1"), ("runtime", "effective")], rendered
    assert hooks.registered_job_lines_hooks(FakeWindow) == ("desktop-manager", "desktop-runtime", "recovery-display")


def test_presenter_registry(hooks) -> None:
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


def test_history_button_registry(hooks) -> None:
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
    paths = [
        LOCAL_ENGINE / "desktop_ui.py",
        LOCAL_ENGINE / "desktop_extras.py",
        LOCAL_ENGINE / "desktop_manager.py",
        LOCAL_ENGINE / "desktop_runtime.py",
        LOCAL_ENGINE / "task_center.py",
        LOCAL_ENGINE / "recovery_display.py",
    ]
    texts = {path.name: path.read_text(encoding="utf-8") for path in paths}

    forbidden = (
        "original_build = window_cls._build_ui",
        "original_queue_tick = window_cls._galaxy_queue_tick",
        "original_job_lines",
        "extras._job_lines =",
        "extras._show_history =",
        "manager._show_settings =",
        "manager._show_history_manager =",
        "manager._show_queue_manager =",
        "original_sync_history",
        "extras._sync_history_button =",
        "_augment_queue_rows(",
        "ui._render_queue =",
    )
    for filename, text in texts.items():
        for marker in forbidden:
            assert marker not in text, f"{filename} still contains legacy wrapper: {marker}"

    build_owners = sum(text.count("window_cls._build_ui = build_ui") for text in texts.values())
    queue_tick_owners = sum(text.count("window_cls._galaxy_queue_tick = queue_tick") for text in texts.values())
    queue_render_owners = sum(text.count("def _render_queue(") for text in texts.values())
    assert build_owners == 1, f"expected one canonical _build_ui owner, got {build_owners}"
    assert queue_tick_owners == 1, f"expected one canonical _galaxy_queue_tick owner, got {queue_tick_owners}"
    assert queue_render_owners == 1, f"expected one canonical _render_queue owner, got {queue_render_owners}"

    assert "run_after_build_ui_hooks(window)" in texts["desktop_ui.py"]
    assert "run_queue_row_hooks(window, row, queued, index - 1, pending)" in texts["desktop_ui.py"]
    assert "run_queue_tick_hooks(window)" in texts["desktop_ui.py"]
    assert "run_job_lines_hooks(window" in texts["desktop_extras.py"]
    assert "register_after_build_ui_hook" in texts["desktop_extras.py"]
    assert "register_desktop_presenter" in texts["desktop_extras.py"]
    assert "show_desktop_presenter" in texts["desktop_extras.py"]
    assert "run_history_button_hooks" in texts["desktop_extras.py"]
    assert "register_queue_row_hook" in texts["desktop_extras.py"]
    assert "register_queue_tick_hook" in texts["desktop_extras.py"]
    assert "register_after_build_ui_hook" in texts["desktop_manager.py"]
    assert "register_job_lines_hook" in texts["desktop_manager.py"]
    assert "register_desktop_presenter" in texts["desktop_manager.py"]
    assert "show_desktop_presenter" in texts["desktop_manager.py"]
    assert "register_after_build_ui_hook" in texts["desktop_runtime.py"]
    assert "register_queue_tick_hook" in texts["desktop_runtime.py"]
    assert "register_job_lines_hook" in texts["desktop_runtime.py"]
    assert "register_desktop_presenter" in texts["desktop_runtime.py"]
    assert "show_desktop_presenter" in texts["desktop_runtime.py"]
    assert "register_after_build_ui_hook" in texts["task_center.py"]
    assert "register_desktop_presenter" in texts["task_center.py"]
    assert "register_history_button_hook" in texts["task_center.py"]
    assert "register_job_lines_hook" in texts["recovery_display.py"]


def main() -> None:
    hooks = load_module("galaxy_desktop_hooks_test", LOCAL_ENGINE / "desktop_hooks.py")
    test_registry_order_and_identity(hooks)
    test_queue_registry_is_separate(hooks)
    test_queue_row_registry(hooks)
    test_job_line_registry(hooks)
    test_presenter_registry(hooks)
    test_history_button_registry(hooks)
    test_single_desktop_method_owner()
    print("Local Engine desktop hook architecture tests passed")


if __name__ == "__main__":
    main()
