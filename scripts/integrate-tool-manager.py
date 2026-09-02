from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "local-engine" / "entrypoint.py"


def insert_after(text: str, anchor: str, value: str) -> str:
    if value in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"missing integration anchor: {anchor!r}")
    return text.replace(anchor, anchor + value, 1)


def integrate() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    text = insert_after(
        text,
        "from desktop_runtime import install_desktop_runtime\n",
        "from desktop_tools import install_desktop_tools\n",
    )
    text = insert_after(
        text,
        "from task_center import install_task_center, run_task_center_self_test\n",
        "from tool_manager import install_tool_manager, run_tool_manager_self_test\n",
    )
    text = insert_after(
        text,
        "install_runtime_paths_policy(engine)\n",
        "install_tool_manager(engine)\n",
    )
    text = insert_after(
        text,
        "install_desktop_runtime(engine)\n",
        "install_desktop_tools(engine)\n",
    )
    text = insert_after(
        text,
        '    assert getattr(engine.EngineWindow, "_galaxy_desktop_runtime_installed", False) is True\n',
        '    assert getattr(engine.EngineWindow, "_galaxy_desktop_tools_installed", False) is True\n',
    )
    text = insert_after(
        text,
        '    assert getattr(engine, "_galaxy_runtime_paths_policy_installed", False) is True\n',
        '    assert getattr(engine, "_galaxy_tool_manager_installed", False) is True\n'
        '    assert getattr(engine.EngineWindow, "_galaxy_tool_manager_installed", False) is True\n',
    )
    text = insert_after(
        text,
        "    run_runtime_storage_self_test()\n",
        "    run_tool_manager_self_test()\n",
    )
    ENTRYPOINT.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    integrate()
    print("integrated tool manager")
