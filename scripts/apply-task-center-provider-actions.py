from __future__ import annotations

from pathlib import Path

PATH = Path("local-engine/task_center.py")
text = PATH.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
'''        if active_pause_button is not None:
            pause_event = getattr(window, "pause_event", None)
            can_pause = bool(one and one.get("kind") == "active" and getattr(window, "running", False))
            if pause_event is not None and pause_event.is_set():
                can_pause = False
            active_pause_button.state(["!disabled"] if can_pause else ["disabled"])
        if resume_button is not None:
            resume_button.state(["!disabled"] if resume and not bool(getattr(window, "running", False)) else ["disabled"])
''',
'''        if active_pause_button is not None:
            provider_can_pause = bool(provider and "pause" in provider_actions)
            pause_event = getattr(window, "pause_event", None)
            can_pause = provider_can_pause or bool(one and one.get("kind") == "active" and getattr(window, "running", False))
            if not provider_can_pause and pause_event is not None and pause_event.is_set():
                can_pause = False
            active_pause_button.configure(text="暂停任务" if provider_can_pause else "暂停当前")
            active_pause_button.state(["!disabled"] if can_pause else ["disabled"])
        if resume_button is not None:
            provider_can_resume = bool(provider and "resume" in provider_actions)
            can_resume = provider_can_resume or bool(resume and not bool(getattr(window, "running", False)))
            resume_button.state(["!disabled"] if can_resume else ["disabled"])
''',
"action-state routing",
)

replace_once(
'''    def pause_active_selected() -> None:
        rows = selected_rows()
        pause = getattr(window, "pause_active_job", None)
        if len(rows) == 1 and rows[0].get("kind") == "active" and callable(pause):
            if pause():
                window.set_status("Pausing", "正在保存可恢复状态并停止到安全检查点…")
            refresh(force=True)

    def resume_selected() -> None:
        row = selected_resume()
        resume = getattr(window, "resume_job", None)
        if row and callable(resume):
            job_id = str(row.get("jobId") or "")
            if job_id and resume(job_id):
                refresh(force=True)
            elif job_id:
                messagebox.showwarning(engine_module.APP_NAME, "当前无法继续这个任务；请确认没有其他下载正在运行。", parent=dialog)
''',
'''    def pause_active_selected() -> None:
        provider = selected_provider()
        if provider is not None and "pause" in tuple(provider.get("providerActions") or ()):
            run_provider_action("pause")
            return
        rows = selected_rows()
        pause = getattr(window, "pause_active_job", None)
        if len(rows) == 1 and rows[0].get("kind") == "active" and callable(pause):
            if pause():
                window.set_status("Pausing", "正在保存可恢复状态并停止到安全检查点…")
            refresh(force=True)

    def resume_selected() -> None:
        provider = selected_provider()
        if provider is not None and "resume" in tuple(provider.get("providerActions") or ()):
            run_provider_action("resume")
            return
        row = selected_resume()
        resume = getattr(window, "resume_job", None)
        if row and callable(resume):
            job_id = str(row.get("jobId") or "")
            if job_id and resume(job_id):
                refresh(force=True)
            elif job_id:
                messagebox.showwarning(engine_module.APP_NAME, "当前无法继续这个任务；请确认没有其他下载正在运行。", parent=dialog)
''',
"pause/resume handlers",
)

replace_once(
'''        if rows[0].get("kind") == "resume":
            resume_selected()
        elif rows[0].get("kind") == "history":
''',
'''        if rows[0].get("kind") == "provider" and "resume" in tuple(rows[0].get("providerActions") or ()):
            resume_selected()
        elif rows[0].get("kind") == "resume":
            resume_selected()
        elif rows[0].get("kind") == "history":
''',
"double-click resume routing",
)

replace_once(
'''    provider = {
        "kind": "provider",
        "state": "cancelled",
        "sourceHost": "gallery-dl",
        "label": "Gallery · example.com",
        "providerActions": ("retry",),
    }
    assert _matches_filter(provider, "cancelled", "gallery") is True
''',
'''    provider = {
        "kind": "provider",
        "state": "paused",
        "sourceHost": "aria2",
        "label": "Magnet 下载",
        "providerActions": ("resume", "cancel"),
    }
    assert _matches_filter(provider, "paused", "aria2") is True
    assert "resume" in provider["providerActions"]
''',
"provider self-test fixture",
)

PATH.write_text(text, encoding="utf-8")
print("task_center provider pause/resume routing patched")
