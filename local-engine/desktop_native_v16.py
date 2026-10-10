from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from desktop_design_tokens import ACCENT, BG, LAYOUT, TYPE
from desktop_hooks import run_after_build_ui_hooks
from media_policy import aria2c_available

NATIVE_UI_REVISION = "1.6.1"
ui = None


def _label(master, text=None, *, variable=None, size="body", weight="normal", color=None, bg=None, **kwargs):
    return ui._label(
        master,
        text,
        variable=variable,
        size=size,
        weight=weight,
        color=color or ui.TEXT,
        bg=bg or ui.PANEL,
        **kwargs,
    )


def _hairline(master, *, bg=None):
    return tk.Frame(master, height=1, bg=bg or ui.BORDER_SOFT)


def _brand_mark(canvas: tk.Canvas) -> None:
    """Draw the same quiet G/download mark used by the packaged Windows icon."""
    canvas.delete("all")
    canvas.create_arc(5, 5, 39, 39, start=42, extent=278, style="arc", outline="#F1F2F4", width=4)
    canvas.create_line(26, 23, 39, 23, fill="#F1F2F4", width=4, capstyle="round")
    canvas.create_line(31, 12, 31, 29, fill=ui.ACCENT, width=4, capstyle="round")
    canvas.create_line(25, 24, 31, 30, 37, 24, fill=ui.ACCENT, width=4, joinstyle="round", capstyle="round")
    canvas.create_line(24, 35, 38, 35, fill=ui.ACCENT, width=3, capstyle="round")


def _make_titlebar_icon(master: tk.Misc, size: int = 32) -> tk.PhotoImage:
    image = tk.PhotoImage(master=master, width=size, height=size)
    image.put(ui.BG, to=(0, 0, size, size))
    white = ui.TEXT
    blue = ui.ACCENT
    cx = cy = size / 2
    outer = size * 0.39
    inner = size * 0.29
    import math

    for y in range(size):
        for x in range(size):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            distance = (dx * dx + dy * dy) ** 0.5
            angle = math.degrees(math.atan2(dy, dx)) % 360
            if inner <= distance <= outer and not (315 <= angle or angle <= 38):
                image.put(white, (x, y))
    bar_y = int(size * 0.50)
    image.put(white, to=(int(size * 0.53), bar_y, int(size * 0.84), bar_y + max(2, size // 11)))
    shaft_x0, shaft_x1 = int(size * 0.64), int(size * 0.75)
    image.put(blue, to=(shaft_x0, int(size * 0.24), shaft_x1, int(size * 0.65)))
    mid = int(size * 0.695)
    for offset in range(max(2, int(size * 0.15))):
        y = int(size * 0.55) + offset
        image.put(blue, to=(mid - offset, y, mid + offset + 1, y + 1))
    image.put(blue, to=(int(size * 0.54), int(size * 0.78), int(size * 0.85), int(size * 0.86)))
    return image


def _metric_row(master, title: str, variable: tk.Variable, *, first: bool = False) -> tk.Frame:
    cell = tk.Frame(master, bg=ui.PANEL, padx=0 if first else LAYOUT["section"], pady=LAYOUT["inline"])
    if not first:
        tk.Frame(cell, width=1, bg=ui.BORDER_SOFT).pack(side="left", fill="y", padx=(0, LAYOUT["section"]))
    copy = tk.Frame(cell, bg=ui.PANEL)
    copy.pack(side="left", fill="both", expand=True)
    _label(copy, title, size="body_sm", color=ui.SUBTLE).pack(anchor="w")
    _label(copy, variable=variable, size="title_sm", weight="bold").pack(anchor="w", pady=(2, 0))
    return cell


def _status_item(master, label: str, ready: bool, *, optional: bool = False) -> tk.Frame:
    row = tk.Frame(master, bg=ui.PANEL)
    dot = tk.Canvas(row, width=10, height=10, bg=ui.PANEL, bd=0, highlightthickness=0)
    color = ui.SUCCESS if ready else (ui.SUBTLE if optional else ui.DANGER)
    dot.create_oval(2, 2, 8, 8, fill=color, outline="")
    dot.pack(side="left")
    _label(row, label, size="body_sm", color=ui.MUTED).pack(side="left", padx=(7, 0))
    return row


def _configure_native_styles(window) -> None:
    style = ttk.Style(window)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Galaxy.Horizontal.TProgressbar",
        troughcolor=ui.PANEL_3,
        background=ui.ACCENT,
        bordercolor=ui.PANEL_3,
        lightcolor=ui.ACCENT,
        darkcolor=ui.ACCENT,
        thickness=8,
    )
    style.configure(
        "Galaxy.TCombobox",
        fieldbackground=ui.PANEL_3,
        background=ui.PANEL_3,
        foreground=ui.TEXT,
        arrowcolor=ui.MUTED,
        bordercolor=ui.BORDER,
        lightcolor=ui.BORDER,
        darkcolor=ui.BORDER,
        padding=(8, 7),
    )
    style.map(
        "Galaxy.TCombobox",
        fieldbackground=[("readonly", ui.PANEL_3)],
        foreground=[("readonly", ui.TEXT)],
        selectbackground=[("readonly", ui.PANEL_3)],
        selectforeground=[("readonly", ui.TEXT)],
    )


def install_native_desktop_v16(engine_module, ui_module):
    """Make the executable itself the V1.6 workbench; HTML stays an optional surface."""
    global ui
    ui = ui_module
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_native_v16_installed", False):
        return window_cls
    if not getattr(window_cls, "_galaxy_desktop_ui_installed", False):
        raise RuntimeError("install_native_desktop_v16 requires install_desktop_ui first")

    def build_ui(window) -> None:
        window.configure(bg=ui.BG)
        window.geometry("1220x820")
        window.minsize(1040, 720)
        window.option_add("*Font", "{Segoe UI} 10")
        try:
            window.tk.call("tk", "scaling", 1.0)
        except tk.TclError:
            pass

        _configure_native_styles(window)
        icon = _make_titlebar_icon(window, 32)
        window._galaxy_icon = icon
        try:
            window.iconphoto(True, icon)
        except tk.TclError:
            pass

        shell = tk.Frame(window, bg=ui.BG)
        shell.pack(fill="both", expand=True)

        header = tk.Frame(shell, bg=ui.BG, padx=LAYOUT["page"], pady=LAYOUT["section"])
        header.pack(fill="x")
        identity = tk.Frame(header, bg=ui.BG)
        identity.pack(side="left", fill="x", expand=True)
        mark = tk.Canvas(identity, width=44, height=44, bg=ui.BG, bd=0, highlightthickness=0)
        mark.pack(side="left", padx=(0, LAYOUT["content"]))
        _brand_mark(mark)
        copy = tk.Frame(identity, bg=ui.BG)
        copy.pack(side="left", anchor="w")
        _label(copy, "Galaxy Local Engine", size="brand", weight="bold", bg=ui.BG).pack(anchor="w")
        _label(
            copy,
            f"本机下载工作台 · Engine v{engine_module.VERSION} · UI {NATIVE_UI_REVISION}",
            size="body_sm",
            color=ui.MUTED,
            bg=ui.BG,
        ).pack(anchor="w", pady=(2, 0))

        header_actions = tk.Frame(header, bg=ui.BG)
        header_actions.pack(side="right", anchor="center")
        ui.ActionButton(
            header_actions,
            text="打开 SparkDownloader",
            command=lambda: webbrowser.open(ui.WEBSITE_URL),
            kind="ghost",
            compact=True,
        ).pack(side="left", padx=(0, LAYOUT["inline"]))
        window._copy_diag_button = ui.ActionButton(
            header_actions,
            text="复制诊断",
            command=lambda: ui._copy_diagnostics(window, engine_module),
            kind="ghost",
            compact=True,
        )
        window._copy_diag_button.pack(side="left")

        _hairline(shell).pack(fill="x")

        body = tk.Frame(shell, bg=ui.BG, padx=LAYOUT["page"], pady=LAYOUT["section"])
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=76, uniform="workbench")
        body.grid_columnconfigure(1, weight=24, uniform="workbench")
        body.grid_rowconfigure(0, weight=1)

        main = tk.Frame(
            body,
            bg=ui.PANEL,
            padx=LAYOUT["panel"],
            pady=LAYOUT["panel"],
            highlightthickness=1,
            highlightbackground=ui.BORDER,
        )
        main.grid(row=0, column=0, sticky="nsew", padx=(0, LAYOUT["content"]))
        rail = tk.Frame(
            body,
            bg=ui.PANEL,
            padx=LAYOUT["section"],
            pady=LAYOUT["section"],
            highlightthickness=1,
            highlightbackground=ui.BORDER,
        )
        rail.grid(row=0, column=1, sticky="nsew")

        current = tk.Frame(main, bg=ui.PANEL)
        current.pack(fill="x")
        current_head = tk.Frame(current, bg=ui.PANEL)
        current_head.pack(fill="x")
        _label(current_head, "当前任务", size="title_sm", weight="bold").pack(side="left")
        window._queue_summary_var = tk.StringVar(value="等待 0 项")
        _label(current_head, variable=window._queue_summary_var, size="body_sm", color=ui.MUTED).pack(side="right")

        _label(current, variable=window.status_var, size="title", weight="bold").pack(
            anchor="w", pady=(LAYOUT["content"], 0)
        )
        _label(
            current,
            variable=window.detail_var,
            size="body",
            color=ui.MUTED,
            justify="left",
            anchor="w",
            wraplength=760,
        ).pack(fill="x", pady=(LAYOUT["micro"], LAYOUT["content"]))

        progress = tk.Frame(current, bg=ui.PANEL)
        progress.pack(fill="x")
        ttk.Progressbar(
            progress,
            variable=window.percent_var,
            maximum=100,
            style="Galaxy.Horizontal.TProgressbar",
        ).pack(fill="x")
        window._percent_text_var = tk.StringVar(value="0%")
        _label(progress, variable=window._percent_text_var, size="body_sm", weight="bold", color=ui.MUTED).pack(
            anchor="e", pady=(LAYOUT["micro"], 0)
        )

        metrics = tk.Frame(current, bg=ui.PANEL)
        metrics.pack(fill="x", pady=(LAYOUT["content"], 0))
        for index, (title, variable) in enumerate(
            (("速度", window.speed_var), ("剩余时间", window.eta_var), ("已下载", window.size_var))
        ):
            metrics.grid_columnconfigure(index, weight=1)
            _metric_row(metrics, title, variable, first=index == 0).grid(row=0, column=index, sticky="nsew")

        _hairline(main).pack(fill="x", pady=(LAYOUT["section"], LAYOUT["content"]))

        advanced = tk.Frame(main, bg=ui.PANEL)
        advanced.pack(fill="x")
        window._advanced_open = False
        toggle_row = tk.Frame(advanced, bg=ui.PANEL)
        toggle_row.pack(fill="x")
        window._advanced_toggle_var = tk.StringVar(value="高级下载设置  ›")
        toggle = tk.Button(
            toggle_row,
            textvariable=window._advanced_toggle_var,
            command=lambda: ui._toggle_advanced(window),
            font=(str(TYPE["family"]), int(TYPE["body"]), "bold"),
            bg=ui.PANEL,
            fg=ui.TEXT,
            activebackground=ui.PANEL,
            activeforeground=ui.ACCENT_HOVER,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=0,
            pady=LAYOUT["micro"],
        )
        toggle.pack(side="left")
        window._advanced_summary_var = tk.StringVar(value="片段 · 章节 · 字幕/音轨 · SponsorBlock · aria2c")
        _label(toggle_row, variable=window._advanced_summary_var, size="body_sm", color=ui.SUBTLE).pack(side="right")
        window._advanced_panel = tk.Frame(
            advanced,
            bg=ui.PANEL_2,
            padx=LAYOUT["content"],
            pady=LAYOUT["content"],
            highlightthickness=1,
            highlightbackground=ui.BORDER_SOFT,
        )
        ui._build_advanced_panel(window, engine_module)

        actions = tk.Frame(main, bg=ui.PANEL)
        actions.pack(fill="x", side="bottom", pady=(LAYOUT["section"], 0))
        window.cancel_button = ui.ActionButton(actions, text="取消当前任务", command=window.cancel, kind="danger")
        window.cancel_button.pack(side="left")
        window.cancel_button.state(["disabled"])
        window.folder_button = ui.ActionButton(actions, text="打开下载目录", command=window.open_folder, kind="secondary")
        window.folder_button.pack(side="right")

        queue_head = tk.Frame(rail, bg=ui.PANEL)
        queue_head.pack(fill="x")
        queue_copy = tk.Frame(queue_head, bg=ui.PANEL)
        queue_copy.pack(side="left", fill="x", expand=True)
        _label(queue_copy, "下载队列", size="title_sm", weight="bold").pack(anchor="w")
        window._queue_count_var = tk.StringVar(value="当前 0 · 等待 0")
        _label(queue_copy, variable=window._queue_count_var, size="body_sm", color=ui.MUTED).pack(anchor="w", pady=(2, 0))
        window._queue_clear_button = ui.ActionButton(
            queue_head,
            text="清空",
            command=lambda: ui._clear_queue_from_ui(window),
            kind="ghost",
            compact=True,
        )
        window._queue_clear_button.pack(side="right", anchor="n")
        window._queue_clear_button.state(["disabled"])

        window._queue_panel = tk.Frame(rail, bg=ui.PANEL)
        window._queue_panel.pack(fill="both", expand=True, pady=(LAYOUT["content"], 0))

        runtime_box = tk.Frame(rail, bg=ui.PANEL)
        runtime_box.pack(fill="x", side="bottom", pady=(LAYOUT["section"], 0))
        _hairline(runtime_box).pack(fill="x", pady=(0, LAYOUT["content"]))
        _label(runtime_box, "本机组件", size="title_sm", weight="bold").pack(anchor="w")
        component_rows = tk.Frame(runtime_box, bg=ui.PANEL)
        component_rows.pack(fill="x", pady=(LAYOUT["inline"], LAYOUT["content"]))
        ffmpeg_ready = engine_module.ffmpeg_dir() is not None
        ytdlp_ready = engine_module.external_ytdlp_path(engine_module.app_dir()) is not None
        aria2_ready = aria2c_available(engine_module)
        _status_item(component_rows, "FFmpeg", ffmpeg_ready).pack(anchor="w", pady=(0, 5))
        _status_item(component_rows, "yt-dlp", ytdlp_ready).pack(anchor="w", pady=(0, 5))
        _status_item(component_rows, "aria2（可选）", aria2_ready, optional=True).pack(anchor="w")

        _label(runtime_box, "版本", size="body_sm", weight="bold", color=ui.MUTED).pack(anchor="w")
        window._latest_var = tk.StringVar(value=f"Engine v{engine_module.VERSION} · UI {NATIVE_UI_REVISION}")
        _label(runtime_box, variable=window._latest_var, size="body_sm", color=ui.SUBTLE).pack(
            anchor="w", pady=(2, LAYOUT["inline"])
        )
        window._update_button = ui.ActionButton(
            runtime_box,
            text="检查稳定版更新",
            command=lambda: ui._check_update(window, engine_module),
            kind="ghost",
            compact=True,
        )
        window._update_button.pack(fill="x")

        run_after_build_ui_hooks(window)
        window._galaxy_ui_tick()
        window._galaxy_queue_tick()

    window_cls._build_ui = build_ui
    window_cls._galaxy_native_v16_installed = True
    return window_cls


def run_native_desktop_v16_self_test() -> None:
    assert NATIVE_UI_REVISION == "1.6.1"
    assert TYPE["body"] >= 10
    assert ACCENT == "#6F8FFF"
    assert BG == "#121315"
    assert callable(install_native_desktop_v16)


if __name__ == "__main__":
    run_native_desktop_v16_self_test()
    print("Native desktop V1.6 self-test passed")
