from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk
from typing import Any

import desktop_ui as ui
from desktop_course_resume import launch_desktop_course_resume

_SUBTITLE_KIND_LABELS = {"manual": "人工", "automatic": "自动"}
_SUBTITLE_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_ITEM_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _safe_index(value: object, fallback: int = 10**9) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 0 else fallback


def _safe_progress(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, parsed)


def subtitle_tracks_text(item: dict[str, Any]) -> str:
    """Render only bounded public subtitle language/kind metadata."""
    tracks = item.get("subtitleTracks")
    if not isinstance(tracks, list):
        return "—"
    labels: list[str] = []
    seen: set[tuple[str, str]] = set()
    for track in tracks[:64]:
        if not isinstance(track, dict):
            continue
        language = str(track.get("language") or "").strip()
        kind = str(track.get("kind") or "").strip().lower()
        if not _SUBTITLE_LANGUAGE_RE.fullmatch(language) or kind not in _SUBTITLE_KIND_LABELS:
            continue
        key = (language, kind)
        if key in seen:
            continue
        seen.add(key)
        labels.append(f"{language} {_SUBTITLE_KIND_LABELS[kind]}")
    return " · ".join(labels) if labels else "—"


def section_display_text(section: dict[str, Any], fallback_index: int) -> str:
    title = str(section.get("title") or f"章节 {fallback_index + 1}")
    total = _safe_index(section.get("itemCount"), 0)
    completed = min(_safe_index(section.get("completedCount"), 0), total)
    return f"{title} · {completed}/{total}" if total else title


def navigation_target(item: dict[str, Any], direction: str) -> str:
    field = {"previous": "previousItemId", "next": "nextItemId"}.get(direction)
    if field is None:
        return ""
    target = str(item.get(field) or "").strip().lower()
    return target if _ITEM_ID_RE.fullmatch(target) else ""


def _item_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    return (_safe_index(item.get("courseItemIndex")), str(item.get("id") or ""))


def resume_action_text(result: dict[str, Any]) -> str:
    """Render a path-safe Desktop status from the shared Resume contract."""
    resume = result.get("resume") if isinstance(result.get("resume"), dict) else {}
    state = str(resume.get("state") or "empty")
    item = resume.get("item") if isinstance(resume.get("item"), dict) else {}
    title = str(item.get("title") or "课时").strip()[:160] or "课时"
    if result.get("opened"):
        if state == "resume":
            return f"已从 {_safe_progress(resume.get('progressSeconds')):.0f}s 继续：{title}"
        return f"已开始：{title}"
    if state == "completed":
        return "课程已完成"
    if state == "empty":
        return "没有可播放的本地课时"
    return "未能打开课程播放器"


def build_navigation_tab(notebook, api) -> None:
    tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14)
    notebook.add(tab, text="导航 / 字幕")

    header = tk.Frame(tab, bg=ui.PANEL)
    header.pack(fill="x")
    text = tk.Frame(header, bg=ui.PANEL)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "章节导航与字幕", size=10, weight="bold").pack(anchor="w")
    ui._label(
        text,
        "快速跳转章节和课时；仅展示字幕语言与人工/自动类型，不保存或显示签名字幕 URL。",
        size=7,
        color=ui.MUTED,
    ).pack(anchor="w", pady=(2, 0))

    filters = tk.Frame(tab, bg=ui.PANEL)
    filters.pack(fill="x", pady=(12, 0))
    ui._label(filters, "课程", size=7, color=ui.MUTED).pack(side="left")
    course_var = tk.StringVar()
    course_combo = ttk.Combobox(filters, textvariable=course_var, state="readonly", width=34)
    course_combo.pack(side="left", padx=(6, 14))
    ui._label(filters, "章节", size=7, color=ui.MUTED).pack(side="left")
    section_var = tk.StringVar()
    section_combo = ttk.Combobox(filters, textvariable=section_var, state="readonly", width=38)
    section_combo.pack(side="left", padx=(6, 0), fill="x", expand=True)

    tree = ttk.Treeview(tab, columns=("progress", "subtitles"), show="tree headings", selectmode="browse")
    tree.heading("#0", text="章节 / 课时")
    tree.heading("progress", text="进度")
    tree.heading("subtitles", text="字幕")
    tree.column("#0", width=430, minwidth=220, stretch=True)
    tree.column("progress", width=100, minwidth=80, anchor="center", stretch=False)
    tree.column("subtitles", width=260, minwidth=160, stretch=True)
    tree.pack(fill="both", expand=True, pady=(12, 0))

    status = tk.StringVar(value="选择课程查看章节")
    courses: list[dict[str, Any]] = []
    course_labels: dict[str, str] = {}
    sections_by_label: dict[str, str] = {}
    section_label_by_key: dict[str, str] = {}
    item_by_tree_id: dict[str, dict[str, Any]] = {}
    tree_id_by_item_id: dict[str, str] = {}

    def selected_course() -> dict[str, Any] | None:
        course_id = course_labels.get(course_var.get(), "")
        return next((course for course in courses if str(course.get("id") or "") == course_id), None)

    def selected_item() -> dict[str, Any] | None:
        selection = tree.selection()
        return item_by_tree_id.get(selection[0]) if selection else None

    def select_item_id(item_id: str) -> None:
        iid = tree_id_by_item_id.get(item_id, "")
        if iid:
            tree.selection_set(iid)
            tree.focus(iid)
            tree.see(iid)

    def update_controls(*_args) -> None:
        item = selected_item()
        previous_button.state(["!disabled"] if item and navigation_target(item, "previous") else ["disabled"])
        next_button.state(["!disabled"] if item and navigation_target(item, "next") else ["disabled"])
        resume_button.state(["!disabled"] if selected_course() else ["disabled"])
        selection = tree.selection()
        if selection:
            label = section_label_by_key.get(tree.parent(selection[0]), "")
            if label:
                section_var.set(label)

    def insert_item(parent: str, item: dict[str, Any]) -> None:
        item_id = str(item.get("id") or "").strip().lower()
        if not _ITEM_ID_RE.fullmatch(item_id):
            return
        iid = f"item:{item_id}"
        progress = "✓ 已完成" if item.get("completed") else f"{_safe_progress(item.get('progressSeconds')):.0f}s"
        tree.insert(
            parent,
            "end",
            iid=iid,
            text=str(item.get("title") or item.get("fileName") or "未命名课时"),
            values=(progress, subtitle_tracks_text(item)),
        )
        item_by_tree_id[iid] = item
        tree_id_by_item_id[item_id] = iid

    def render_course(payload: dict[str, Any]) -> None:
        for child in tree.get_children():
            tree.delete(child)
        item_by_tree_id.clear()
        tree_id_by_item_id.clear()
        sections_by_label.clear()
        section_label_by_key.clear()
        sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        items_by_section: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            if isinstance(item, dict):
                items_by_section.setdefault(str(item.get("sectionId") or ""), []).append(item)

        section_labels: list[str] = []
        valid_section_count = 0
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            valid_section_count += 1
            section_id = str(section.get("id") or "")
            key = f"section:{section_id or index}"
            label = section_display_text(section, index)
            choice = f"{len(section_labels) + 1}. {label}"
            sections_by_label[choice] = key
            section_label_by_key[key] = choice
            section_labels.append(choice)
            tree.insert("", "end", iid=key, text=label, values=("", ""), open=True)
            for item in sorted(items_by_section.pop(section_id, []), key=_item_sort_key):
                insert_item(key, item)

        remaining = sorted([item for rows in items_by_section.values() for item in rows], key=_item_sort_key)
        if remaining:
            key = "section:unsectioned"
            choice = f"{len(section_labels) + 1}. 未分组课时"
            sections_by_label[choice] = key
            section_label_by_key[key] = choice
            section_labels.append(choice)
            tree.insert("", "end", iid=key, text="未分组课时", values=("", ""), open=True)
            for item in remaining:
                insert_item(key, item)

        section_combo["values"] = section_labels
        section_var.set(section_labels[0] if section_labels else "")
        first = next(iter(item_by_tree_id), "")
        if first:
            tree.selection_set(first)
            tree.focus(first)
            tree.see(first)
        status.set(f"{valid_section_count} 个章节 · {len(item_by_tree_id)} 个课时")
        update_controls()

    def refresh_course(*_args) -> None:
        course = selected_course()
        if course is None:
            render_course({"sections": [], "items": []})
            return
        try:
            payload = api.items(course["id"], limit=5000)
        except Exception:  # noqa: BLE001
            status.set("课程导航读取失败")
            return
        render_course(payload)

    def refresh_courses() -> None:
        previous_id = str((selected_course() or {}).get("id") or "")
        try:
            courses[:] = api.courses(limit=500).get("courses", [])
        except Exception:  # noqa: BLE001
            status.set("课程读取失败")
            return
        course_labels.clear()
        values: list[str] = []
        selected_label = ""
        for index, course in enumerate(courses):
            label = f"{index + 1}. {str(course.get('name') or '未命名课程')}"
            course_labels[label] = str(course.get("id") or "")
            values.append(label)
            if previous_id and course_labels[label] == previous_id:
                selected_label = label
        course_combo["values"] = values
        course_var.set(selected_label or values[0] if values else "")
        refresh_course()

    def jump_section(*_args) -> None:
        key = sections_by_label.get(section_var.get(), "")
        if not key:
            return
        children = tree.get_children(key)
        target = children[0] if children else key
        tree.selection_set(target)
        tree.focus(target)
        tree.see(target)
        update_controls()

    def move(direction: str) -> None:
        item = selected_item()
        target = navigation_target(item, direction) if item else ""
        if target:
            select_item_id(target)
            update_controls()

    def resume_course() -> None:
        course = selected_course()
        if course is None:
            status.set("请选择课程")
            return
        try:
            result = launch_desktop_course_resume(api, course["id"])
        except Exception:  # noqa: BLE001
            status.set("续播失败")
            return
        status.set(resume_action_text(result))
        refresh_course()

    actions = tk.Frame(tab, bg=ui.PANEL)
    actions.pack(fill="x", pady=(10, 0))
    ui._label(actions, variable=status, size=8, color=ui.MUTED).pack(side="left", fill="x", expand=True)
    resume_button = ui.ActionButton(actions, text="继续学习", command=resume_course, kind="secondary", compact=True)
    resume_button.pack(side="right")
    next_button = ui.ActionButton(actions, text="下一课 →", command=lambda: move("next"), kind="ghost", compact=True)
    next_button.pack(side="right", padx=(0, 6))
    previous_button = ui.ActionButton(actions, text="← 上一课", command=lambda: move("previous"), kind="ghost", compact=True)
    previous_button.pack(side="right", padx=(0, 6))
    ui.ActionButton(actions, text="刷新", command=refresh_courses, kind="ghost", compact=True).pack(side="right", padx=(0, 6))

    course_combo.bind("<<ComboboxSelected>>", refresh_course)
    section_combo.bind("<<ComboboxSelected>>", jump_section)
    tree.bind("<<TreeviewSelect>>", update_controls)
    refresh_courses()