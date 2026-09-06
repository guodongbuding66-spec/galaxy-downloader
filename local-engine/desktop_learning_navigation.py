from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

import desktop_ui as ui

_SUBTITLE_KIND_LABELS = {"manual": "人工", "automatic": "自动"}


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
        language = str(track.get("language") or "").strip()[:32]
        kind = str(track.get("kind") or "").strip().lower()
        if not language or kind not in _SUBTITLE_KIND_LABELS:
            continue
        key = (language, kind)
        if key in seen:
            continue
        seen.add(key)
        labels.append(f"{language} {_SUBTITLE_KIND_LABELS[kind]}")
    return " · ".join(labels) if labels else "—"


def section_display_text(section: dict[str, Any], fallback_index: int) -> str:
    title = str(section.get("title") or f"章节 {fallback_index + 1}")
    try:
        total = max(0, int(section.get("itemCount") or 0))
    except (TypeError, ValueError):
        total = 0
    try:
        completed = max(0, min(int(section.get("completedCount") or 0), total))
    except (TypeError, ValueError):
        completed = 0
    return f"{title} · {completed}/{total}" if total else title


def navigation_target(item: dict[str, Any], direction: str) -> str:
    field = {"previous": "previousItemId", "next": "nextItemId"}.get(direction)
    if field is None:
        return ""
    target = str(item.get(field) or "").strip().lower()
    if len(target) != 32 or any(ch not in "0123456789abcdef" for ch in target):
        return ""
    return target


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

    tree = ttk.Treeview(
        tab,
        columns=("progress", "subtitles"),
        show="tree headings",
        selectmode="browse",
    )
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
        label = course_var.get()
        course_id = course_labels.get(label, "")
        for course in courses:
            if str(course.get("id") or "") == course_id:
                return course
        return None

    def selected_item() -> dict[str, Any] | None:
        selection = tree.selection()
        if not selection:
            return None
        return item_by_tree_id.get(selection[0])

    def select_item_id(item_id: str) -> None:
        iid = tree_id_by_item_id.get(item_id, "")
        if not iid:
            return
        tree.selection_set(iid)
        tree.focus(iid)
        tree.see(iid)

    def update_controls(*_args) -> None:
        item = selected_item()
        if item is None:
            previous_button.state(["disabled"])
            next_button.state(["disabled"])
            return
        if navigation_target(item, "previous"):
            previous_button.state(["!disabled"])
        else:
            previous_button.state(["disabled"])
        if navigation_target(item, "next"):
            next_button.state(["!disabled"])
        else:
            next_button.state(["disabled"])
        parent = tree.parent(tree.selection()[0]) if tree.selection() else ""
        label = section_label_by_key.get(parent, "")
        if label:
            section_var.set(label)

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
            if not isinstance(item, dict):
                continue
            items_by_section.setdefault(str(item.get("sectionId") or ""), []).append(item)

        section_labels: list[str] = []
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            section_id = str(section.get("id") or "")
            key = f"section:{section_id or index}"
            label = section_display_text(section, index)
            choice = f"{index + 1}. {label}"
            sections_by_label[choice] = key
            section_label_by_key[key] = choice
            section_labels.append(choice)
            tree.insert("", "end", iid=key, text=label, values=("", ""), open=True)
            rows = items_by_section.pop(section_id, [])
            rows.sort(key=lambda row: (int(row.get("courseItemIndex") or 10**9), str(row.get("id") or "")))
            for item in rows:
                item_id = str(item.get("id") or "").strip().lower()
                if not item_id:
                    continue
                iid = f"item:{item_id}"
                progress = "✓ 已完成" if item.get("completed") else f"{float(item.get('progressSeconds') or 0):.0f}s"
                tree.insert(
                    key,
                    "end",
                    iid=iid,
                    text=str(item.get("title") or item.get("fileName") or "未命名课时"),
                    values=(progress, subtitle_tracks_text(item)),
                )
                item_by_tree_id[iid] = item
                tree_id_by_item_id[item_id] = iid

        remaining = [item for rows in items_by_section.values() for item in rows]
        if remaining:
            key = "section:unsectioned"
            choice = f"{len(section_labels) + 1}. 未分组课时"
            sections_by_label[choice] = key
            section_label_by_key[key] = choice
            section_labels.append(choice)
            tree.insert("", "end", iid=key, text="未分组课时", values=("", ""), open=True)
            remaining.sort(key=lambda row: (int(row.get("courseItemIndex") or 10**9), str(row.get("id") or "")))
            for item in remaining:
                item_id = str(item.get("id") or "").strip().lower()
                if not item_id:
                    continue
                iid = f"item:{item_id}"
                progress = "✓ 已完成" if item.get("completed") else f"{float(item.get('progressSeconds') or 0):.0f}s"
                tree.insert(
                    key,
                    "end",
                    iid=iid,
                    text=str(item.get("title") or item.get("fileName") or "未命名课时"),
                    values=(progress, subtitle_tracks_text(item)),
                )
                item_by_tree_id[iid] = item
                tree_id_by_item_id[item_id] = iid

        section_combo["values"] = section_labels
        section_var.set(section_labels[0] if section_labels else "")
        first = next(iter(item_by_tree_id), "")
        if first:
            tree.selection_set(first)
            tree.focus(first)
            tree.see(first)
        status.set(f"{len(sections)} 个章节 · {len(item_by_tree_id)} 个课时")
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
        if values:
            course_var.set(selected_label or values[0])
        else:
            course_var.set("")
        refresh_course()

    def jump_section(*_args) -> None:
        key = sections_by_label.get(section_var.get(), "")
        if not key:
            return
        tree.selection_set(key)
        tree.focus(key)
        tree.see(key)
        children = tree.get_children(key)
        if children:
            tree.selection_set(children[0])
            tree.focus(children[0])
            tree.see(children[0])
        update_controls()

    def move(direction: str) -> None:
        item = selected_item()
        if item is None:
            return
        target = navigation_target(item, direction)
        if target:
            select_item_id(target)
            update_controls()

    actions = tk.Frame(tab, bg=ui.PANEL)
    actions.pack(fill="x", pady=(10, 0))
    ui._label(actions, variable=status, size=8, color=ui.MUTED).pack(side="left", fill="x", expand=True)
    next_button = ui.ActionButton(
        actions,
        text="下一课 →",
        command=lambda: move("next"),
        kind="secondary",
        compact=True,
    )
    next_button.pack(side="right")
    previous_button = ui.ActionButton(
        actions,
        text="← 上一课",
        command=lambda: move("previous"),
        kind="ghost",
        compact=True,
    )
    previous_button.pack(side="right", padx=(0, 6))
    ui.ActionButton(
        actions,
        text="刷新",
        command=refresh_courses,
        kind="ghost",
        compact=True,
    ).pack(side="right", padx=(0, 6))

    course_combo.bind("<<ComboboxSelected>>", refresh_course)
    section_combo.bind("<<ComboboxSelected>>", jump_section)
    tree.bind("<<TreeviewSelect>>", update_controls)
    refresh_courses()
