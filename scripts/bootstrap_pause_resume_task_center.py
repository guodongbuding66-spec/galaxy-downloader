from __future__ import annotations

from pathlib import Path


def patch_entrypoint() -> None:
    path = Path("local-engine/entrypoint.py")
    text = path.read_text(encoding="utf-8")

    def replace_once(old: str, new: str) -> None:
        nonlocal text
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"expected one entrypoint target, got {count}: {old[:120]!r}")
        text = text.replace(old, new, 1)

    replace_once(
        "from pause_resume_policy import install_pause_resume_policy, run_pause_resume_self_test\n",
        "from pause_resume_policy import install_pause_resume_policy, run_pause_resume_self_test\n"
        "from resume_bridge import PauseResumeLocalBridge, install_resume_bridge, run_resume_bridge_self_test\n",
    )
    replace_once(
        "install_pause_resume_policy(engine)\ninstall_job_queue_policy(engine)\ninstall_queue_controls(engine)\n",
        "install_pause_resume_policy(engine)\n"
        "install_job_queue_policy(engine)\n"
        "install_resume_bridge(engine)\n"
        "install_queue_controls(engine)\n",
    )
    replace_once(
        '    assert getattr(engine, "_galaxy_pause_resume_installed", False) is True\n',
        '    assert getattr(engine, "_galaxy_pause_resume_installed", False) is True\n'
        '    assert getattr(engine, "_galaxy_resume_bridge_installed", False) is True\n',
    )
    replace_once(
        "    assert engine.LocalBridge is StructuredLocalBridge\n",
        "    assert issubclass(PauseResumeLocalBridge, StructuredLocalBridge)\n"
        "    assert engine.LocalBridge is PauseResumeLocalBridge\n",
    )
    replace_once(
        "    run_pause_resume_self_test()\n",
        "    run_pause_resume_self_test()\n"
        "    run_resume_bridge_self_test()\n",
    )
    path.write_text(text, encoding="utf-8")


def patch_task_center() -> None:
    path = Path("local-engine/task_center.py")
    text = path.read_text(encoding="utf-8")

    def replace_once(old: str, new: str) -> None:
        nonlocal text
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"expected one task-center target, got {count}: {old[:140]!r}")
        text = text.replace(old, new, 1)

    replace_once(
        '    "等待": "queued",\n    "完成": "completed",\n',
        '    "等待": "queued",\n    "暂停": "paused",\n    "中断": "interrupted",\n    "完成": "completed",\n',
    )
    replace_once(
        '    "queued": "等待",\n    "completed": "完成",\n',
        '    "queued": "等待",\n    "paused": "暂停",\n    "interrupted": "中断",\n    "completed": "完成",\n',
    )

    resume_rows = '''

def _resume_rows(window) -> list[dict[str, Any]]:
    getter = getattr(window, "get_resume_jobs", None)
    if not callable(getter):
        return []
    try:
        records = list(getter())
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        state = str(record.get("state") or "").lower()
        if state not in {"paused", "interrupted"}:
            continue
        try:
            progress = max(0.0, min(100.0, float(record.get("progress") or 0.0)))
        except (TypeError, ValueError):
            progress = 0.0
        resume_mode = str(record.get("resumeMode") or "continue").lower()
        continue_mode = resume_mode == "continue"
        downloaded = str(record.get("downloaded") or "").strip()
        rows.append(
            {
                "key": f"r:{record.get('id')}",
                "kind": "resume",
                "state": state,
                "jobId": str(record.get("id") or ""),
                "sourceHost": str(record.get("sourceHost") or ""),
                "sourceUrl": "",
                "videoQuality": str(record.get("videoQuality") or "—"),
                "when": f"{progress:.1f}%",
                "label": str(record.get("label") or record.get("sourceHost") or "未完成任务")[:220],
                "detail": f"已保留本机进度 {progress:.1f}%" + (f" · {downloaded}" if downloaded else ""),
                "advice": (
                    "继续时会复用 yt-dlp 的 .part/fragment，从源站允许的最近检查点续传。"
                    if continue_mode
                    else "该来源不能可靠字节续传；继续操作会重新开始该任务，不会伪装成精确断点。"
                ),
                "failureLabel": "断点续传" if continue_mode else "重新开始",
                "resume": record,
            }
        )
    return rows
'''
    replace_once(
        "\n\ndef _history_rows(engine_module) -> list[dict[str, Any]]:\n",
        resume_rows + "\n\ndef _history_rows(engine_module) -> list[dict[str, Any]]:\n",
    )
    replace_once(
        "    rows.extend(_queued_rows(window))\n    rows.extend(_history_rows(engine_module))\n",
        "    rows.extend(_queued_rows(window))\n"
        "    rows.extend(_resume_rows(window))\n"
        "    rows.extend(_history_rows(engine_module))\n",
    )
    replace_once(
        '        "当前下载、等待队列和本机历史放在一个工作区；失败任务会给出原因分类和安全恢复建议。",\n',
        '        "当前下载、等待队列、可恢复任务和本机历史放在一个工作区；暂停/异常退出后不会自动偷偷重新下载。",\n',
    )
    replace_once(
        '    summary_var = tk.StringVar(value="当前 0 · 等待 0 · 完成 0 · 失败 0")\n',
        '    summary_var = tk.StringVar(value="当前 0 · 等待 0 · 可恢复 0 · 完成 0 · 失败 0")\n',
    )
    replace_once(
        "    pause_button: ui.ActionButton | None = None\n",
        "    active_pause_button: ui.ActionButton | None = None\n"
        "    resume_button: ui.ActionButton | None = None\n"
        "    discard_resume_button: ui.ActionButton | None = None\n"
        "    pause_button: ui.ActionButton | None = None\n",
    )
    replace_once(
        "    def selected_queue_ids() -> list[str]:\n",
        '''    def selected_resume() -> dict[str, Any] | None:
        rows = selected_rows()
        if len(rows) != 1 or rows[0].get("kind") != "resume":
            return None
        return rows[0]

    def selected_queue_ids() -> list[str]:
''',
    )
    replace_once(
        "        item = selected_history()\n        queue_ids = selected_queue_ids()\n",
        "        item = selected_history()\n"
        "        resume = selected_resume()\n"
        "        queue_ids = selected_queue_ids()\n",
    )
    replace_once(
        '''        if details_button is not None:
            details_button.state(["!disabled"] if one and one.get("kind") == "active" else ["disabled"])
''',
        '''        if active_pause_button is not None:
            pause_event = getattr(window, "pause_event", None)
            can_pause = bool(one and one.get("kind") == "active" and getattr(window, "running", False))
            if pause_event is not None and pause_event.is_set():
                can_pause = False
            active_pause_button.state(["!disabled"] if can_pause else ["disabled"])
        if resume_button is not None:
            resume_button.state(["!disabled"] if resume and not bool(getattr(window, "running", False)) else ["disabled"])
        if discard_resume_button is not None:
            discard_resume_button.state(["!disabled"] if resume and not bool(getattr(window, "running", False)) else ["disabled"])
        if details_button is not None:
            details_button.state(["!disabled"] if one and one.get("kind") == "active" else ["disabled"])
''',
    )
    replace_once(
        "        queued_count = sum(1 for row in rows if row.get(\"state\") == \"queued\")\n        completed_count = sum(1 for row in history if row.get(\"state\") == \"completed\")\n",
        "        queued_count = sum(1 for row in rows if row.get(\"state\") == \"queued\")\n"
        "        recoverable_count = sum(1 for row in rows if row.get(\"kind\") == \"resume\")\n"
        "        completed_count = sum(1 for row in history if row.get(\"state\") == \"completed\")\n",
    )
    replace_once(
        '        summary_var.set(f"当前 {active_count} · 等待 {queued_count} · 完成 {completed_count} · 失败 {failed_count}")\n',
        '        summary_var.set(f"当前 {active_count} · 等待 {queued_count} · 可恢复 {recoverable_count} · 完成 {completed_count} · 失败 {failed_count}")\n',
    )
    replace_once(
        "    def move_queue(edge: str) -> None:\n",
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

    def discard_resume_selected() -> None:
        row = selected_resume()
        discard = getattr(window, "discard_resume_job", None)
        if not row or not callable(discard):
            return
        job_id = str(row.get("jobId") or "")
        if not job_id:
            return
        if not messagebox.askyesno(
            engine_module.APP_NAME,
            "放弃这个可恢复任务？\n\n下载临时文件不会在这里主动删除，但任务中心将不再提供继续入口。",
            parent=dialog,
        ):
            return
        if discard(job_id):
            refresh(force=True)

    def move_queue(edge: str) -> None:
''',
    )
    replace_once(
        '    pause_button = ui.ActionButton(footer, text="完成后暂停", command=toggle_pause, kind="ghost", compact=True)\n    pause_button.pack(side="left")\n',
        '    active_pause_button = ui.ActionButton(footer, text="暂停当前", command=pause_active_selected, kind="secondary", compact=True)\n'
        '    active_pause_button.pack(side="left")\n'
        '    pause_button = ui.ActionButton(footer, text="完成后暂停", command=toggle_pause, kind="ghost", compact=True)\n'
        '    pause_button.pack(side="left", padx=(6, 0))\n',
    )
    replace_once(
        '    smart_button = ui.ActionButton(footer, text="智能重试", command=lambda: retry_selected(True), kind="primary", compact=True)\n',
        '    resume_button = ui.ActionButton(footer, text="继续任务", command=resume_selected, kind="primary", compact=True)\n'
        '    resume_button.pack(side="right")\n'
        '    discard_resume_button = ui.ActionButton(footer, text="放弃恢复", command=discard_resume_selected, kind="danger", compact=True)\n'
        '    discard_resume_button.pack(side="right", padx=(0, 6))\n'
        '    smart_button = ui.ActionButton(footer, text="智能重试", command=lambda: retry_selected(True), kind="primary", compact=True)\n',
    )
    replace_once(
        "    for button in (top_button, up_button, down_button, remove_button, details_button, copy_button, open_button, reveal_button, retry_button, smart_button):\n",
        "    for button in (active_pause_button, resume_button, discard_resume_button, top_button, up_button, down_button, remove_button, details_button, copy_button, open_button, reveal_button, retry_button, smart_button):\n",
    )
    replace_once(
        '    tree.bind("<Double-1>", lambda _event: open_file(False))\n',
        '''    def activate_selected(_event=None) -> None:
        rows = selected_rows()
        if len(rows) != 1:
            return
        if rows[0].get("kind") == "resume":
            resume_selected()
        elif rows[0].get("kind") == "history":
            open_file(False)
        elif rows[0].get("kind") == "active":
            show_details()

    tree.bind("<Double-1>", activate_selected)
''',
    )
    replace_once(
        '            total = len(load_history(module)) + len(_pending_snapshot(window)) + (1 if bool(getattr(window, "running", False)) else 0)\n',
        '            total = len(load_history(module)) + len(_pending_snapshot(window)) + len(_resume_rows(window)) + (1 if bool(getattr(window, "running", False)) else 0)\n',
    )
    replace_once(
        '    assert "example.com" in _row_search_text(row)\n',
        '    assert "example.com" in _row_search_text(row)\n'
        '    resume = {"state": "paused", "sourceHost": "video.example", "failureLabel": "断点续传"}\n'
        '    assert _matches_filter(resume, "paused", "") is True\n'
        '    assert "断点续传" in _row_search_text(resume)\n',
    )
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_entrypoint()
    patch_task_center()
