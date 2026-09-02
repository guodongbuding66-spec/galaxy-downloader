from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Any, Callable

from desktop_hooks import run_after_build_ui_hooks, run_queue_row_hooks, run_queue_tick_hooks
from media_policy import aria2c_available, load_preferences, save_preferences
from update_check import check_latest_stable

BG = "#080C14"
PANEL = "#0F1624"
PANEL_2 = "#141E30"
PANEL_3 = "#1A2740"
BORDER = "#25324B"
BORDER_SOFT = "#1C2940"
TEXT = "#F6F8FC"
MUTED = "#9AA6BB"
SUBTLE = "#6F7D95"
ACCENT = "#7C6CFF"
ACCENT_HOVER = "#9185FF"
CYAN = "#36D7C4"
SUCCESS = "#45D18A"
DANGER = "#FF6278"
DANGER_HOVER = "#FF788B"
WARNING = "#F2B84B"
WEBSITE_URL = "https://galaxy-downloader.guodongbuding66.workers.dev/zh"

SPONSOR_LABELS: tuple[tuple[str, str], ...] = (
    ("sponsor", "赞助"),
    ("selfpromo", "自我推广"),
    ("interaction", "互动提醒"),
    ("intro", "片头"),
    ("outro", "片尾"),
    ("preview", "预告/回顾"),
    ("music_offtopic", "离题音乐"),
    ("filler", "填充片段"),
)


class ActionButton(tk.Button):
    """Flat button that preserves ttk-style state([...]) calls used by engine.py."""

    def __init__(
        self,
        master,
        *,
        text: str,
        command: Callable[[], None],
        kind: str = "secondary",
        width: int | None = None,
        compact: bool = False,
    ) -> None:
        palette = {
            "primary": (ACCENT, TEXT, ACCENT_HOVER),
            "danger": (DANGER, "#180408", DANGER_HOVER),
            "secondary": (PANEL_3, TEXT, "#233352"),
            "ghost": (PANEL, MUTED, PANEL_2),
        }
        self._base, foreground, self._hover = palette[kind]
        kwargs: dict[str, Any] = {
            "text": text,
            "command": command,
            "font": ("Segoe UI", 8 if compact else 9, "bold"),
            "bg": self._base,
            "fg": foreground,
            "activebackground": self._hover,
            "activeforeground": foreground,
            "disabledforeground": SUBTLE,
            "relief": "flat",
            "bd": 0,
            "highlightthickness": 0,
            "padx": 9 if compact else 14,
            "pady": 5 if compact else 8,
            "cursor": "hand2",
        }
        if width is not None:
            kwargs["width"] = width
        super().__init__(master, **kwargs)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _event=None) -> None:
        if str(self["state"]) != "disabled":
            self.configure(bg=self._hover)

    def _on_leave(self, _event=None) -> None:
        self.configure(bg=self._base)

    def state(self, spec: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        values = set(spec)
        if "disabled" in values:
            self.configure(state="disabled", cursor="arrow")
        if "!disabled" in values:
            self.configure(state="normal", cursor="hand2")
        return ("disabled",) if str(self["state"]) == "disabled" else ()


def _label(
    master,
    text: str | None = None,
    *,
    variable=None,
    size=9,
    weight="normal",
    color=TEXT,
    bg=PANEL,
    **kwargs,
):
    return tk.Label(
        master,
        text=text,
        textvariable=variable,
        font=("Segoe UI", size, weight),
        bg=bg,
        fg=color,
        **kwargs,
    )


def _divider(master, *, bg=PANEL) -> tk.Frame:
    return tk.Frame(master, bg=BORDER_SOFT, height=1)


def _section_title(master, title: str, subtitle: str | None = None, *, bg=PANEL):
    frame = tk.Frame(master, bg=bg)
    _label(frame, title, size=10, weight="bold", bg=bg).pack(anchor="w")
    if subtitle:
        _label(frame, subtitle, size=8, color=MUTED, bg=bg).pack(anchor="w", pady=(2, 0))
    return frame


def _make_window_icon(master: tk.Misc, size: int = 32) -> tk.PhotoImage:
    image = tk.PhotoImage(master=master, width=size, height=size)
    image.put(BG, to=(0, 0, size, size))
    cx = cy = size / 2
    outer = size * 0.37
    inner = size * 0.30
    for y in range(size):
        for x in range(size):
            distance = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
            if inner <= distance <= outer:
                image.put(ACCENT, (x, y))
    for y in range(int(size * 0.22), int(size * 0.56)):
        image.put(CYAN, to=(int(size * 0.45), y, int(size * 0.56), y + 1))
    mid = int(size * 0.5)
    for offset in range(max(1, int(size * 0.18))):
        y = int(size * 0.49) + offset
        image.put(CYAN, to=(mid - offset, y, mid + offset + 1, y + 1))
    return image


def _draw_brand_mark(canvas: tk.Canvas) -> None:
    canvas.delete("all")
    canvas.create_oval(8, 8, 52, 52, outline=ACCENT, width=4)
    canvas.create_arc(2, 16, 58, 46, start=198, extent=144, style="arc", outline="#B4A8FF", width=2)
    canvas.create_line(30, 14, 30, 34, fill=CYAN, width=5, capstyle="round")
    canvas.create_line(21, 29, 30, 39, 39, 29, fill=CYAN, width=5, joinstyle="round", capstyle="round")
    canvas.create_oval(46, 15, 51, 20, fill=CYAN, outline="")


def _status_chip(master, label: str, ready: bool, optional: bool = False) -> tk.Frame:
    frame = tk.Frame(master, bg=PANEL_2, padx=9, pady=5, highlightthickness=1, highlightbackground=BORDER_SOFT)
    dot_color = SUCCESS if ready else (SUBTLE if optional else DANGER)
    dot = tk.Canvas(frame, width=8, height=8, bg=PANEL_2, bd=0, highlightthickness=0)
    dot.create_oval(1, 1, 7, 7, fill=dot_color, outline="")
    dot.pack(side="left", padx=(0, 5))
    _label(frame, label, size=7, weight="bold", color=MUTED, bg=PANEL_2).pack(side="left")
    return frame


def _metric(master, title: str, variable: tk.Variable) -> tk.Frame:
    frame = tk.Frame(master, bg=PANEL_2, padx=12, pady=10, highlightthickness=1, highlightbackground=BORDER_SOFT)
    _label(frame, title, size=7, color=SUBTLE, bg=PANEL_2).pack(anchor="w")
    _label(frame, variable=variable, size=10, weight="bold", bg=PANEL_2).pack(anchor="w", pady=(3, 0))
    return frame


def install_desktop_ui(engine_module):
    """Install the v0.10 desktop workbench without changing download semantics."""
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_ui_installed", False):
        return window_cls

    def build_ui(window) -> None:
        window.configure(bg=BG)
        window.geometry("1060x780")
        window.minsize(940, 700)
        # Tcl parses string font descriptors as lists; quote multi-word families.
        window.option_add("*Font", "{Segoe UI} 9")
        try:
            window.tk.call("tk", "scaling", 1.0)
        except tk.TclError:
            pass

        icon = _make_window_icon(window, 32)
        window._galaxy_icon = icon
        try:
            window.iconphoto(True, icon)
        except tk.TclError:
            pass

        style = ttk.Style(window)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Galaxy.Horizontal.TProgressbar",
            troughcolor=PANEL_3,
            background=ACCENT,
            bordercolor=PANEL_3,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=9,
        )
        style.configure(
            "Galaxy.TCombobox",
            fieldbackground=BG,
            background=PANEL_3,
            foreground=TEXT,
            arrowcolor=MUTED,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
        )

        root = tk.Frame(window, bg=BG, padx=22, pady=18)
        root.pack(fill="both", expand=True)

        header = tk.Frame(root, bg=BG)
        header.pack(fill="x")
        brand = tk.Frame(header, bg=BG)
        brand.pack(side="left", fill="x", expand=True)
        mark = tk.Canvas(brand, width=60, height=60, bg=BG, bd=0, highlightthickness=0)
        mark.pack(side="left", padx=(0, 12))
        _draw_brand_mark(mark)
        brand_text = tk.Frame(brand, bg=BG)
        brand_text.pack(side="left", pady=(5, 0))
        _label(brand_text, "Galaxy Local Engine", size=17, weight="bold", bg=BG).pack(anchor="w")
        _label(
            brand_text,
            f"SparkDownloader 本机媒体工作台 · v{engine_module.VERSION}",
            size=8,
            color=MUTED,
            bg=BG,
        ).pack(anchor="w", pady=(3, 0))

        header_actions = tk.Frame(header, bg=BG)
        header_actions.pack(side="right", anchor="n", pady=(8, 0))
        ActionButton(
            header_actions,
            text="打开 SparkDownloader",
            command=lambda: webbrowser.open(WEBSITE_URL),
            kind="ghost",
            compact=True,
        ).pack(side="left", padx=(0, 8))
        window._copy_diag_button = ActionButton(
            header_actions,
            text="复制诊断信息",
            command=lambda: _copy_diagnostics(window, engine_module),
            kind="ghost",
            compact=True,
        )
        window._copy_diag_button.pack(side="left")

        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, pady=(17, 0))
        body.grid_columnconfigure(0, weight=7, uniform="layout")
        body.grid_columnconfigure(1, weight=3, uniform="layout")
        body.grid_rowconfigure(0, weight=1)

        main = tk.Frame(body, bg=PANEL, padx=20, pady=18, highlightthickness=1, highlightbackground=BORDER)
        main.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        side = tk.Frame(body, bg=PANEL, padx=16, pady=16, highlightthickness=1, highlightbackground=BORDER)
        side.grid(row=0, column=1, sticky="nsew", padx=(9, 0))

        eyebrow = tk.Frame(main, bg=PANEL)
        eyebrow.pack(fill="x")
        _label(eyebrow, "CURRENT JOB", size=7, weight="bold", color=SUBTLE).pack(side="left")
        window._queue_summary_var = tk.StringVar(value="等待 0 项")
        queue_badge = tk.Frame(eyebrow, bg=PANEL_2, padx=8, pady=4)
        queue_badge.pack(side="right")
        _label(queue_badge, variable=window._queue_summary_var, size=7, weight="bold", color=CYAN, bg=PANEL_2).pack()

        _label(main, variable=window.status_var, size=16, weight="bold").pack(anchor="w", pady=(7, 0))
        detail = _label(
            main,
            variable=window.detail_var,
            size=9,
            color=MUTED,
            justify="left",
            anchor="w",
            wraplength=650,
        )
        detail.pack(fill="x", pady=(7, 14))

        progress = tk.Frame(main, bg=PANEL)
        progress.pack(fill="x")
        ttk.Progressbar(
            progress,
            variable=window.percent_var,
            maximum=100,
            style="Galaxy.Horizontal.TProgressbar",
        ).pack(fill="x")
        window._percent_text_var = tk.StringVar(value="0%")
        _label(progress, variable=window._percent_text_var, size=8, weight="bold", color=MUTED).pack(anchor="e", pady=(5, 0))

        stats = tk.Frame(main, bg=PANEL)
        stats.pack(fill="x", pady=(12, 0))
        metrics = (("速度", window.speed_var), ("剩余时间", window.eta_var), ("已下载", window.size_var))
        for index, (title, variable) in enumerate(metrics):
            stats.grid_columnconfigure(index, weight=1)
            cell = _metric(stats, title, variable)
            cell.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 5, 5 if index < 2 else 0))

        advanced = tk.Frame(main, bg=PANEL)
        advanced.pack(fill="x", pady=(16, 0))
        window._advanced_open = False
        toggle_row = tk.Frame(advanced, bg=PANEL)
        toggle_row.pack(fill="x")
        window._advanced_toggle_var = tk.StringVar(value="高级下载工作台  ›")
        toggle = tk.Button(
            toggle_row,
            textvariable=window._advanced_toggle_var,
            command=lambda: _toggle_advanced(window),
            font=("Segoe UI", 9, "bold"),
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=ACCENT_HOVER,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=0,
            pady=4,
        )
        toggle.pack(side="left")
        window._advanced_summary_var = tk.StringVar(value="片段 · 章节 · 字幕/音轨 · SponsorBlock · aria2c")
        _label(toggle_row, variable=window._advanced_summary_var, size=8, color=SUBTLE).pack(side="right")
        window._advanced_panel = tk.Frame(advanced, bg=PANEL_2, padx=14, pady=12, highlightthickness=1, highlightbackground=BORDER_SOFT)
        _build_advanced_panel(window, engine_module)

        actions = tk.Frame(main, bg=PANEL)
        actions.pack(fill="x", side="bottom", pady=(16, 0))
        window.cancel_button = ActionButton(actions, text="取消当前任务", command=window.cancel, kind="danger")
        window.cancel_button.pack(side="left")
        window.cancel_button.state(["disabled"])
        window.folder_button = ActionButton(actions, text="打开下载目录", command=window.open_folder, kind="secondary")
        window.folder_button.pack(side="right")

        queue_head = tk.Frame(side, bg=PANEL)
        queue_head.pack(fill="x")
        title = _section_title(queue_head, "下载队列", "当前任务结束后自动执行")
        title.pack(side="left", fill="x", expand=True)
        window._queue_clear_button = ActionButton(
            queue_head,
            text="清空",
            command=lambda: _clear_queue_from_ui(window),
            kind="ghost",
            compact=True,
        )
        window._queue_clear_button.pack(side="right", anchor="n")
        window._queue_clear_button.state(["disabled"])

        window._queue_count_var = tk.StringVar(value="当前 0 · 等待 0")
        _label(side, variable=window._queue_count_var, size=8, weight="bold", color=CYAN).pack(anchor="w", pady=(10, 9))
        window._queue_panel = tk.Frame(side, bg=PANEL)
        window._queue_panel.pack(fill="both", expand=True)

        system = tk.Frame(side, bg=PANEL)
        system.pack(fill="x", side="bottom", pady=(12, 0))
        _divider(system).pack(fill="x", pady=(0, 12))
        _label(system, "运行环境", size=9, weight="bold").pack(anchor="w")
        runtime = tk.Frame(system, bg=PANEL)
        runtime.pack(fill="x", pady=(8, 12))
        ffmpeg_ready = engine_module.ffmpeg_dir() is not None
        ytdlp_ready = engine_module.external_ytdlp_path(engine_module.app_dir()) is not None
        aria2_ready = aria2c_available(engine_module)
        _status_chip(runtime, "FFmpeg", ffmpeg_ready).pack(side="left", padx=(0, 5))
        _status_chip(runtime, "yt-dlp", ytdlp_ready).pack(side="left", padx=(0, 5))
        _status_chip(runtime, "aria2", aria2_ready, optional=True).pack(side="left")

        _label(system, "版本与更新", size=9, weight="bold").pack(anchor="w")
        window._latest_var = tk.StringVar(value=f"当前 v{engine_module.VERSION} · 未检查")
        _label(system, variable=window._latest_var, size=8, color=MUTED).pack(anchor="w", pady=(4, 8))
        window._update_button = ActionButton(
            system,
            text="检查稳定版更新",
            command=lambda: _check_update(window, engine_module),
            kind="ghost",
            compact=True,
        )
        window._update_button.pack(fill="x")
        _label(
            system,
            "更新只在你确认后打开 Release；不会静默替换 EXE。",
            size=7,
            color=SUBTLE,
            wraplength=245,
            justify="left",
        ).pack(anchor="w", pady=(7, 0))

        run_after_build_ui_hooks(window)
        window._galaxy_ui_tick()
        window._galaxy_queue_tick()

    def ui_tick(window) -> None:
        try:
            window._percent_text_var.set(f"{max(0, min(100, round(window.percent_var.get())))}%")
        except Exception:
            pass
        try:
            window.after(180, window._galaxy_ui_tick)
        except tk.TclError:
            pass

    def queue_tick(window) -> None:
        try:
            lock = getattr(window, "_queue_lock", None)
            if lock is not None:
                with lock:
                    pending = list(getattr(window, "pending_jobs", []))
            else:
                pending = list(getattr(window, "pending_jobs", []))
            waiting = len(pending)
            active = 1 if bool(getattr(window, "running", False)) else 0
            window._queue_summary_var.set(f"等待 {waiting} 项")
            window._queue_count_var.set(f"当前 {active} · 等待 {waiting}")
            if waiting:
                window._queue_clear_button.state(["!disabled"])
            else:
                window._queue_clear_button.state(["disabled"])
            _render_queue(window, pending)
        except Exception:
            pass
        try:
            window.after(650, window._galaxy_queue_tick)
        except tk.TclError:
            pass
        run_queue_tick_hooks(window)

    window_cls._build_ui = build_ui
    window_cls._galaxy_ui_tick = ui_tick
    window_cls._galaxy_queue_tick = queue_tick
    window_cls._galaxy_desktop_ui_installed = True
    return window_cls


def _render_queue(window, pending: list[Any]) -> None:
    panel = window._queue_panel
    for child in panel.winfo_children():
        child.destroy()
    if not pending:
        empty = tk.Frame(panel, bg=PANEL_2, padx=12, pady=15, highlightthickness=1, highlightbackground=BORDER_SOFT)
        empty.pack(fill="x")
        _label(empty, "队列为空", size=9, weight="bold", bg=PANEL_2).pack(anchor="w")
        _label(
            empty,
            "网页忙碌时继续提交即可排队，无需启动第二个 Engine。",
            size=8,
            color=MUTED,
            bg=PANEL_2,
            wraplength=245,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))
        return

    for index, queued in enumerate(pending[:8], start=1):
        row = tk.Frame(panel, bg=PANEL_2, padx=10, pady=8, highlightthickness=1, highlightbackground=BORDER_SOFT)
        row.pack(fill="x", pady=(0, 6))
        number = tk.Frame(row, bg=PANEL_3, padx=6, pady=4)
        number.pack(side="left", padx=(0, 8))
        _label(number, f"{index:02d}", size=7, weight="bold", color=ACCENT_HOVER, bg=PANEL_3).pack()
        text = tk.Frame(row, bg=PANEL_2)
        text.pack(side="left", fill="x", expand=True)
        label = str(getattr(queued, "label", "Queued download") or "Queued download")
        host = str(getattr(queued, "source_host", "") or "")
        _label(text, label[:34], size=8, weight="bold", bg=PANEL_2).pack(anchor="w")
        if host:
            _label(text, host[:32], size=7, color=SUBTLE, bg=PANEL_2).pack(anchor="w", pady=(2, 0))
        job_id = str(getattr(queued, "job_id", "") or "")
        if job_id:
            cancel = tk.Button(
                row,
                text="×",
                command=lambda value=job_id: _cancel_queued_from_ui(window, value),
                font=("Segoe UI", 10, "bold"),
                bg=PANEL_2,
                fg=SUBTLE,
                activebackground=PANEL_3,
                activeforeground=DANGER,
                relief="flat",
                bd=0,
                highlightthickness=0,
                cursor="hand2",
                padx=5,
                pady=2,
            )
            cancel.pack(side="right", padx=(5, 0))
        run_queue_row_hooks(window, row, queued, index - 1, pending)
    if len(pending) > 8:
        _label(panel, f"另有 {len(pending) - 8} 项等待", size=8, color=MUTED).pack(anchor="w", padx=3, pady=(1, 0))


def _cancel_queued_from_ui(window, job_id: str) -> None:
    removed = None
    lock = getattr(window, "_queue_lock", None)
    if lock is None:
        return
    with lock:
        pending = getattr(window, "pending_jobs", [])
        for index, queued in enumerate(pending):
            if str(getattr(queued, "job_id", "")) == job_id:
                removed = pending.pop(index)
                break
    if removed is not None:
        window.set_status(
            window.status_var.get(),
            f"已从等待队列移除：{str(getattr(removed, 'label', 'Queued download'))[:70]}",
        )


def _clear_queue_from_ui(window) -> None:
    clear = getattr(window, "clear_queued_jobs", None)
    if not callable(clear):
        return
    count = int(clear())
    if count:
        window.set_status(window.status_var.get(), f"已清空 {count} 个等待任务；当前任务不受影响。")


def _build_advanced_panel(window, engine_module) -> None:
    panel = window._advanced_panel
    preferences = load_preferences(engine_module)
    sponsor_values = set(preferences.get("sponsorBlockCategories") or [])
    window._media_pref_vars = {
        "segmentStart": tk.StringVar(value=str(preferences.get("segmentStart") or "")),
        "segmentEnd": tk.StringVar(value=str(preferences.get("segmentEnd") or "")),
        "splitChapters": tk.BooleanVar(value=bool(preferences.get("splitChapters", False))),
        "subtitleMode": tk.StringVar(value=str(preferences.get("subtitleMode") or "both")),
        "subtitleLanguages": tk.StringVar(value=",".join(preferences.get("subtitleLanguages") or [])),
        "audioLanguages": tk.StringVar(value=",".join(preferences.get("audioLanguages") or [])),
        "useAria2c": tk.BooleanVar(value=bool(preferences.get("useAria2c", False))),
    }
    for category, _label_text in SPONSOR_LABELS:
        window._media_pref_vars[f"sb:{category}"] = tk.BooleanVar(value=category in sponsor_values)

    presets = tk.Frame(panel, bg=PANEL_2)
    presets.pack(fill="x")
    _label(presets, "快捷方案", size=8, weight="bold", bg=PANEL_2).pack(side="left", padx=(0, 9))
    for key, label in (("standard", "标准"), ("course", "课程/播客"), ("clean", "去赞助"), ("fast", "高速")):
        button = ActionButton(
            presets,
            text=label,
            command=lambda value=key: _apply_preset(window, engine_module, value),
            kind="ghost",
            compact=True,
        )
        if key == "fast" and not aria2c_available(engine_module):
            button.state(["disabled"])
        button.pack(side="left", padx=(0, 5))

    window._preset_status_var = tk.StringVar(value="所有高级项默认关闭；快捷方案只修改下面这些默认值。")
    _label(panel, variable=window._preset_status_var, size=7, color=SUBTLE, bg=PANEL_2).pack(anchor="w", pady=(6, 10))

    columns = tk.Frame(panel, bg=PANEL_2)
    columns.pack(fill="x")
    columns.grid_columnconfigure(0, weight=1, uniform="advanced")
    columns.grid_columnconfigure(1, weight=1, uniform="advanced")

    left = tk.Frame(columns, bg=PANEL_2)
    left.grid(row=0, column=0, sticky="new", padx=(0, 10))
    right = tk.Frame(columns, bg=PANEL_2)
    right.grid(row=0, column=1, sticky="new", padx=(10, 0))

    _label(left, "片段与章节", size=8, weight="bold", bg=PANEL_2).pack(anchor="w")
    segment = tk.Frame(left, bg=PANEL_2)
    segment.pack(fill="x", pady=(6, 0))
    _label(segment, "开始", size=7, color=MUTED, bg=PANEL_2).grid(row=0, column=0, sticky="w")
    _entry(segment, window._media_pref_vars["segmentStart"], width=11).grid(row=0, column=1, padx=(6, 12))
    _label(segment, "结束", size=7, color=MUTED, bg=PANEL_2).grid(row=0, column=2, sticky="w")
    _entry(segment, window._media_pref_vars["segmentEnd"], width=11).grid(row=0, column=3, padx=(6, 0))
    _label(left, "例如 01:20 → 03:45；留空表示完整视频。", size=7, color=SUBTLE, bg=PANEL_2).pack(anchor="w", pady=(5, 5))
    _check(left, "按章节拆分", window._media_pref_vars["splitChapters"]).pack(anchor="w")

    _divider(left, bg=PANEL_2).pack(fill="x", pady=(10, 9))
    _label(left, "字幕与音轨", size=8, weight="bold", bg=PANEL_2).pack(anchor="w")
    subtitle = tk.Frame(left, bg=PANEL_2)
    subtitle.pack(fill="x", pady=(6, 0))
    _label(subtitle, "字幕来源", size=7, color=MUTED, bg=PANEL_2).pack(side="left")
    ttk.Combobox(
        subtitle,
        textvariable=window._media_pref_vars["subtitleMode"],
        values=("manual", "auto", "both"),
        width=9,
        state="readonly",
        style="Galaxy.TCombobox",
    ).pack(side="left", padx=(6, 0))
    language = tk.Frame(left, bg=PANEL_2)
    language.pack(fill="x", pady=(7, 0))
    _label(language, "字幕语言", size=7, color=MUTED, bg=PANEL_2).grid(row=0, column=0, sticky="w")
    _entry(language, window._media_pref_vars["subtitleLanguages"], width=22).grid(row=0, column=1, padx=(6, 0), sticky="ew")
    _label(language, "音轨语言", size=7, color=MUTED, bg=PANEL_2).grid(row=1, column=0, sticky="w", pady=(6, 0))
    _entry(language, window._media_pref_vars["audioLanguages"], width=22).grid(row=1, column=1, padx=(6, 0), pady=(6, 0), sticky="ew")

    _label(right, "SponsorBlock", size=8, weight="bold", bg=PANEL_2).pack(anchor="w")
    _label(right, "按分类移除区段，默认全部关闭。", size=7, color=SUBTLE, bg=PANEL_2).pack(anchor="w", pady=(2, 6))
    sponsor_grid = tk.Frame(right, bg=PANEL_2)
    sponsor_grid.pack(fill="x")
    for index, (category, label_text) in enumerate(SPONSOR_LABELS):
        _check(sponsor_grid, label_text, window._media_pref_vars[f"sb:{category}"]).grid(
            row=index // 2,
            column=index % 2,
            sticky="w",
            padx=(0, 10),
            pady=1,
        )

    _divider(right, bg=PANEL_2).pack(fill="x", pady=(10, 9))
    _label(right, "下载器", size=8, weight="bold", bg=PANEL_2).pack(anchor="w")
    aria2 = _check(right, "aria2c 多连接加速（yt-dlp 仍负责解析）", window._media_pref_vars["useAria2c"])
    aria2.pack(anchor="w", pady=(6, 0))
    if not aria2c_available(engine_module):
        aria2.configure(state="disabled", disabledforeground=SUBTLE)
        _label(right, "未检测到 aria2c；安装后重新启动 Engine 即可启用。", size=7, color=SUBTLE, bg=PANEL_2).pack(anchor="w", pady=(3, 0))

    buttons = tk.Frame(panel, bg=PANEL_2)
    buttons.pack(fill="x", pady=(12, 0))
    ActionButton(
        buttons,
        text="恢复默认",
        command=lambda: _reset_media_preferences(window, engine_module),
        kind="ghost",
        compact=True,
    ).pack(side="left")
    ActionButton(
        buttons,
        text="保存默认设置",
        command=lambda: _save_media_preferences(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")


def _entry(master, variable: tk.Variable, width: int) -> tk.Entry:
    return tk.Entry(
        master,
        textvariable=variable,
        width=width,
        font=("Segoe UI", 8),
        bg=BG,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
    )


def _check(master, text: str, variable: tk.BooleanVar) -> tk.Checkbutton:
    return tk.Checkbutton(
        master,
        text=text,
        variable=variable,
        font=("Segoe UI", 8),
        bg=PANEL_2,
        fg=MUTED,
        activebackground=PANEL_2,
        activeforeground=TEXT,
        selectcolor=BG,
        highlightthickness=0,
        bd=0,
        cursor="hand2",
    )


def _toggle_advanced(window) -> None:
    window._advanced_open = not bool(getattr(window, "_advanced_open", False))
    if window._advanced_open:
        window._advanced_panel.pack(fill="x", pady=(8, 0))
        window._advanced_toggle_var.set("高级下载工作台  ⌄")
    else:
        window._advanced_panel.pack_forget()
        window._advanced_toggle_var.set("高级下载工作台  ›")


def _apply_preset(window, engine_module, preset: str) -> None:
    values = window._media_pref_vars
    values["segmentStart"].set("")
    values["segmentEnd"].set("")
    values["splitChapters"].set(False)
    values["subtitleMode"].set("both")
    values["subtitleLanguages"].set("")
    values["audioLanguages"].set("")
    values["useAria2c"].set(False)
    for category, _label_text in SPONSOR_LABELS:
        values[f"sb:{category}"].set(False)

    if preset == "course":
        values["splitChapters"].set(True)
        window._preset_status_var.set("课程/播客：按章节拆分；字幕来源保留人工 + 自动。")
    elif preset == "clean":
        for category in ("sponsor", "selfpromo", "interaction"):
            values[f"sb:{category}"].set(True)
        window._preset_status_var.set("去赞助：移除赞助、自我推广和互动提醒；不会移除片头片尾。")
    elif preset == "fast":
        values["useAria2c"].set(bool(aria2c_available(engine_module)))
        window._preset_status_var.set("高速：启用 aria2c；yt-dlp 继续负责格式选择与调度。")
    else:
        window._preset_status_var.set("标准：恢复完整视频与默认 yt-dlp 行为。")


def _save_media_preferences(window, engine_module) -> None:
    values = window._media_pref_vars
    categories = [
        category
        for category, _label_text in SPONSOR_LABELS
        if bool(values[f"sb:{category}"].get())
    ]
    cleaned = save_preferences(
        engine_module,
        {
            "segmentStart": values["segmentStart"].get(),
            "segmentEnd": values["segmentEnd"].get(),
            "splitChapters": bool(values["splitChapters"].get()),
            "subtitleMode": values["subtitleMode"].get(),
            "subtitleLanguages": values["subtitleLanguages"].get(),
            "audioLanguages": values["audioLanguages"].get(),
            "sponsorBlockCategories": categories,
            "useAria2c": bool(values["useAria2c"].get()),
        },
    )
    for key in ("segmentStart", "segmentEnd", "subtitleMode"):
        values[key].set(str(cleaned.get(key) or ""))
    values["subtitleLanguages"].set(",".join(cleaned.get("subtitleLanguages") or []))
    values["audioLanguages"].set(",".join(cleaned.get("audioLanguages") or []))
    cleaned_categories = set(cleaned.get("sponsorBlockCategories") or [])
    for category, _label_text in SPONSOR_LABELS:
        values[f"sb:{category}"].set(category in cleaned_categories)
    values["useAria2c"].set(bool(cleaned.get("useAria2c", False)))
    window._preset_status_var.set("已保存。新任务在网页没有单独覆盖时会使用这些默认值。")
    window.set_status(
        "Ready" if not window.running else window.status_var.get(),
        "高级下载默认设置已保存。当前运行任务不会被修改。",
    )


def _reset_media_preferences(window, engine_module) -> None:
    _apply_preset(window, engine_module, "standard")
    _save_media_preferences(window, engine_module)
    window._preset_status_var.set("已恢复并保存标准默认设置。")


def _copy_diagnostics(window, engine_module) -> None:
    try:
        queue_length = len(getattr(window, "pending_jobs", []))
        text = "\n".join(
            (
                "Galaxy Local Engine diagnostics",
                f"version={engine_module.VERSION}",
                f"status={window.status_var.get()}",
                f"ffmpeg={'ready' if engine_module.ffmpeg_dir() is not None else 'missing'}",
                f"yt-dlp={'ready' if engine_module.external_ytdlp_path(engine_module.app_dir()) is not None else 'missing'}",
                f"aria2c={'ready' if aria2c_available(engine_module) else 'missing'}",
                f"active={'1' if bool(getattr(window, 'running', False)) else '0'}",
                f"queued={queue_length}",
            )
        )
        window.clipboard_clear()
        window.clipboard_append(text)
        window.update_idletasks()
        window.set_status(window.status_var.get(), "诊断信息已复制到剪贴板。")
    except tk.TclError:
        pass


def _check_update(window, engine_module) -> None:
    button = window._update_button
    button.state(["disabled"])
    window._latest_var.set(f"当前 v{engine_module.VERSION} · 正在检查…")

    def worker() -> None:
        info = check_latest_stable(engine_module.VERSION)

        def finish() -> None:
            button.state(["!disabled"])
            if info.error:
                window._latest_var.set(f"当前 v{engine_module.VERSION} · 检查失败")
                messagebox.showwarning(
                    engine_module.APP_NAME,
                    f"无法检查 GitHub 稳定版更新。\n\n{info.error}",
                    parent=window,
                )
                return
            latest = info.latest_version or "—"
            if not info.update_available:
                window._latest_var.set(f"当前 v{engine_module.VERSION} · 最新 v{latest}")
                messagebox.showinfo(
                    engine_module.APP_NAME,
                    f"当前版本 v{engine_module.VERSION} 已是最新稳定版。",
                    parent=window,
                )
                return
            window._latest_var.set(f"当前 v{engine_module.VERSION} · 可更新 v{latest}")
            approved = messagebox.askyesno(
                engine_module.APP_NAME,
                f"发现稳定版 v{latest}。\n\n是否打开 GitHub Release 页面？\n程序不会自动替换当前 EXE。",
                parent=window,
            )
            if approved:
                webbrowser.open(info.release_url)

        try:
            window.after(0, finish)
        except tk.TclError:
            pass

    threading.Thread(target=worker, name="GalaxyUpdateCheck", daemon=True).start()
