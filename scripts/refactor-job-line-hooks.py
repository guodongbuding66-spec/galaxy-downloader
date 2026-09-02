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
        '_AFTER_BUILD_ATTR = "_galaxy_after_build_ui_hooks"\n_QUEUE_TICK_ATTR = "_galaxy_queue_tick_hooks"\n\nDesktopHook = Callable[[Any], None]\nHookRecord = tuple[int, str, DesktopHook]\n',
        '_AFTER_BUILD_ATTR = "_galaxy_after_build_ui_hooks"\n_QUEUE_TICK_ATTR = "_galaxy_queue_tick_hooks"\n_JOB_LINES_ATTR = "_galaxy_job_line_hooks"\n\nDesktopHook = Callable[[Any], None]\nJobLines = list[tuple[str, str]]\nJobLinesHook = Callable[[Any, JobLines], JobLines]\nHookRecord = tuple[int, str, Callable[..., Any]]\n',
        "job-line registry declarations",
    )
    replace_once(
        hooks,
        'def _register(window_cls: type, attribute: str, name: str, callback: DesktopHook, order: int) -> None:\n',
        'def _register(window_cls: type, attribute: str, name: str, callback: Callable[..., Any], order: int) -> None:\n',
        "generic hook callback signature",
    )
    replace_once(
        hooks,
        'def register_queue_tick_hook(window_cls: type, name: str, callback: DesktopHook, *, order: int) -> None:\n    _register(window_cls, _QUEUE_TICK_ATTR, name, callback, order)\n\n\ndef _run(window: Any, attribute: str) -> None:\n',
        'def register_queue_tick_hook(window_cls: type, name: str, callback: DesktopHook, *, order: int) -> None:\n    _register(window_cls, _QUEUE_TICK_ATTR, name, callback, order)\n\n\ndef register_job_lines_hook(window_cls: type, name: str, callback: JobLinesHook, *, order: int) -> None:\n    _register(window_cls, _JOB_LINES_ATTR, name, callback, order)\n\n\ndef _run(window: Any, attribute: str) -> None:\n',
        "job-line hook registration",
    )
    replace_once(
        hooks,
        'def run_queue_tick_hooks(window: Any) -> None:\n    _run(window, _QUEUE_TICK_ATTR)\n\n\ndef registered_after_build_ui_hooks(window_cls: type) -> tuple[str, ...]:\n',
        'def run_queue_tick_hooks(window: Any) -> None:\n    _run(window, _QUEUE_TICK_ATTR)\n\n\ndef run_job_lines_hooks(window: Any, lines: JobLines) -> JobLines:\n    rendered = list(lines)\n    for _order, name, callback in list(_registry(type(window), _JOB_LINES_ATTR)):\n        next_lines = callback(window, list(rendered))\n        if not isinstance(next_lines, list):\n            raise TypeError(f"desktop job-line hook {name!r} must return a list")\n        rendered = next_lines\n    return rendered\n\n\ndef registered_after_build_ui_hooks(window_cls: type) -> tuple[str, ...]:\n',
        "job-line hook dispatcher",
    )
    replace_once(
        hooks,
        'def registered_queue_tick_hooks(window_cls: type) -> tuple[str, ...]:\n    return tuple(record[1] for record in _registry(window_cls, _QUEUE_TICK_ATTR))\n',
        'def registered_queue_tick_hooks(window_cls: type) -> tuple[str, ...]:\n    return tuple(record[1] for record in _registry(window_cls, _QUEUE_TICK_ATTR))\n\n\ndef registered_job_lines_hooks(window_cls: type) -> tuple[str, ...]:\n    return tuple(record[1] for record in _registry(window_cls, _JOB_LINES_ATTR))\n',
        "job-line registry introspection",
    )

    extras = Path("local-engine/desktop_extras.py")
    replace_once(
        extras,
        'from desktop_hooks import register_after_build_ui_hook, register_queue_tick_hook\n',
        'from desktop_hooks import register_after_build_ui_hook, register_queue_tick_hook, run_job_lines_hooks\n',
        "extras job-line dispatcher import",
    )
    replace_once(
        extras,
        '    if job is None:\n        return [("状态", "当前没有任务")]\n',
        '    if job is None:\n        return run_job_lines_hooks(window, [("状态", "当前没有任务")])\n',
        "empty job-line dispatch",
    )
    old_base = '''    return [
        ("来源", source),
        ("视频画质", str(getattr(job, "video_quality", "best") or "best")),
        ("音频质量", str(getattr(job, "audio_quality", "best") or "best")),
        ("包含音频", "是" if bool(getattr(job, "include_audio", True)) else "否"),
        ("字幕", "是" if bool(getattr(job, "include_subtitle", False)) else "否"),
        ("字幕来源", str(getattr(job, "subtitle_mode", "both") or "both")),
        ("字幕语言", subtitle_languages),
        ("音轨语言", audio_languages),
        ("片段", segment),
        ("章节拆分", "开启" if bool(getattr(job, "split_chapters", False)) else "关闭"),
        ("SponsorBlock", sponsors),
        ("aria2c", "开启" if bool(getattr(job, "use_aria2c", False)) else "关闭"),
        ("集合模式", str(getattr(job, "collection_mode", "single") or "single")),
    ]
'''
    new_base = old_base.replace("    return [", "    lines = [") + "    return run_job_lines_hooks(window, lines)\n"
    replace_once(extras, old_base, new_base, "base job-line dispatch")

    manager = Path("local-engine/desktop_manager.py")
    replace_once(manager, "from typing import Any, Callable\n", "from typing import Any\n", "manager callable import cleanup")
    replace_once(
        manager,
        "from desktop_hooks import register_after_build_ui_hook\n",
        "from desktop_hooks import register_after_build_ui_hook, register_job_lines_hook\n",
        "manager job-line hook import",
    )
    old_manager = '''    original_job_lines: Callable[[Any], list[tuple[str, str]]] = extras._job_lines

    def job_lines(window) -> list[tuple[str, str]]:
        lines = original_job_lines(window)
        job = getattr(window, "job", None)
        if job is None:
            return lines
        preferences = load_workspace_preferences(engine_module)
        style_label = STYLE_LABELS.get(str(preferences["outputNameStyle"]), str(preferences["outputNameStyle"]))
        lines.extend(
            [
                ("下载 Archive", "开启" if bool(getattr(job, "skip_previously_downloaded", False)) else "关闭"),
                ("文件命名", style_label),
                ("按来源整理", "开启" if bool(preferences["organizeBySource"]) else "关闭"),
                ("输出模板", output_template(engine_module, job)),
            ]
        )
        return lines

    extras._job_lines = job_lines
'''
    new_manager = '''    def job_lines_hook(window, lines: list[tuple[str, str]]) -> list[tuple[str, str]]:
        job = getattr(window, "job", None)
        if job is None:
            return lines
        preferences = load_workspace_preferences(engine_module)
        style_label = STYLE_LABELS.get(str(preferences["outputNameStyle"]), str(preferences["outputNameStyle"]))
        return [
            *lines,
            ("下载 Archive", "开启" if bool(getattr(job, "skip_previously_downloaded", False)) else "关闭"),
            ("文件命名", style_label),
            ("按来源整理", "开启" if bool(preferences["organizeBySource"]) else "关闭"),
            ("输出模板", output_template(engine_module, job)),
        ]

    register_job_lines_hook(window_cls, "desktop-manager", job_lines_hook, order=120)
'''
    replace_once(manager, old_manager, new_manager, "manager job-line wrapper")

    runtime = Path("local-engine/desktop_runtime.py")
    replace_once(runtime, "from typing import Any, Callable\n", "from typing import Any\n", "runtime callable import cleanup")
    replace_once(
        runtime,
        "from desktop_hooks import register_after_build_ui_hook, register_queue_tick_hook\n",
        "from desktop_hooks import register_after_build_ui_hook, register_job_lines_hook, register_queue_tick_hook\n",
        "runtime job-line hook import",
    )
    old_runtime = '''    original_job_lines: Callable[[Any], list[tuple[str, str]]] = extras._job_lines

    def job_lines(window) -> list[tuple[str, str]]:
        lines = original_job_lines(window)
        if getattr(window, "job", None) is None:
            return lines
        preferences = load_workspace_preferences(engine_module)
        retry_key = str(preferences["networkRetryProfile"])
        rate = int(preferences["rateLimitMbps"])
        lines.extend(
            [
                ("网络重试", RETRY_LABELS.get(retry_key, retry_key)),
                ("并发分片", str(preferences["concurrentFragments"])),
                ("速度上限", RATE_LABELS.get(rate, f"{rate} Mbps")),
            ]
        )
        return lines

    extras._job_lines = job_lines
'''
    new_runtime = '''    def job_lines_hook(window, lines: list[tuple[str, str]]) -> list[tuple[str, str]]:
        if getattr(window, "job", None) is None:
            return lines
        preferences = load_workspace_preferences(engine_module)
        retry_key = str(preferences["networkRetryProfile"])
        rate = int(preferences["rateLimitMbps"])
        return [
            *lines,
            ("网络重试", RETRY_LABELS.get(retry_key, retry_key)),
            ("并发分片", str(preferences["concurrentFragments"])),
            ("速度上限", RATE_LABELS.get(rate, f"{rate} Mbps")),
        ]

    register_job_lines_hook(window_cls, "desktop-runtime", job_lines_hook, order=130)
'''
    replace_once(runtime, old_runtime, new_runtime, "runtime job-line wrapper")

    recovery = Path("local-engine/recovery_display.py")
    replace_once(
        recovery,
        "from typing import Any, Callable\n\nimport desktop_extras as extras\n",
        "from typing import Any\n\nfrom desktop_hooks import register_job_lines_hook\n",
        "recovery imports",
    )
    replace_once(
        recovery,
        '''    original_job_lines: Callable[[Any], list[tuple[str, str]]] = extras._job_lines

    def job_lines(window) -> list[tuple[str, str]]:
        lines = original_job_lines(window)
        job = getattr(window, "job", None)
        if job is None:
            return lines
''',
        '''    def job_lines_hook(window, lines: list[tuple[str, str]]) -> list[tuple[str, str]]:
        job = getattr(window, "job", None)
        if job is None:
            return lines
''',
        "recovery job-line wrapper start",
    )
    replace_once(
        recovery,
        '    extras._job_lines = job_lines\n    window_cls._galaxy_recovery_display_installed = True\n',
        '    register_job_lines_hook(window_cls, "recovery-display", job_lines_hook, order=140)\n    window_cls._galaxy_recovery_display_installed = True\n',
        "recovery job-line hook registration",
    )

    test = Path("scripts/test-local-desktop-hooks.py")
    replace_once(
        test,
        "def test_single_desktop_method_owner() -> None:\n",
        '''def test_job_line_registry(hooks) -> None:
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


def test_single_desktop_method_owner() -> None:
''',
        "job-line registry test",
    )
    replace_once(
        test,
        '        LOCAL_ENGINE / "task_center.py",\n    ]\n',
        '        LOCAL_ENGINE / "task_center.py",\n        LOCAL_ENGINE / "recovery_display.py",\n    ]\n',
        "recovery display architecture scan",
    )
    replace_once(
        test,
        '    forbidden = (\n        "original_build = window_cls._build_ui",\n        "original_queue_tick = window_cls._galaxy_queue_tick",\n    )\n',
        '    forbidden = (\n        "original_build = window_cls._build_ui",\n        "original_queue_tick = window_cls._galaxy_queue_tick",\n        "original_job_lines",\n        "extras._job_lines =",\n    )\n',
        "job-line takeover guards",
    )
    replace_once(
        test,
        "    test_queue_registry_is_separate(hooks)\n    test_single_desktop_method_owner()\n",
        "    test_queue_registry_is_separate(hooks)\n    test_job_line_registry(hooks)\n    test_single_desktop_method_owner()\n",
        "job-line registry test execution",
    )


if __name__ == "__main__":
    main()
