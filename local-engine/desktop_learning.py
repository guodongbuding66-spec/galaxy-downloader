from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook
from headless_learning_api import HeadlessLearningApi


def _api(engine_module) -> HeadlessLearningApi:
    return HeadlessLearningApi(engine_module.default_download_dir())


def _show_learning(window, engine_module) -> None:
    existing = getattr(window, "_learning_workspace_window", None)
    if existing is not None:
        try:
            existing.deiconify(); existing.lift(); return
        except tk.TclError:
            pass
    dialog = tk.Toplevel(window)
    window._learning_workspace_window = dialog
    dialog.title("学习中心 · Galaxy Local Engine")
    dialog.geometry("1000x700")
    dialog.minsize(860, 580)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=18, pady=16); shell.pack(fill="both", expand=True)
    ui._label(shell, "课程与复习", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(shell, "课程媒体 · 时间戳笔记 · 进度 · Flashcards / Spaced Repetition", size=8, color=ui.MUTED, bg=ui.BG).pack(anchor="w", pady=(3, 10))

    api = _api(engine_module)
    notebook = ttk.Notebook(shell); notebook.pack(fill="both", expand=True)
    courses_tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14); notebook.add(courses_tab, text="课程")
    cards_tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14); notebook.add(cards_tab, text="复习卡")

    course_name = tk.StringVar(value="新课程"); source_url = tk.StringVar(); status = tk.StringVar(value="就绪")
    top = tk.Frame(courses_tab, bg=ui.PANEL); top.pack(fill="x")
    for label, var, width in (("课程名", course_name, 20), ("来源 URL", source_url, 42)):
        ui._label(top, label, size=7, color=ui.MUTED).pack(side="left")
        tk.Entry(top, textvariable=var, width=width, bg=ui.BG, fg=ui.TEXT, insertbackground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER).pack(side="left", padx=(6, 12), fill="x", expand=label == "来源 URL")

    columns = tk.Frame(courses_tab, bg=ui.PANEL); columns.pack(fill="both", expand=True, pady=(12, 0))
    course_list = tk.Listbox(columns, bg=ui.BG, fg=ui.TEXT, selectbackground=ui.PANEL_3, selectforeground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER)
    item_list = tk.Listbox(columns, bg=ui.BG, fg=ui.TEXT, selectbackground=ui.PANEL_3, selectforeground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER)
    course_list.pack(side="left", fill="both", expand=True)
    item_list.pack(side="left", fill="both", expand=True, padx=(10, 0))
    courses: list[dict] = []; items: list[dict] = []

    progress_var = tk.StringVar(value="0"); note_var = tk.StringVar()
    edit = tk.Frame(courses_tab, bg=ui.PANEL); edit.pack(fill="x", pady=(10, 0))
    ui._label(edit, "进度(s)", size=7, color=ui.MUTED).pack(side="left")
    tk.Entry(edit, textvariable=progress_var, width=10, bg=ui.BG, fg=ui.TEXT, insertbackground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER).pack(side="left", padx=(6, 10))
    ui._label(edit, "笔记", size=7, color=ui.MUTED).pack(side="left")
    tk.Entry(edit, textvariable=note_var, bg=ui.BG, fg=ui.TEXT, insertbackground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER).pack(side="left", padx=(6, 0), fill="x", expand=True)

    def selected_course():
        s = course_list.curselection(); return courses[s[0]] if s else None
    def selected_item():
        s = item_list.curselection(); return items[s[0]] if s else None
    def refresh_items(*_args) -> None:
        items.clear(); item_list.delete(0, "end")
        course = selected_course()
        if not course: return
        data = api.items(course["id"])
        items.extend(data.get("items", []))
        for item in items:
            mark = "✓" if item.get("completed") else f"{float(item.get('progressSeconds') or 0):.0f}s"
            item_list.insert("end", f"{mark} · {item.get('title') or item.get('mediaId')}")
        if items: item_list.selection_set(0)
    course_list.bind("<<ListboxSelect>>", refresh_items)

    def refresh_courses() -> None:
        courses[:] = api.courses(limit=500).get("courses", [])
        course_list.delete(0, "end")
        for course in courses:
            course_list.insert("end", f"{course.get('name')} · {course.get('itemCount', 0)} 项")
        if courses: course_list.selection_set(0)
        refresh_items()

    def create() -> None:
        try:
            api.create_course({"name": course_name.get(), "sourceUrl": source_url.get(), "provider": "generic"})
            status.set("课程已创建"); refresh_courses()
        except Exception as exc: status.set(f"失败：{exc}")

    def save_progress(completed: bool = False) -> None:
        item = selected_item()
        if not item: return
        try:
            api.set_progress(item["id"], {"progressSeconds": float(progress_var.get() or 0), "completed": completed})
            status.set("进度已保存"); refresh_items()
        except Exception as exc: status.set(f"失败：{exc}")

    def add_note() -> None:
        item = selected_item()
        if not item: return
        try:
            api.create_note(item["id"], {"timestampSeconds": float(progress_var.get() or 0), "body": note_var.get()})
            status.set("笔记已保存"); note_var.set("")
        except Exception as exc: status.set(f"失败：{exc}")

    actions = tk.Frame(courses_tab, bg=ui.PANEL); actions.pack(fill="x", pady=(10, 0))
    ui._label(actions, variable=status, size=8, color=ui.MUTED).pack(side="left")
    ui.ActionButton(actions, text="创建课程", command=create, kind="secondary", compact=True).pack(side="right")
    ui.ActionButton(actions, text="保存笔记", command=add_note, kind="ghost", compact=True).pack(side="right", padx=(0, 6))
    ui.ActionButton(actions, text="标记完成", command=lambda: save_progress(True), kind="ghost", compact=True).pack(side="right", padx=(0, 6))
    ui.ActionButton(actions, text="保存进度", command=lambda: save_progress(False), kind="ghost", compact=True).pack(side="right", padx=(0, 6))

    front_var = tk.StringVar(); back_var = tk.StringVar(); rating_var = tk.StringVar(value="good"); cards_status = tk.StringVar(value="就绪")
    card_list = tk.Listbox(cards_tab, bg=ui.BG, fg=ui.TEXT, selectbackground=ui.PANEL_3, selectforeground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER)
    card_list.pack(fill="both", expand=True)
    cards: list[dict] = []
    form = tk.Frame(cards_tab, bg=ui.PANEL); form.pack(fill="x", pady=(10, 0))
    for label, var in (("正面", front_var), ("背面", back_var)):
        ui._label(form, label, size=7, color=ui.MUTED).pack(side="left")
        tk.Entry(form, textvariable=var, bg=ui.BG, fg=ui.TEXT, insertbackground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER).pack(side="left", padx=(6, 10), fill="x", expand=True)
    ttk.Combobox(form, textvariable=rating_var, values=("again", "hard", "good", "easy"), state="readonly", width=8).pack(side="left")

    def selected_card():
        s = card_list.curselection(); return cards[s[0]] if s else None
    def refresh_cards() -> None:
        cards[:] = api.flashcards(due_only=False, limit=1000).get("flashcards", [])
        card_list.delete(0, "end")
        for card in cards:
            card_list.insert("end", f"{card.get('front')} → {card.get('back')} · due {card.get('dueAt','')}")
        if cards: card_list.selection_set(0)
    def create_card() -> None:
        try:
            api.create_flashcard({"front": front_var.get(), "back": back_var.get()}); cards_status.set("已创建"); refresh_cards()
        except Exception as exc: cards_status.set(f"失败：{exc}")
    def review() -> None:
        card = selected_card()
        if not card: return
        try:
            api.review_flashcard(card["id"], {"rating": rating_var.get()}); cards_status.set("复习结果已记录"); refresh_cards()
        except Exception as exc: cards_status.set(f"失败：{exc}")
    card_actions = tk.Frame(cards_tab, bg=ui.PANEL); card_actions.pack(fill="x", pady=(10, 0))
    ui._label(card_actions, variable=cards_status, size=8, color=ui.MUTED).pack(side="left")
    ui.ActionButton(card_actions, text="创建卡片", command=create_card, kind="secondary", compact=True).pack(side="right")
    ui.ActionButton(card_actions, text="记录复习", command=review, kind="ghost", compact=True).pack(side="right", padx=(0, 6))

    def close() -> None:
        window._learning_workspace_window = None; dialog.destroy()
    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh_courses(); refresh_cards()


def _add_learning_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_learning_entry_built", False): return
    card = tk.Frame(panel, bg=ui.PANEL_2); card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2); text.pack(side="left", fill="x", expand=True)
    ui._label(text, "课程 / 学习", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(text, "课程媒体 · 时间戳笔记 · 进度 · Spaced Repetition", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(card, text="打开学习中心", command=lambda: _show_learning(window, engine_module), kind="secondary", compact=True).pack(side="right")
    window._galaxy_learning_entry_built = True


def install_desktop_learning(engine_module):
    cls = engine_module.EngineWindow
    if getattr(cls, "_galaxy_desktop_learning_installed", False): return cls
    register_after_build_ui_hook(cls, "desktop-learning", lambda window: _add_learning_entry(window, engine_module), order=55)
    cls._galaxy_desktop_learning_installed = True
    return cls


def run_desktop_learning_self_test() -> None:
    assert callable(HeadlessLearningApi)
