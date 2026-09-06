from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Any

import desktop_ui as ui
from desktop_course_download import DesktopCourseDownloadService
from desktop_hooks import (
    install_before_close_support,
    register_after_build_ui_hook,
    register_before_close_hook,
)
from desktop_learning_attachments import build_attachment_tab, close_attachment_download_service
from headless_learning_api import HeadlessLearningApi
from headless_learning_structure import install_headless_learning_structure

_PROVIDER_VALUES = ("udemy", "auto")
_BROWSER_VALUES = ("none", "edge", "chrome", "firefox", "brave")
_TERMINAL_JOB_STATES = {"failed", "cancelled"}
_TERMINAL_SYNC_STATES = {"synced", "failed"}
_UNSECTIONED_KEY = "section:unsectioned"


def _api(engine_module) -> HeadlessLearningApi:
    install_headless_learning_structure()
    return HeadlessLearningApi(engine_module.default_download_dir())


def _position(value: object, fallback: int) -> tuple[int, int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return (1, fallback)
    return (0, parsed)


def build_course_tree_rows(sections: list[dict], items: list[dict]) -> list[dict[str, Any]]:
    """Return stable Section -> Lecture rows without requiring a Tk display."""
    ordered_sections = sorted(
        (dict(section) for section in sections),
        key=lambda row: (
            _position(row.get("position"), 10**9),
            str(row.get("title") or ""),
            str(row.get("id") or ""),
        ),
    )
    indexed_items = list(enumerate(dict(item) for item in items))
    item_groups: dict[str, list[tuple[int, dict]]] = {}
    for index, item in indexed_items:
        section_id = str(item.get("sectionId") or "").strip()
        item_groups.setdefault(section_id, []).append((index, item))

    rows: list[dict[str, Any]] = []
    for index, section in enumerate(ordered_sections):
        section_id = str(section.get("id") or "").strip()
        if not section_id:
            section_id = f"missing-{index}"
        key = f"section:{section_id}"
        rows.append(
            {
                "kind": "section",
                "key": key,
                "parent": "",
                "title": str(section.get("title") or f"章节 {index + 1}"),
                "sectionId": section_id,
            }
        )
        lectures = sorted(
            item_groups.pop(section_id, []),
            key=lambda pair: (_position(pair[1].get("providerPosition"), pair[0]), pair[0]),
        )
        for fallback_index, item in lectures:
            item_id = str(item.get("id") or "").strip()
            if not item_id:
                continue
            rows.append(
                {
                    "kind": "item",
                    "key": f"item:{item_id}",
                    "parent": key,
                    "title": str(item.get("title") or item.get("mediaId") or "未命名课时"),
                    "itemId": item_id,
                    "item": item,
                    "fallbackPosition": fallback_index,
                }
            )

    unsectioned = list(item_groups.pop("", []))
    for _unknown_section, unknown_items in sorted(item_groups.items()):
        unsectioned.extend(unknown_items)
    if unsectioned:
        rows.append(
            {
                "kind": "section",
                "key": _UNSECTIONED_KEY,
                "parent": "",
                "title": "未分组课时",
                "sectionId": "",
            }
        )
        for fallback_index, item in sorted(
            unsectioned,
            key=lambda pair: (_position(pair[1].get("providerPosition"), pair[0]), pair[0]),
        ):
            item_id = str(item.get("id") or "").strip()
            if not item_id:
                continue
            rows.append(
                {
                    "kind": "item",
                    "key": f"item:{item_id}",
                    "parent": _UNSECTIONED_KEY,
                    "title": str(item.get("title") or item.get("mediaId") or "未命名课时"),
                    "itemId": item_id,
                    "item": item,
                    "fallbackPosition": fallback_index,
                }
            )
    return rows


def managed_download_status_text(payload: dict[str, Any]) -> str:
    job = payload.get("job") if isinstance(payload.get("job"), dict) else {}
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    state = str(job.get("state") or "unknown").lower()
    labels = {
        "queued": "已加入队列",
        "running": "正在下载",
        "completed": "下载完成",
        "failed": "下载失败",
        "cancelled": "已取消",
    }
    try:
        progress = max(0.0, min(float(job.get("progress") or 0.0), 100.0))
    except (TypeError, ValueError):
        progress = 0.0
    sync_state = str(session.get("syncState") or "").lower()
    sync_labels = {
        "pending": "等待课程同步",
        "syncing": "正在同步课程",
        "synced": "课程已同步",
        "failed": "课程同步失败",
    }
    parts = [labels.get(state, state or "状态未知"), f"{progress:.0f}%"]
    if sync_state:
        parts.append(sync_labels.get(sync_state, sync_state))
    return " · ".join(parts)


def managed_download_finished(payload: dict[str, Any]) -> bool:
    job = payload.get("job") if isinstance(payload.get("job"), dict) else {}
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    state = str(job.get("state") or "").lower()
    if state in _TERMINAL_JOB_STATES:
        return True
    if state != "completed":
        return False
    sync_state = str(session.get("syncState") or "").lower()
    return not sync_state or sync_state in _TERMINAL_SYNC_STATES


def _course_service(window, engine_module) -> DesktopCourseDownloadService:
    service = getattr(window, "_learning_course_download_service", None)
    if service is None:
        service = DesktopCourseDownloadService(engine_module.default_download_dir())
        window._learning_course_download_service = service
    return service


def _close_learning_service(window) -> None:
    close_attachment_download_service(window)
    service = getattr(window, "_learning_course_download_service", None)
    window._learning_course_download_service = None
    if service is not None:
        service.close()


def _show_learning(window, engine_module) -> None:
    existing = getattr(window, "_learning_workspace_window", None)
    if existing is not None:
        try:
            existing.deiconify()
            existing.lift()
            return
        except tk.TclError:
            window._learning_workspace_window = None
    dialog = tk.Toplevel(window)
    window._learning_workspace_window = dialog
    dialog.title("学习中心 · Galaxy Local Engine")
    dialog.geometry("1100x740")
    dialog.minsize(900, 620)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=18, pady=16)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "课程与复习", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "授权课程下载 · 章节课时 · 时间戳笔记 · 进度 · Flashcards / Spaced Repetition",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(3, 10))

    api = _api(engine_module)
    notebook = ttk.Notebook(shell)
    notebook.pack(fill="both", expand=True)
    courses_tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14)
    notebook.add(courses_tab, text="课程")
    cards_tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14)
    notebook.add(cards_tab, text="复习卡")

    course_name = tk.StringVar()
    source_url = tk.StringVar()
    provider_var = tk.StringVar(value="udemy")
    browser_var = tk.StringVar(value="none")
    subtitles_var = tk.BooleanVar(value=True)
    status = tk.StringVar(value="就绪")
    build_attachment_tab(notebook, window, api, browser_var)

    source_row = tk.Frame(courses_tab, bg=ui.PANEL)
    source_row.pack(fill="x")
    ui._label(source_row, "课程 URL", size=7, color=ui.MUTED).pack(side="left")
    tk.Entry(
        source_row,
        textvariable=source_url,
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    ).pack(side="left", padx=(6, 10), fill="x", expand=True)
    ui._label(source_row, "Provider", size=7, color=ui.MUTED).pack(side="left")
    ttk.Combobox(
        source_row,
        textvariable=provider_var,
        values=_PROVIDER_VALUES,
        state="readonly",
        width=9,
    ).pack(side="left", padx=(6, 10))
    ui._label(source_row, "浏览器登录", size=7, color=ui.MUTED).pack(side="left")
    ttk.Combobox(
        source_row,
        textvariable=browser_var,
        values=_BROWSER_VALUES,
        state="readonly",
        width=9,
    ).pack(side="left", padx=(6, 0))

    managed_row = tk.Frame(courses_tab, bg=ui.PANEL)
    managed_row.pack(fill="x", pady=(8, 0))
    ui._label(managed_row, "课程名（可选）", size=7, color=ui.MUTED).pack(side="left")
    tk.Entry(
        managed_row,
        textvariable=course_name,
        width=24,
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    ).pack(side="left", padx=(6, 12))
    ttk.Checkbutton(managed_row, text="同时下载字幕", variable=subtitles_var).pack(side="left")

    columns = tk.Frame(courses_tab, bg=ui.PANEL)
    columns.pack(fill="both", expand=True, pady=(12, 0))
    course_list = tk.Listbox(
        columns,
        width=32,
        bg=ui.BG,
        fg=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    course_list.pack(side="left", fill="both")
    item_tree = ttk.Treeview(columns=("progress",), show="tree headings", selectmode="browse")
    item_tree.heading("#0", text="章节 / 课时")
    item_tree.heading("progress", text="进度")
    item_tree.column("#0", width=520, minwidth=260, stretch=True)
    item_tree.column("progress", width=100, minwidth=80, anchor="center", stretch=False)
    item_tree.pack(side="left", fill="both", expand=True, padx=(10, 0))

    courses: list[dict] = []
    item_by_tree_id: dict[str, dict] = {}
    progress_var = tk.StringVar(value="0")
    note_var = tk.StringVar()
    edit = tk.Frame(courses_tab, bg=ui.PANEL)
    edit.pack(fill="x", pady=(10, 0))
    ui._label(edit, "进度(s)", size=7, color=ui.MUTED).pack(side="left")
    tk.Entry(
        edit,
        textvariable=progress_var,
        width=10,
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    ).pack(side="left", padx=(6, 10))
    ui._label(edit, "笔记", size=7, color=ui.MUTED).pack(side="left")
    tk.Entry(
        edit,
        textvariable=note_var,
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    ).pack(side="left", padx=(6, 0), fill="x", expand=True)

    def selected_course():
        selection = course_list.curselection()
        return courses[selection[0]] if selection else None

    def selected_item():
        selection = item_tree.selection()
        if not selection:
            return None
        return item_by_tree_id.get(selection[0])

    def refresh_items(*_args) -> None:
        item_by_tree_id.clear()
        for child in item_tree.get_children():
            item_tree.delete(child)
        course = selected_course()
        if not course:
            return
        data = api.items(course["id"], limit=5000)
        rows = build_course_tree_rows(data.get("sections", []), data.get("items", []))
        for row in rows:
            if row["kind"] == "section":
                item_tree.insert("", "end", iid=row["key"], text=row["title"], values=("",), open=True)
                continue
            item = row["item"]
            mark = "✓ 已完成" if item.get("completed") else f"{float(item.get('progressSeconds') or 0):.0f}s"
            item_tree.insert(row["parent"], "end", iid=row["key"], text=row["title"], values=(mark,))
            item_by_tree_id[row["key"]] = item
        first_item = next(iter(item_by_tree_id), None)
        if first_item:
            item_tree.selection_set(first_item)

    def on_item_selected(*_args) -> None:
        item = selected_item()
        if item is not None:
            progress_var.set(f"{float(item.get('progressSeconds') or 0):.0f}")

    item_tree.bind("<<TreeviewSelect>>", on_item_selected)
    course_list.bind("<<ListboxSelect>>", refresh_items)

    def refresh_courses(select_course_id: str | None = None) -> None:
        previous = select_course_id or str((selected_course() or {}).get("id") or "")
        courses[:] = api.courses(limit=500).get("courses", [])
        course_list.delete(0, "end")
        selected_index = 0
        for index, course in enumerate(courses):
            course_list.insert("end", f"{course.get('name')} · {course.get('itemCount', 0)} 项")
            if previous and str(course.get("id") or "") == previous:
                selected_index = index
        if courses:
            course_list.selection_set(selected_index)
            course_list.see(selected_index)
        refresh_items()

    def create() -> None:
        try:
            name = course_name.get().strip() or "新课程"
            manual_provider = provider_var.get()
            if manual_provider == "auto":
                manual_provider = "generic"
            api.create_course(
                {
                    "name": name,
                    "sourceUrl": source_url.get(),
                    "provider": manual_provider or "generic",
                }
            )
            status.set("空课程已创建")
            refresh_courses()
        except Exception as exc:  # noqa: BLE001
            status.set(f"失败：{exc}")

    def save_progress(completed: bool = False) -> None:
        item = selected_item()
        if not item:
            return
        try:
            api.set_progress(
                item["id"],
                {"progressSeconds": float(progress_var.get() or 0), "completed": completed},
            )
            status.set("进度已保存")
            refresh_items()
        except Exception as exc:  # noqa: BLE001
            status.set(f"失败：{exc}")

    def add_note() -> None:
        item = selected_item()
        if not item:
            return
        try:
            api.create_note(
                item["id"],
                {"timestampSeconds": float(progress_var.get() or 0), "body": note_var.get()},
            )
            status.set("笔记已保存")
            note_var.set("")
        except Exception as exc:  # noqa: BLE001
            status.set(f"失败：{exc}")

    poll_after_id: str | None = None

    def set_download_controls(running: bool, *, sync_failed: bool = False) -> None:
        if running:
            download_button.state(["disabled"])
            cancel_button.state(["!disabled"])
        else:
            download_button.state(["!disabled"])
            cancel_button.state(["disabled"])
        if sync_failed:
            sync_button.state(["!disabled"])
        else:
            sync_button.state(["disabled"])

    def schedule_poll(delay: int = 750) -> None:
        nonlocal poll_after_id
        if not dialog.winfo_exists():
            return
        if poll_after_id is not None:
            try:
                dialog.after_cancel(poll_after_id)
            except tk.TclError:
                poll_after_id = None
        poll_after_id = dialog.after(delay, poll_download)

    def apply_download_status(payload: dict[str, Any]) -> None:
        job = payload.get("job") if isinstance(payload.get("job"), dict) else {}
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        state = str(job.get("state") or "").lower()
        sync_state = str(session.get("syncState") or "").lower()
        status.set(managed_download_status_text(payload))
        finished = managed_download_finished(payload)
        set_download_controls(
            not finished,
            sync_failed=state == "completed" and sync_state == "failed",
        )
        if finished:
            course_id = str(session.get("courseId") or getattr(window, "_learning_course_id", "") or "")
            if state == "completed" and sync_state == "synced":
                refresh_courses(course_id or None)
            return
        schedule_poll()

    def poll_download() -> None:
        nonlocal poll_after_id
        poll_after_id = None
        job_id = str(getattr(window, "_learning_course_job_id", "") or "")
        if not job_id:
            set_download_controls(False)
            return
        try:
            payload = _course_service(window, engine_module).status(job_id)
        except Exception as exc:  # noqa: BLE001
            status.set(f"状态读取失败：{exc}")
            set_download_controls(False)
            return
        apply_download_status(payload)

    def submit_managed() -> None:
        source = source_url.get().strip()
        if not source:
            status.set("请输入课程 URL")
            return
        try:
            service = _course_service(window, engine_module)
        except Exception as exc:  # noqa: BLE001
            status.set(f"课程下载服务启动失败：{exc}")
            set_download_controls(False)
            return
        set_download_controls(True)
        status.set("正在提交课程下载…")
        provider = provider_var.get()
        browser = browser_var.get()
        include_subtitles = subtitles_var.get()
        requested_name = course_name.get().strip()

        def worker() -> None:
            try:
                submitted = service.submit(
                    source,
                    provider=provider,
                    browser=browser,
                    include_subtitles=include_subtitles,
                    course_name=requested_name,
                )
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)

                def failed() -> None:
                    try:
                        exists = bool(dialog.winfo_exists())
                    except tk.TclError:
                        exists = False
                    if exists:
                        status.set(f"提交失败：{error_text}")
                        set_download_controls(False)

                try:
                    window.ui(failed)
                except tk.TclError:
                    return
                return

            def accepted() -> None:
                try:
                    exists = bool(dialog.winfo_exists())
                except tk.TclError:
                    exists = False
                if not exists:
                    return
                job = submitted.get("job") if isinstance(submitted.get("job"), dict) else {}
                course = submitted.get("course") if isinstance(submitted.get("course"), dict) else {}
                window._learning_course_job_id = str(job.get("id") or "")
                window._learning_course_id = str(course.get("id") or "")
                apply_download_status(submitted)
                refresh_courses(window._learning_course_id or None)

            try:
                window.ui(accepted)
            except tk.TclError:
                return

        threading.Thread(target=worker, daemon=True, name="galaxy-course-submit").start()

    def cancel_managed() -> None:
        job_id = str(getattr(window, "_learning_course_job_id", "") or "")
        if not job_id:
            return
        try:
            payload = _course_service(window, engine_module).cancel(job_id)
            apply_download_status(payload)
        except Exception as exc:  # noqa: BLE001
            status.set(f"取消失败：{exc}")

    def retry_sync() -> None:
        job_id = str(getattr(window, "_learning_course_job_id", "") or "")
        if not job_id:
            return
        try:
            payload = _course_service(window, engine_module).sync_now(job_id)
            apply_download_status(payload)
        except Exception as exc:  # noqa: BLE001
            status.set(f"同步失败：{exc}")

    actions = tk.Frame(courses_tab, bg=ui.PANEL)
    actions.pack(fill="x", pady=(10, 0))
    ui._label(actions, variable=status, size=8, color=ui.MUTED).pack(side="left", fill="x", expand=True)
    download_button = ui.ActionButton(
        actions,
        text="下载课程",
        command=submit_managed,
        kind="secondary",
        compact=True,
    )
    download_button.pack(side="right")
    cancel_button = ui.ActionButton(
        actions,
        text="取消下载",
        command=cancel_managed,
        kind="ghost",
        compact=True,
    )
    cancel_button.pack(side="right", padx=(0, 6))
    sync_button = ui.ActionButton(
        actions,
        text="重试同步",
        command=retry_sync,
        kind="ghost",
        compact=True,
    )
    sync_button.pack(side="right", padx=(0, 6))
    ui.ActionButton(
        actions,
        text="创建空课程",
        command=create,
        kind="ghost",
        compact=True,
    ).pack(side="right", padx=(0, 6))
    ui.ActionButton(
        actions,
        text="保存笔记",
        command=add_note,
        kind="ghost",
        compact=True,
    ).pack(side="right", padx=(0, 6))
    ui.ActionButton(
        actions,
        text="标记完成",
        command=lambda: save_progress(True),
        kind="ghost",
        compact=True,
    ).pack(side="right", padx=(0, 6))
    ui.ActionButton(
        actions,
        text="保存进度",
        command=lambda: save_progress(False),
        kind="ghost",
        compact=True,
    ).pack(side="right", padx=(0, 6))
    set_download_controls(False)

    front_var = tk.StringVar()
    back_var = tk.StringVar()
    rating_var = tk.StringVar(value="good")
    cards_status = tk.StringVar(value="就绪")
    card_list = tk.Listbox(
        cards_tab,
        bg=ui.BG,
        fg=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    card_list.pack(fill="both", expand=True)
    cards: list[dict] = []
    form = tk.Frame(cards_tab, bg=ui.PANEL)
    form.pack(fill="x", pady=(10, 0))
    for label, var in (("正面", front_var), ("背面", back_var)):
        ui._label(form, label, size=7, color=ui.MUTED).pack(side="left")
        tk.Entry(
            form,
            textvariable=var,
            bg=ui.BG,
            fg=ui.TEXT,
            insertbackground=ui.TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=ui.BORDER,
        ).pack(side="left", padx=(6, 10), fill="x", expand=True)
    ttk.Combobox(
        form,
        textvariable=rating_var,
        values=("again", "hard", "good", "easy"),
        state="readonly",
        width=8,
    ).pack(side="left")

    def selected_card():
        selection = card_list.curselection()
        return cards[selection[0]] if selection else None

    def refresh_cards() -> None:
        cards[:] = api.flashcards(due_only=False, limit=1000).get("flashcards", [])
        card_list.delete(0, "end")
        for card in cards:
            card_list.insert("end", f"{card.get('front')} → {card.get('back')} · due {card.get('dueAt', '')}")
        if cards:
            card_list.selection_set(0)

    def create_card() -> None:
        try:
            api.create_flashcard({"front": front_var.get(), "back": back_var.get()})
            cards_status.set("已创建")
            refresh_cards()
        except Exception as exc:  # noqa: BLE001
            cards_status.set(f"失败：{exc}")

    def review() -> None:
        card = selected_card()
        if not card:
            return
        try:
            api.review_flashcard(card["id"], {"rating": rating_var.get()})
            cards_status.set("复习结果已记录")
            refresh_cards()
        except Exception as exc:  # noqa: BLE001
            cards_status.set(f"失败：{exc}")

    card_actions = tk.Frame(cards_tab, bg=ui.PANEL)
    card_actions.pack(fill="x", pady=(10, 0))
    ui._label(card_actions, variable=cards_status, size=8, color=ui.MUTED).pack(side="left")
    ui.ActionButton(
        card_actions,
        text="创建卡片",
        command=create_card,
        kind="secondary",
        compact=True,
    ).pack(side="right")
    ui.ActionButton(
        card_actions,
        text="记录复习",
        command=review,
        kind="ghost",
        compact=True,
    ).pack(side="right", padx=(0, 6))

    def close() -> None:
        nonlocal poll_after_id
        if poll_after_id is not None:
            try:
                dialog.after_cancel(poll_after_id)
            except tk.TclError:
                poll_after_id = None
            poll_after_id = None
        window._learning_workspace_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh_courses()
    refresh_cards()
    if getattr(window, "_learning_course_job_id", None):
        schedule_poll(50)


def _add_learning_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_learning_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "课程 / 学习", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        text,
        "授权课程下载 · 章节课时 · 时间戳笔记 · 进度 · Spaced Repetition",
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(
        card,
        text="打开学习中心",
        command=lambda: _show_learning(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_learning_entry_built = True


def install_desktop_learning(engine_module):
    cls = engine_module.EngineWindow
    if getattr(cls, "_galaxy_desktop_learning_installed", False):
        return cls
    install_before_close_support(cls)
    register_after_build_ui_hook(
        cls,
        "desktop-learning",
        lambda window: _add_learning_entry(window, engine_module),
        order=55,
    )
    register_before_close_hook(cls, "desktop-learning", _close_learning_service, order=55)
    cls._galaxy_desktop_learning_installed = True
    return cls


def run_desktop_learning_self_test() -> None:
    assert callable(HeadlessLearningApi)
    rows = build_course_tree_rows(
        [
            {"id": "s1", "title": "第二章", "position": 2},
            {"id": "s0", "title": "第一章", "position": 1},
        ],
        [
            {"id": "i2", "sectionId": "s1", "title": "2.1", "providerPosition": 1},
            {"id": "i1", "sectionId": "s0", "title": "1.1", "providerPosition": 1},
        ],
    )
    assert [row["title"] for row in rows] == ["第一章", "1.1", "第二章", "2.1"]
    assert managed_download_finished(
        {"job": {"state": "completed"}, "session": {"syncState": "synced"}}
    )
