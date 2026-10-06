from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from ai_task_service import AiTaskService  # noqa: E402
from desktop_ai_tasks import (  # noqa: E402
    _shutdown_service,
    install_desktop_ai_tasks,
    run_desktop_ai_tasks_self_test,
)
from desktop_hooks import (  # noqa: E402
    registered_after_build_ui_hooks,
    registered_before_close_hooks,
)


class FakeWindow:
    def __init__(self) -> None:
        self.closed = False

    def close_app(self) -> None:
        self.closed = True


class FakeEngine:
    EngineWindow = FakeWindow


class FakeService(AiTaskService):
    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self.shutdown_args = None

    def snapshot(self):
        return {
            "waiting": [{"id": "a" * 32}],
            "active": [{"id": "b" * 32}],
        }

    def cancel(self, task_id):
        self.cancelled.append(str(task_id))
        return {"state": "cancelled"}

    def shutdown(self, *, cancel_running=False, timeout=5.0):
        self.shutdown_args = (bool(cancel_running), float(timeout))


def run() -> None:
    installed = install_desktop_ai_tasks(FakeEngine)
    assert installed is FakeWindow
    assert getattr(FakeWindow, "_galaxy_desktop_ai_tasks_installed", False) is True
    assert "desktop-ai-tasks" in registered_after_build_ui_hooks(FakeWindow)
    assert "desktop-ai-tasks" in registered_before_close_hooks(FakeWindow)

    install_desktop_ai_tasks(FakeEngine)
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-ai-tasks") == 1
    assert registered_before_close_hooks(FakeWindow).count("desktop-ai-tasks") == 1

    window = FakeWindow()
    service = FakeService()
    window._desktop_ai_task_service = service
    window.close_app()
    assert window.closed is True
    assert service.cancelled == ["a" * 32, "b" * 32]
    assert service.shutdown_args == (True, 1.5)
    assert window._desktop_ai_task_service is None

    # Direct cleanup stays idempotent after close.
    _shutdown_service(window)
    run_desktop_ai_tasks_self_test()

    source = (LOCAL_ENGINE / "desktop_ai_tasks.py").read_text(encoding="utf-8")
    for required in (
        "AiTaskService",
        "submit_text",
        "submit_media_transcript",
        "list_ai_runs",
        "get_ai_run",
        "delete_ai_run",
        "clear_ai_history",
        "register_before_close_hook",
        "threading.Thread",
        "dialog.after(900, refresh_async)",
        "AI Queue & History",
        "Add to Queue",
        "Cancel selected",
    ):
        assert required in source

    # No second queue/history persistence layer may be introduced by the Desktop surface.
    assert "sqlite3" not in source
    assert "requests." not in source
    assert "urllib.request" not in source

    entrypoint = (LOCAL_ENGINE / "entrypoint.py").read_text(encoding="utf-8")
    assert "install_desktop_ai_tasks(engine)" in entrypoint
    assert "run_desktop_ai_tasks_self_test()" in entrypoint


if __name__ == "__main__":
    run()
    print("Desktop AI Queue / History contract passed")
