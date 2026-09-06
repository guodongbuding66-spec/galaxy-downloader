from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

import desktop_ui as ui
from course_attachment_download_service import CourseAttachmentDownloadService

_TERMINAL_ATTACHMENT_STATES = {"completed", "failed", "cancelled"}


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def format_attachment_size(value: object) -> str:
    size = _safe_int(value)
    if size <= 0:
        return "—"
    units = ("B", "KB", "MB", "GB")
    rendered = float(size)
    unit = units[0]
    for candidate in units:
        unit = candidate
        if rendered < 1024 or candidate == units[-1]:
            break
        rendered /= 1024
    return f"{rendered:.0f} {unit}" if unit == "B" else f"{rendered:.1f} {unit}"


def build_attachment_rows(items: list[dict]) -> list[dict[str, Any]]:
    """Flatten public lecture attachment metadata without carrying provider internals."""
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        lecture = str(item.get("title") or item.get("fileName") or "未命名课时")
        attachments = item.get("attachments")
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            attachment_id = str(attachment.get("id") or "").strip().lower()
            if len(attachment_id) != 32 or any(ch not in "0123456789abcdef" for ch in attachment_id):
                continue
            rows.append(
                {
                    "id": attachment_id,
                    "lecture": lecture,
                    "title": str(attachment.get("title") or attachment.get("fileName") or "附件"),
                    "fileName": str(attachment.get("fileName") or ""),
                    "assetType": str(attachment.get("assetType") or ""),
                    "downloaded": bool(attachment.get("downloaded")),
                    "sizeBytes": _safe_int(attachment.get("sizeBytes")),
                }
            )
    return rows


def attachment_job_status_text(job: dict[str, Any]) -> str:
    state = str(job.get("state") or "queued").lower()
    labels = {
        "queued": "已加入附件队列",
        "running": "正在下载附件",
        "cancelling": "正在取消附件",
        "completed": "附件已下载",
        "failed": "附件下载失败",
        "cancelled": "附件下载已取消",
    }
    try:
        progress = max(0.0, min(float(job.get("progress") or 0.0), 100.0))
    except (TypeError, ValueError):
        progress = 0.0
    parts = [labels.get(state, state or "附件状态未知")]
    if state not in {"completed", "failed", "cancelled"}:
        parts.append(f"{progress:.0f}%")
    downloaded = _safe_int(job.get("downloadedBytes"))
    total = _safe_int(job.get("sizeBytes"))
    if total > 0:
        parts.append(f"{format_attachment_size(downloaded)} / {format_attachment_size(total)}")
    elif downloaded > 0:
        parts.append(format_attachment_size(downloaded))
    error = str(job.get("error") or "").strip()
    if error:
        parts.append(error[:180])
    return " · ".join(parts)


def _attachment_service(window, context) -> CourseAttachmentDownloadService:
    service = getattr(window, "_learning_attachment_download_service", None)
    if service is None:
        service = CourseAttachmentDownloadService(context)
        window._learning_attachment_download_service = service
    return service


def close_attachment_download_service(window) -> None:
    service = getattr(window, "_learning_attachment_download_service", None)
    window._learning_attachment_download_service = None
    if service is not None:
        service.close()


def build_attachment_tab(notebook, window, api, browser_var) -> None:
    tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14)
    notebook.add(tab, text="附件")

    intro = tk.Frame(tab, bg=ui.PANEL)
    intro.pack(fill="x")
    text = tk.Frame(intro, bg=ui.PANEL)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "课程附件", size=10, weight="bold").pack(anchor="w")
    ui._label(
        text,
        "使用上方选择的浏览器登录下载已授权课时附件；不会显示签名 URL 或本地路径。",
        size=7,
        color=ui.MUTED,
    ).pack(anchor="w", pady=(2, 0))

    columns = tk.Frame(tab, bg=ui.PANEL)
    columns.pack(fill="both", expand=True, pady=(12, 0))
    course_list = tk.Listbox(
        columns,
        width=30,
        bg=ui.BG,
        fg=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    course_list.pack(side="left", fill="both")

    attachment_tree = ttk.Treeview(
        columns,
        columns=("lecture", "type", "status", "size"),
        show="tree headings",
        selectmode="browse",
    )
    attachment_tree.heading("#0", text="附件")
    attachment_tree.heading("lecture", text="课时")
    attachment_tree.heading("type", text="类型")
    attachment_tree.heading("status", text="状态")
    attachment_tree.heading("size", text="大小")
    attachment_tree.column("#0", width=250, minwidth=150, stretch=True)
    attachment_tree.column("lecture", width=260, minwidth=160, stretch=True)
    attachment_tree.column("type", width=85, minwidth=70, stretch=False)
    attachment_tree.column("status", width=90, minwidth=80, anchor="center", stretch=False)
    attachment_tree.column("size", width=90, minwidth=75, anchor="e", stretch=False)
    attachment_tree.pack(side="left", fill="both", expand=True, padx=(10, 0))

    courses: list[dict] = []
    attachments: dict[str, dict[str, Any]] = {}
    status = tk.StringVar(value="选择课程查看附件")
    poll_after_id: str | None = None

    def selected_course() -> dict | None:
        selection = course_list.curselection()
        return courses[selection[0]] if selection else None

    def selected_attachment() -> dict[str, Any] | None:
        selection = attachment_tree.selection()
        if not selection:
            return None
        return attachments.get(selection[0])

    def render_rows(rows: list[dict[str, Any]]) -> None:
        attachments.clear()
        for child in attachment_tree.get_children():
            attachment_tree.delete(child)
        for row in rows:
            iid = f"attachment:{row['id']}"
            attachments[iid] = row
            state = "✓ 已下载" if row["downloaded"] else "未下载"
            attachment_tree.insert(
                "",
                "end",
                iid=iid,
                text=row["title"],
                values=(row["lecture"], row["assetType"] or "—", state, format_attachment_size(row["sizeBytes"])),
            )
        first = next(iter(attachments), None)
        if first:
            attachment_tree.selection_set(first)
        status.set(f"{len(rows)} 个附件" if rows else "此课程没有可下载附件")
        update_controls()

    def refresh_attachments(*_args) -> None:
        course = selected_course()
        if not course:
            render_rows([])
            return
        try:
            payload = api.items(course["id"], limit=5000)
            render_rows(build_attachment_rows(payload.get("items") or []))
        except Exception as exc:  # noqa: BLE001
            status.set(f"附件读取失败：{exc}")
            render_rows([])

    def refresh_courses(select_course_id: str = "") -> None:
        previous = select_course_id or str((selected_course() or {}).get("id") or "")
        try:
            courses[:] = api.courses(limit=500).get("courses", [])
        except Exception as exc:  # noqa: BLE001
            status.set(f"课程读取失败：{exc}")
            return
        course_list.delete(0, "end")
        selected_index = 0
        for index, course in enumerate(courses):
            course_list.insert("end", str(course.get("name") or "未命名课程"))
            if previous and str(course.get("id") or "") == previous:
                selected_index = index
        if courses:
            course_list.selection_set(selected_index)
            course_list.see(selected_index)
        refresh_attachments()

    def active_job_id() -> str:
        return str(getattr(window, "_learning_attachment_job_id", "") or "")

    def active_attachment_id() -> str:
        return str(getattr(window, "_learning_attachment_id", "") or "")

    def update_controls(job: dict[str, Any] | None = None) -> None:
        row = selected_attachment()
        state = str((job or {}).get("state") or "").lower()
        running = bool(active_job_id()) and state not in _TERMINAL_ATTACHMENT_STATES
        if running:
            download_button.state(["disabled"])
            cancel_button.state(["!disabled"])
            return
        cancel_button.state(["disabled"])
        if row is None or row.get("downloaded"):
            download_button.state(["disabled"])
        else:
            download_button.state(["!disabled"])

    def stop_polling() -> None:
        nonlocal poll_after_id
        if poll_after_id is None:
            return
        try:
            tab.after_cancel(poll_after_id)
        except tk.TclError:
            pass
        poll_after_id = None

    def schedule_poll(delay: int = 500) -> None:
        nonlocal poll_after_id
        stop_polling()
        try:
            if not tab.winfo_exists():
                return
            poll_after_id = tab.after(delay, poll_job)
        except tk.TclError:
            poll_after_id = None

    def apply_job(job: dict[str, Any]) -> None:
        state = str(job.get("state") or "").lower()
        status.set(attachment_job_status_text(job))
        update_controls(job)
        if state in _TERMINAL_ATTACHMENT_STATES:
            window._learning_attachment_job_id = ""
            if state == "completed":
                refresh_attachments()
            return
        schedule_poll()

    def poll_job() -> None:
        nonlocal poll_after_id
        poll_after_id = None
        job_id = active_job_id()
        if not job_id:
            update_controls()
            return
        try:
            job = _attachment_service(window, api.context).status(job_id)
        except Exception as exc:  # noqa: BLE001
            window._learning_attachment_job_id = ""
            status.set(f"附件状态读取失败：{exc}")
            update_controls()
            return
        apply_job(job)

    def start_download() -> None:
        row = selected_attachment()
        if row is None or row.get("downloaded"):
            return
        try:
            job = _attachment_service(window, api.context).submit(
                row["id"],
                browser=browser_var.get(),
            )
        except Exception as exc:  # noqa: BLE001
            status.set(f"附件下载提交失败：{exc}")
            update_controls()
            return
        window._learning_attachment_job_id = str(job.get("id") or "")
        window._learning_attachment_id = row["id"]
        apply_job(job)

    def cancel_download() -> None:
        job_id = active_job_id()
        if not job_id:
            return
        try:
            job = _attachment_service(window, api.context).cancel(job_id)
        except Exception as exc:  # noqa: BLE001
            status.set(f"附件取消失败：{exc}")
            return
        apply_job(job)

    actions = tk.Frame(tab, bg=ui.PANEL)
    actions.pack(fill="x", pady=(10, 0))
    ui._label(actions, variable=status, size=8, color=ui.MUTED).pack(side="left", fill="x", expand=True)
    download_button = ui.ActionButton(
        actions,
        text="下载附件",
        command=start_download,
        kind="secondary",
        compact=True,
    )
    download_button.pack(side="right")
    cancel_button = ui.ActionButton(
        actions,
        text="取消附件",
        command=cancel_download,
        kind="ghost",
        compact=True,
    )
    cancel_button.pack(side="right", padx=(0, 6))
    ui.ActionButton(
        actions,
        text="刷新附件",
        command=refresh_courses,
        kind="ghost",
        compact=True,
    ).pack(side="right", padx=(0, 6))

    course_list.bind("<<ListboxSelect>>", refresh_attachments)
    attachment_tree.bind("<<TreeviewSelect>>", lambda _event: update_controls())

    def destroyed(event) -> None:
        if event.widget is tab:
            stop_polling()

    tab.bind("<Destroy>", destroyed, add="+")
    refresh_courses()
    if active_job_id():
        schedule_poll(50)
    else:
        update_controls()
