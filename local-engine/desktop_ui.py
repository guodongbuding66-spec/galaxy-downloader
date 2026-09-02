from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Any, Callable

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
        # Tk parses a string font descriptor as a Tcl list. A family name that
        # contains spaces must therefore be one list element. `Segoe UI 9`
        # becomes `Segoe`, `UI`, `9` and Tcl tries to parse `UI` as the font
        # size, crashing startup with: expected integer but got "UI".
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

        _build_side_panel(window, side, engine_module)
        _bind_refresh_hooks(window, engine_module)

    window_cls._build_ui = build_ui
    window_cls._galaxy_desktop_ui_installed = True
    return window_cls


def _build_side_panel(window, side: tk.Frame, engine_module) -> None:
    _section_title(side, "本机运行状态", "浏览器只负责下发任务，媒体文件直接保存到本机。")

    status_box = tk.Frame(side, bg=PANEL_2, padx=12, pady=12, highlightthickness=1, highlightbackground=BORDER_SOFT)
    status_box.pack(fill="x", pady=(12, 0))
    chips = tk.Frame(status_box, bg=PANEL_2)
    chips.pack(fill="x")
    yt_ready = bool(engine_module.external_ytdlp_available())
    ff_ready = bool(engine_module.ffmpeg_available())
    _status_chip(chips, "yt-dlp", yt_ready).pack(side="left", padx=(0, 5))
    _status_chip(chips, "FFmpeg", ff_ready).pack(side="left", padx=(0, 5))
    _status_chip(chips, "aria2c", aria2c_available(), optional=True).pack(side="left")

    window._engine_hint_var = tk.StringVar()
    _label(status_box, variable=window._engine_hint_var, size=8, color=MUTED, bg=PANEL_2, justify="left", wraplength=255).pack(
        fill="x", pady=(10, 0)
    )

    folder = tk.Frame(side, bg=PANEL)
    folder.pack(fill="x", pady=(16, 0))
    _label(folder, "下载目录", size=7, color=SUBTLE).pack(anchor="w")
    window._download_dir_var = tk.StringVar(value=str(engine_module.default_download_dir()))
    _label(folder, variable=window._download_dir_var, size=8, weight="bold", justify="left", anchor="w", wraplength=255).pack(
        fill="x", pady=(4, 0)
    )

    _divider(side).pack(fill="x", pady=16)
    _section_title(side, "任务与诊断", "队列、历史、错误分类和运行日志集中在这里。")
    side_actions = tk.Frame(side, bg=PANEL)
    side_actions.pack(fill="x", pady=(11, 0))
    window._queue_manager_button = ActionButton(side_actions, text="队列", command=lambda: _show_queue_manager(window, engine_module), kind="ghost", compact=True)
    window._queue_manager_button.pack(side="left", padx=(0, 6))
    window._history_button = ActionButton(side_actions, text="历史", command=lambda: _show_history(window, engine_module), kind="ghost", compact=True)
    window._history_button.pack(side="left", padx=(0, 6))
    ActionButton(side_actions, text="日志", command=lambda: _show_logs(window, engine_module), kind="ghost", compact=True).pack(side="left")

    window._update_var = tk.StringVar(value="正在检查稳定版…")
    _label(side, variable=window._update_var, size=7, color=SUBTLE, justify="left", wraplength=255).pack(fill="x", pady=(15, 0))
    _refresh_side_status(window, engine_module)
    window.after(700, lambda: _start_update_check(window, engine_module))


def _build_advanced_panel(window, engine_module) -> None:
    panel = window._advanced_panel
    preferences = load_preferences()

    section = tk.Frame(panel, bg=PANEL_2)
    section.pack(fill="x")
    _label(section, "片段与章节", size=9, weight="bold", bg=PANEL_2).pack(anchor="w")

    clip_row = tk.Frame(section, bg=PANEL_2)
    clip_row.pack(fill="x", pady=(9, 0))
    _label(clip_row, "视频片段", size=8, color=MUTED, bg=PANEL_2).grid(row=0, column=0, sticky="w")
    window._clip_start_var = tk.StringVar(value=preferences.clip_start or "")
    window._clip_end_var = tk.StringVar(value=preferences.clip_end or "")
    clip_start = tk.Entry(
        clip_row,
        textvariable=window._clip_start_var,
        width=10,
        font=("Segoe UI", 8),
        bg=BG,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
    )
    clip_start.grid(row=0, column=1, padx=(12, 5))
    _label(clip_row, "—", size=8, color=SUBTLE, bg=PANEL_2).grid(row=0, column=2)
    clip_end = tk.Entry(
        clip_row,
        textvariable=window._clip_end_var,
        width=10,
        font=("Segoe UI", 8),
        bg=BG,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
    )
    clip_end.grid(row=0, column=3, padx=(5, 0))
    _label(clip_row, "例如 01:20 — 03:45；留空代表完整视频。", size=7, color=SUBTLE, bg=PANEL_2).grid(
        row=1, column=0, columnspan=4, sticky="w", pady=(5, 0)
    )

    window._split_chapters_var = tk.BooleanVar(value=preferences.split_chapters)
    tk.Checkbutton(
        section,
        text="按章节拆分文件",
        variable=window._split_chapters_var,
        bg=PANEL_2,
        fg=TEXT,
        activebackground=PANEL_2,
        activeforeground=TEXT,
        selectcolor=BG,
        font=("Segoe UI", 8),
        highlightthickness=0,
        command=lambda: _save_advanced_preferences(window),
    ).pack(anchor="w", pady=(10, 0))

    _divider(panel, bg=PANEL_2).pack(fill="x", pady=13)
    _label(panel, "字幕与音轨", size=9, weight="bold", bg=PANEL_2).pack(anchor="w")

    language_row = tk.Frame(panel, bg=PANEL_2)
    language_row.pack(fill="x", pady=(9, 0))
    window._include_subtitle_var = tk.BooleanVar(value=preferences.include_subtitle)
    tk.Checkbutton(
        language_row,
        text="下载字幕",
        variable=window._include_subtitle_var,
        bg=PANEL_2,
        fg=TEXT,
        activebackground=PANEL_2,
        activeforeground=TEXT,
        selectcolor=BG,
        font=("Segoe UI", 8),
        highlightthickness=0,
        command=lambda: _save_advanced_preferences(window),
    ).pack(side="left")

    window._subtitle_language_var = tk.StringVar(value=preferences.subtitle_language or "zh-Hans")
    window._audio_language_var = tk.StringVar(value=preferences.audio_language or "auto")
    ttk.Combobox(
        language_row,
        textvariable=window._subtitle_language_var,
        values=("zh-Hans", "zh-Hant", "en", "ja", "ko", "auto"),
        width=10,
        state="readonly",
        style="Galaxy.TCombobox",
    ).pack(side="left", padx=(10, 5))
    ttk.Combobox(
        language_row,
        textvariable=window._audio_language_var,
        values=("auto", "zh", "en", "ja", "ko", "original"),
        width=10,
        state="readonly",
        style="Galaxy.TCombobox",
    ).pack(side="left")

    window._include_auto_subtitles_var = tk.BooleanVar(value=preferences.include_auto_subtitles)
    tk.Checkbutton(
        panel,
        text="允许自动字幕（优先使用人工字幕）",
        variable=window._include_auto_subtitles_var,
        bg=PANEL_2,
        fg=MUTED,
        activebackground=PANEL_2,
        activeforeground=TEXT,
        selectcolor=BG,
        font=("Segoe UI", 8),
        highlightthickness=0,
        command=lambda: _save_advanced_preferences(window),
    ).pack(anchor="w", pady=(7, 0))

    _divider(panel, bg=PANEL_2).pack(fill="x", pady=13)
    _label(panel, "SponsorBlock", size=9, weight="bold", bg=PANEL_2).pack(anchor="w")
    sponsor_row = tk.Frame(panel, bg=PANEL_2)
    sponsor_row.pack(fill="x", pady=(8, 0))
    window._sponsor_vars = {}
    enabled = set(preferences.sponsorblock_categories)
    for index, (value, label) in enumerate(SPONSOR_LABELS):
        variable = tk.BooleanVar(value=value in enabled)
        window._sponsor_vars[value] = variable
        tk.Checkbutton(
            sponsor_row,
            text=label,
            variable=variable,
            bg=PANEL_2,
            fg=MUTED,
            activebackground=PANEL_2,
            activeforeground=TEXT,
            selectcolor=BG,
            font=("Segoe UI", 8),
            highlightthickness=0,
            command=lambda: _save_advanced_preferences(window),
        ).grid(row=index // 4, column=index % 4, sticky="w", padx=(0, 10), pady=2)

    _divider(panel, bg=PANEL_2).pack(fill="x", pady=13)
    performance = tk.Frame(panel, bg=PANEL_2)
    performance.pack(fill="x")
    _label(performance, "高速下载", size=9, weight="bold", bg=PANEL_2).pack(anchor="w")
    window._prefer_aria2c_var = tk.BooleanVar(value=preferences.prefer_aria2c)
    tk.Checkbutton(
        performance,
        text="检测到 aria2c 时优先启用",
        variable=window._prefer_aria2c_var,
        bg=PANEL_2,
        fg=MUTED,
        activebackground=PANEL_2,
        activeforeground=TEXT,
        selectcolor=BG,
        font=("Segoe UI", 8),
        highlightthickness=0,
        command=lambda: _save_advanced_preferences(window),
    ).pack(anchor="w", pady=(7, 0))

    for variable in (
        window._clip_start_var,
        window._clip_end_var,
        window._subtitle_language_var,
        window._audio_language_var,
    ):
        variable.trace_add("write", lambda *_args: _save_advanced_preferences(window))


def _toggle_advanced(window) -> None:
    window._advanced_open = not bool(getattr(window, "_advanced_open", False))
    if window._advanced_open:
        window._advanced_panel.pack(fill="x", pady=(10, 0))
        window._advanced_toggle_var.set("高级下载工作台  ⌄")
    else:
        window._advanced_panel.pack_forget()
        window._advanced_toggle_var.set("高级下载工作台  ›")


def _save_advanced_preferences(window) -> None:
    preferences = load_preferences()
    preferences.clip_start = window._clip_start_var.get().strip() or None
    preferences.clip_end = window._clip_end_var.get().strip() or None
    preferences.split_chapters = bool(window._split_chapters_var.get())
    preferences.include_subtitle = bool(window._include_subtitle_var.get())
    preferences.include_auto_subtitles = bool(window._include_auto_subtitles_var.get())
    preferences.subtitle_language = window._subtitle_language_var.get().strip() or None
    preferences.audio_language = window._audio_language_var.get().strip() or None
    preferences.sponsorblock_categories = tuple(
        key for key, variable in window._sponsor_vars.items() if bool(variable.get())
    )
    preferences.prefer_aria2c = bool(window._prefer_aria2c_var.get())
    save_preferences(preferences)


def _refresh_side_status(window, engine_module) -> None:
    yt_ready = bool(engine_module.external_ytdlp_available())
    ff_ready = bool(engine_module.ffmpeg_available())
    aria_ready = aria2c_available()
    if yt_ready and ff_ready:
        hint = "本机引擎已就绪。网页可直接提交视频、音频、合集与图文任务。"
    else:
        missing = []
        if not yt_ready:
            missing.append("yt-dlp.exe")
        if not ff_ready:
            missing.append("FFmpeg")
        hint = "缺少 " + "、".join(missing) + "；部分下载能力不可用。"
    if aria_ready:
        hint += " aria2c 已可用。"
    window._engine_hint_var.set(hint)
    window._download_dir_var.set(str(engine_module.default_download_dir()))
    if getattr(window, "running", False):
        percent = float(window.percent_var.get())
        window._percent_text_var.set(f"{percent:.0f}%")
    else:
        window._percent_text_var.set("0%")


def _bind_refresh_hooks(window, engine_module) -> None:
    original_set_status = window.set_status

    def set_status(title: str, detail: str) -> None:
        original_set_status(title, detail)
        try:
            _refresh_side_status(window, engine_module)
        except tk.TclError:
            pass

    window.set_status = set_status
    window.after(900, lambda: _periodic_refresh(window, engine_module))


def _periodic_refresh(window, engine_module) -> None:
    if not window.winfo_exists():
        return
    try:
        _refresh_side_status(window, engine_module)
    except tk.TclError:
        return
    window.after(900, lambda: _periodic_refresh(window, engine_module))


def _start_update_check(window, engine_module) -> None:
    def worker() -> None:
        result = check_latest_stable(engine_module.VERSION)
        text = result.message
        try:
            window.after(0, lambda: window._update_var.set(text))
        except tk.TclError:
            pass

    threading.Thread(target=worker, name="galaxy-update-check", daemon=True).start()


def _copy_diagnostics(window, engine_module) -> None:
    payload = engine_module.build_diagnostics_payload(window)
    import json

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    window.clipboard_clear()
    window.clipboard_append(text)
    window._copy_diag_button.configure(text="已复制")
    window.after(1200, lambda: window._copy_diag_button.configure(text="复制诊断信息"))


def _show_queue_manager(window, engine_module) -> None:
    callback = getattr(engine_module, "show_queue_manager", None)
    if callable(callback):
        callback(window)
    else:
        messagebox.showinfo("任务队列", "队列管理器将在当前窗口中打开。")


def _show_history(window, engine_module) -> None:
    callback = getattr(engine_module, "show_download_history", None)
    if callable(callback):
        callback(window)
    else:
        messagebox.showinfo("下载历史", "历史记录将在当前窗口中打开。")


def _show_logs(window, engine_module) -> None:
    callback = getattr(engine_module, "show_diagnostics_log", None)
    if callable(callback):
        callback(window)
    else:
        messagebox.showinfo("诊断日志", "诊断中心将在当前窗口中打开。")
