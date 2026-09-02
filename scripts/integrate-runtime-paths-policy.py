from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "local-engine" / "entrypoint.py"
MARKER = "install_runtime_paths_policy(engine)"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"integration anchor missing: {label}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("runtime paths policy already integrated")
        return

    text = replace_once(
        text,
        "from runtime_health import install_runtime_health, run_runtime_health_self_test\n",
        "from runtime_health import install_runtime_health, run_runtime_health_self_test\n"
        "from runtime_paths_policy import (\n"
        "    install_runtime_paths_policy,\n"
        "    run_runtime_paths_policy_self_test,\n"
        ")\n",
        "runtime path import",
    )
    text = replace_once(
        text,
        "# final Job type; queue/history/runtime policies wrap execution; presentation is\n"
        "# installed last before the first Tk instance exists.\n"
        "install_archive_policy(engine)\n",
        "# final Job type; queue/history/runtime policies wrap execution; presentation is\n"
        "# installed last before the first Tk instance exists. Runtime paths are installed\n"
        "# first so every later policy can resolve mutable storage without assuming Windows.\n"
        "install_runtime_paths_policy(engine)\n"
        "install_archive_policy(engine)\n",
        "runtime path installation",
    )
    text = replace_once(
        text,
        '    assert getattr(engine, "_galaxy_archive_policy_installed", False) is True\n',
        '    assert getattr(engine, "_galaxy_runtime_paths_policy_installed", False) is True\n'
        '    assert getattr(engine.EngineWindow, "_galaxy_runtime_paths_policy_installed", False) is True\n'
        '    assert getattr(engine, "_galaxy_archive_policy_installed", False) is True\n',
        "runtime path install assertion",
    )
    text = replace_once(
        text,
        "    run_runtime_health_self_test()\n    run_task_center_self_test()\n",
        "    run_runtime_health_self_test()\n"
        "    run_runtime_paths_policy_self_test()\n"
        "    run_task_center_self_test()\n",
        "runtime path self-test",
    )

    TARGET.write_text(text, encoding="utf-8")
    print("integrated runtime paths policy")


if __name__ == "__main__":
    main()
