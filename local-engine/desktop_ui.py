from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable
from urllib.parse import urlparse

from media_policy import DEFAULT_PREFERENCES, aria2c_available, load_preferences, save_preferences
from update_check import check_latest_stable

BG = "#0A0F1C"
SURFACE = "#111827"
SURFACE_2 = "#151E31"
SURFACE_3 = "#1A2540"
BORDER = "#26324C"
TEXT = "#F4F7FF"
MUTED = "#8E9AB5"
SUBTLE = "#66738E"
VIOLET = "#8A6CFF"
VIOLET_HOVER = "#9A82FF"
CYAN = "#35D4BC"
DANGER = "#FF647C"
DANGER_HOVER = "#FF7990"
SUCCESS = "#48D597"


class ActionButton(tk.Button):
    """Flat Tk button with ttk-compatible state([...]) used by engine.py."""

    def __init__(
        self,
        master,
        *,
        text: str,
        command: Callable[[], None],
        kind: str = "secondary",
        width: int | None = None,
    ) -> None:
        palette = {
            "primary": (VIOLET, TEXT, VIOLET_HOVER),
            "danger": (DANGER, "#19050A", DANGER_HOVER),
            "secondary": (SURFACE_3, TEXT, "#223152"),
            "ghost": (SURFACE, MUTED, SURFACE_2),
        }
        self._base, foreground, self._hover = palette[kind]
        kwargs: dict[str, Any] = {
            "text": text,
            "command": command,
            "font": ("Segoe UI", 9, "bold"),
            "bg": self._base,
            "fg": foreground,
            "activebackground": self._hover,
            "activeforeground": foreground,
            "disabledforeground": SUBTLE,
            "relief": "flat",
            "bd": 0,
            "highlightthickness": 0,
            "padx": 14,
            "pady": 8,
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


def _label(master, text: str | None = None, *, variable=None, size=9, weight="normal", color=TEXT, bg=SURFACE, **kwargs):
    return tk.Label(
        master,
        text=text,
        textvariable=variable,
        font=("Segoe UI", size, weight),
        bg=bg,
        fg=color,
        **kwargs,
    )


def _section_title(master, title: str, subtitle: str | None = None, *, bg=SURFACE):
    frame = tk.Frame(master, bg=bg)
    _label(frame, title, size=10, weight="bold", bg=bg).pack(anchor="w")
    if subtitle:
        _label(frame, subtitle, size=8, color=MUTED, bg=bg).pack(anchor="w", pady=(2, 0))
    return frame


def _make_window_icon(master: tk.Misc, size: int = 32) -> tk.PhotoImage:
    image = tk.PhotoImage(master=master, width=size, height=size)
    image.put(BG, to=(0, 0, size, size))
    cx = cy = size / 2
    outer = size * 0.36
    inner = size * 0.29
    for y in range(size):
        for x in range(size):
            distance = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
            if inner <= distance <= outer:
                image.put(VIOLET, (x, y))
    shaft_left = int(size * 0.44)
    shaft_right = int(size * 0.56)
    for y in range(int(size * 0.23), int(size * 0.57)):
        image.put(CYAN, to=(shaft_left, y, shaft_right + 1, y + 1))
    tip_y = int(size * 0.72)
    mid = int(size * 0.5)
    for offset in range(int(size * 0.18)):
        y = int(size * 0.5) + offset
        left = max(0, mid - offset)
        right = min(size - 1, mid + offset)
        image.put(CYAN, to=(left, y, right + 1, y + 1))
        if y >= tip_y:
            break
    return image


def _draw_brand_mark(canvas: tk.Canvas) -> None:
    canvas.delete("all")
    canvas.create_oval(8, 8, 52, 52, outline=VIOLET, width=4)
    canvas.create_arc(2, 16, 58, 46, start=198, extent=144, style="arc", outline="#B4A5FF", width=2)
    canvas.create_line(30, 14, 30, 34, fill=CYAN, width=5, capstyle="round")
    canvas.create_line(21, 29, 30, 39, 39, 29, fill=CYAN, width=5, joinstyle="round", capstyle="round")
    canvas.create_oval(46, 15, 51, 20, fill=CYAN, outline="")


def install_desktop_ui(engine_module):
    """Replace the legacy Tk form with a compact dark desktop workbench.

    The patch intentionally keeps engine.py's public widget/variable contracts
    intact (percent_var, cancel_button.state(), etc.) so download behavior stays
    isolated from presentation changes.
    """
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_ui_installed", False):
        return window_cls

    def build_ui(window) -> None:
        window.configure(bg=BG)
        window.geometry("940x690")
        window.minsize(840, 620)
        window.option_add("*Font", "Segoe UI 9")
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
            troughcolor=SURFACE_3,
            background=VIOLET,
            bordercolor=SURFACE_3,
            lightcolor=VIOLET,
            darkcolor=VIOLET,
            thickness=8,
        )

        root = tk.Frame(window, bg=BG, padx=22, pady=18)
        root.pack(fill="both", expand=True)

        # Header: brand and system readiness form one visual sentence instead of
        # the old title + loose subtitle stack.
        header = tk.Frame(root, bg=BG)
        header.pack(fill="x")
        brand = tk.Frame(header, bg=BG)
        brand.pack(side="left", fill="x", expand=True)
        mark = tk.Canvas(brand, width=60, height=60, bg=BG, bd=0, highlightthickness=0)
        mark.pack(side="left", padx=(0, 12))
        _draw_brand_mark(mark)
        brand_text = tk.Frame(brand, bg=BG)
        brand_text.pack(side="left", pady=(6, 0))
        _label(brand_text, "Galaxy Local Engine", size=17, weight="bold", bg=BG).pack(anchor="w")
        _label(
            brand_text,
            f"SparkDownloader local media runtime · v{engine_module.VERSION}",
            size=8,
            color=MUTED,
            bg=BG,
        ).pack(anchor="w", pady=(3, 0))

        readiness = tk.Frame(header, bg=BG)
        readiness.pack(side="right", anchor="n", pady=(7, 0))
        ffmpeg_ready = engine_module.ffmpeg_dir() is not None
        ytdlp_ready = engine_module.external_ytdlp_path(engine_module.app_dir()) is not None
        aria2_ready = aria2c_available(engine_module)
        _status_chip(readiness, "FFmpeg", ffmpeg_ready).pack(side="left", padx=(0, 6))
        _status_chip(readiness, "yt-dlp", ytdlp_ready).pack(side="left", padx=(0, 6))
        _status_chip(readiness, "aria2", aria2_ready, optional=True).pack(side="left")

        content = tk.Frame(root, bg=BG)
        content.pack(fill="both", expand=True, pady=(18, 0))
        content.grid_columnconfigure(0, weight=7, uniform="content")
        content.grid_columnconfigure(1, weight=3, uniform="content")
        content.grid_rowconfigure(0, weight=1)

        main = tk.Frame(content, bg=SURFACE, padx=20, pady=18, highlightthickness=1, highlightbackground=BORDER)
        main.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        side = tk.Frame(content, bg=SURFACE, padx=16, pady=16, highlightthickness=1, highlightbackground=BORDER)
        side.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        status_row = tk.Frame(main, bg=SURFACE)
        status_row.pack(fill="x")
        status_left = tk.Frame(status_row, bg=SURFACE)
        status_left.pack(side="left", fill="x", expand=True)
        _label(status_left, "当前任务", size=8, color=MUTED).pack(anchor="w")
        _label(status_left, variable=window.status_var, size=15, weight="bold").pack(anchor="w", pady=(4, 0))
        window._queue_summary_var = tk.StringVar(value="等待 0 项")
        _label(status_row, variable=window._queue_summary_var, size=8, weight="bold", color=CYAN).pack(side="right", anchor="n", pady=(3, 0))

        detail = _label(
            main,
            variable=window.detail_var,
            size=9,
            color=MUTED,
            justify="left",
            anchor="w",
            wraplength=510,
        )
        detail.pack(fill="x", pady=(8, 14))

        progress_frame = tk.Frame(main, bg=SURFACE)
        progress_frame.pack(fill="x")
        ttk.Progressbar(
            progress_frame,
            variable=window.percent_var,
            maximum=100,
            style="Galaxy.Horizontal.TProgressbar",
        ).pack(fill="x")
        window._percent_text_var = tk.StringVar(value="0%")
        _label(progress_frame, variable=window._percent_text_var, size=8, color=MUTED).pack(anchor="e", pady=(5, 0))

        stats = tk.Frame(main, bg=SURFACE)
        stats.pack(fill="x", pady=(14, 0))
        for index, (title, var) in enumerate(
            (("速度", window.speed_var), ("剩余时间", window.eta_var), ("已下载", window.size_var))
        ):
            stats.grid_columnconfigure(index, weight=1)
            cell = tk.Frame(stats, bg=SURFACE_2, padx=12, pady=10)
            cell.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 5, 5 if index < 2 else 0))
            _label(cell, title, size=8, color=SUBTLE, bg=SURFACE_2).pack(anchor="w")
            _label(cell, variable=var, size=10, weight="bold", bg=SURFACE_2).pack(anchor="w", pady=(3, 0))

        # Advanced settings are progressive disclosure: visible enough to find,
        # collapsed by default so the core current-task flow keeps priority.
        advanced = tk.Frame(main, bg=SURFACE)
        advanced.pack(fill="x", pady=(18, 0))
        window._advanced_open = False
        toggle_row = tk.Frame(advanced, bg=SURFACE)
        toggle_row.pack(fill="x")
        window._advanced_toggle_var = tk.StringVar(value="高级下载默认设置  ›")
        toggle = tk.Button(
            toggle_row,
            textvariable=window._advanced_toggle_var,
            command=lambda: _toggle_advanced(window),
            font=("Segoe UI", 9, "bold"),
            bg=SURFACE,
            fg=TEXT,
            activebackground=SURFACE,
            activeforeground=VIOLET_HOVER,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=0,
            pady=4,
        )
        toggle.pack(side="left")
        _label(toggle_row, "默认关闭的高级能力在这里设置", size=8, color=SUBTLE).pack(side="right")

        window._advanced_panel = tk.Frame(advanced, bg=SURFACE_2, padx=14, pady=12)
        _build_advanced_panel(window, engine_module)

        actions = tk.Frame(main, bg=SURFACE)
        actions.pack(fill="x", side="bottom", pady=(18, 0))
        window.cancel_button = ActionButton(actions, text="取消当前任务", command=window.cancel, kind="danger")
        window.cancel_button.pack(side="left")
        window.cancel_button.state(["disabled"])
        window.folder_button = ActionButton(actions, text="打开下载目录", command=window.open_folder, kind="secondary")
        window.folder_button.pack(side="right")

        # Queue / system side rail.
        queue_header = _section_title(side, "下载队列", "当前任务结束后按顺序自动执行")
        queue_header.pack(fill="x")
        window._queue_count_var = tk.StringVar(value="当前 0 · 等待 0")
        _label(side, variable=window._queue_count_var, size=8, color=CYAN).pack(anchor="w", pady=(9, 10))
        window._queue_panel = tk.Frame(side, bg=SURFACE)
        window._queue_panel.pack(fill="both", expand=True)

        system = tk.Frame(side, bg=SURFACE)
        system.pack(fill="x", side="bottom", pady=(14, 0))
        tk.Frame(system, height=1, bg=BORDER).pack(fill="x", pady=(0, 12))
        _label(system, "版本与更新", size=9, weight="bold").pack(anchor="w")
        window._latest_var = tk.StringVar(value=f"当前 v{engine_module.VERSION} · 未检查")
        _label(system, variable=window._latest_var, size=8, color=MUTED).pack(anchor="w", pady=(4, 9))
        window._update_button = ActionButton(
            system,
            text="检查稳定版更新",
            command=lambda: _check_update(window, engine_module),
            kind="ghost",
        )
        window._update_button.pack(fill="x")
        _label(
            system,
            "只检查版本；更新前会再次确认，不会静默替换 EXE。",
            size=7,
            color=SUBTLE,
            wraplength=235,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

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
            pending = []
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
            _render_queue(window, pending)
        except Exception:
            pass
        try:
            window.after(650, window._galaxy_queue_tick)
        except tk.TclError:
            pass

    window_cls._build_ui = build_ui
    window_cls._galaxy_ui_tick = ui_tick
    window_cls._galaxy_queue_tick = queue_tick
    window_cls._galaxy_desktop_ui_installed = True
    return window_cls


def _status_chip(master, label: str, ready: bool, optional: bool = False) -> tk.Frame:
    frame = tk.Frame(master, bg=SURFACE_2, padx=9, pady=5)
    dot_color = SUCCESS if ready else (SUBTLE if optional else DANGER)
    dot = tk.Canvas(frame, width=8, height=8, bg=SURFACE_2, bd=0, highlightthickness=0)
    dot.create_oval(1, 1, 7, 7, fill=dot_color, outline="")
    dot.pack(side="left", padx=(0, 5))
    _label(frame, label, size=7, weight="bold", color=MUTED, bg=SURFACE_2).pack(side="left")
    return frame


def _render_queue(window, pending: list[Any]) -> None:
    panel = window._queue_panel
    for child in panel.winfo_children():
        child.destroy()
    if not pending:
        empty = tk.Frame(panel, bg=SURFACE_2, padx=12, pady=16)
        empty.pack(fill="x")
        _label(empty, "队列为空", size=9, weight="bold", bg=SURFACE_2).pack(anchor="w")
        _label(empty, "网页忙碌时提交的任务会显示在这里。", size=8, color=MUTED, bg=SURFACE_2, wraplength=220, justify="left").pack(anchor="w", pady=(4, 0))
        return

    for index, queued in enumerate(pending[:8], start=1):
        row = tk.Frame(panel, bg=SURFACE_2, padx=10, pady=9)
        row.pack(fill="x", pady=(0, 6))
        _label(row, f"{index:02d}", size=8, weight="bold", color=VIOLET, bg=SURFACE_2).pack(side="left", padx=(0, 9))
        text = tk.Frame(row, bg=SURFACE_2)
        text.pack(side="left", fill="x", expand=True)
        label = str(getattr(queued, "label", "Queued download") or "Queued download")
        host = str(getattr(queued, "source_host", "") or "")
        _label(text, label[:36], size=8, weight="bold", bg=SURFACE_2).pack(anchor="w")
        if host:
            _label(text, host[:34], size=7, color=SUBTLE, bg=SURFACE_2).pack(anchor="w", pady=(2, 0))
    if len(pending) > 8:
        _label(panel, f"另有 {len(pending) - 8} 项等待", size=8, color=MUTED).pack(anchor="w", padx=3, pady=(1, 0))


def _build_advanced_panel(window, engine_module) -> None:
    panel = window._advanced_panel
    preferences = load_preferences(engine_module)
    window._media_pref_vars = {
        "segmentStart": tk.StringVar(value=str(preferences.get("segmentStart") or "")),
        "segmentEnd": tk.StringVar(value=str(preferences.get("segmentEnd") or "")),
        "splitChapters": tk.BooleanVar(value=bool(preferences.get("splitChapters", False))),
        "subtitleMode": tk.StringVar(value=str(preferences.get("subtitleMode") or "both")),
        "subtitleLanguages": tk.StringVar(value=",".join(preferences.get("subtitleLanguages") or [])),
        "audioLanguages": tk.StringVar(value=",".join(preferences.get("audioLanguages") or [])),
        "sponsor": tk.BooleanVar(value="sponsor" in (preferences.get("sponsorBlockCategories") or [])),
        "selfpromo": tk.BooleanVar(value="selfpromo" in (preferences.get("sponsorBlockCategories") or [])),
        "useAria2c": tk.BooleanVar(value=bool(preferences.get("useAria2c", False))),
    }

    segment = tk.Frame(panel, bg=SURFACE_2)
    segment.pack(fill="x")
    _label(segment, "视频片段", size=8, weight="bold", bg=SURFACE_2).grid(row=0, column=0, sticky="w", columnspan=4)
    _label(segment, "开始", size=7, color=MUTED, bg=SURFACE_2).grid(row=1, column=0, sticky="w", pady=(7, 0))
    start = _entry(segment, window._media_pref_vars["segmentStart"], width=10)
    start.grid(row=1, column=1, sticky="w", padx=(6, 12), pady=(7, 0))
    _label(segment, "结束", size=7, color=MUTED, bg=SURFACE_2).grid(row=1, column=2, sticky="w", pady=(7, 0))
    end = _entry(segment, window._media_pref_vars["segmentEnd"], width=10)
    end.grid(row=1, column=3, sticky="w", padx=(6, 0), pady=(7, 0))
    _label(segment, "格式示例：01:20 → 03:45；留空表示完整视频。", size=7, color=SUBTLE, bg=SURFACE_2).grid(row=2, column=0, columnspan=4, sticky="w", pady=(5, 0))

    row2 = tk.Frame(panel, bg=SURFACE_2)
    row2.pack(fill="x", pady=(11, 0))
    _check(row2, "按章节拆分", window._media_pref_vars["splitChapters"]).pack(side="left")
    _check(row2, "SponsorBlock·赞助", window._media_pref_vars["sponsor"]).pack(side="left", padx=(14, 0))
    _check(row2, "自我推广", window._media_pref_vars["selfpromo"]).pack(side="left", padx=(10, 0))

    row3 = tk.Frame(panel, bg=SURFACE_2)
    row3.pack(fill="x", pady=(10, 0))
    _label(row3, "字幕", size=7, color=MUTED, bg=SURFACE_2).pack(side="left")
    subtitle_mode = ttk.Combobox(
        row3,
        textvariable=window._media_pref_vars["subtitleMode"],
        values=("manual", "auto", "both"),
        width=9,
        state="readonly",
    )
    subtitle_mode.pack(side="left", padx=(6, 12))
    _label(row3, "语言", size=7, color=MUTED, bg=SURFACE_2).pack(side="left")
    _entry(row3, window._media_pref_vars["subtitleLanguages"], width=20).pack(side="left", padx=(6, 0))

    row4 = tk.Frame(panel, bg=SURFACE_2)
    row4.pack(fill="x", pady=(10, 0))
    _label(row4, "多音轨语言", size=7, color=MUTED, bg=SURFACE_2).pack(side="left")
    _entry(row4, window._media_pref_vars["audioLanguages"], width=20).pack(side="left", padx=(6, 12))
    aria2 = _check(row4, "aria2c 加速", window._media_pref_vars["useAria2c"])
    aria2.pack(side="left")
    if not aria2c_available(engine_module):
        aria2.configure(state="disabled", disabledforeground=SUBTLE)

    save = ActionButton(
        panel,
        text="保存高级默认设置",
        command=lambda: _save_media_preferences(window, engine_module),
        kind="secondary",
    )
    save.pack(anchor="e", pady=(12, 0))


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
        highlightcolor=VIOLET,
    )


def _check(master, text: str, variable: tk.BooleanVar) -> tk.Checkbutton:
    return tk.Checkbutton(
        master,
        text=text,
        variable=variable,
        font=("Segoe UI", 8),
        bg=SURFACE_2,
        fg=MUTED,
        activebackground=SURFACE_2,
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
        window._advanced_toggle_var.set("高级下载默认设置  ⌄")
    else:
        window._advanced_panel.pack_forget()
        window._advanced_toggle_var.set("高级下载默认设置  ›")


def _save_media_preferences(window, engine_module) -> None:
    values = window._media_pref_vars
    categories: list[str] = []
    if bool(values["sponsor"].get()):
        categories.append("sponsor")
    if bool(values["selfpromo"].get()):
        categories.append("selfpromo")
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
    window.set_status(
        "Ready" if not window.running else window.status_var.get(),
        "Advanced download defaults saved; new website jobs will use them when no per-job override is supplied.",
    )
    for key in ("segmentStart", "segmentEnd", "subtitleMode"):
        if key in values:
            values[key].set(str(cleaned.get(key) or ""))


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
