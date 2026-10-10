from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from desktop_design_tokens import LAYOUT, TYPE, font
from desktop_hooks import run_after_build_ui_hooks
from media_policy import aria2c_available

NATIVE_UI_REVISION = "1.7.0"
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
    canvas.delete("all")
    canvas.create_arc(6, 6, 42, 42, start=42, extent=278, style="arc", outline=ui.TEXT, width=4)
    canvas.create_line(28, 24, 42, 24, fill=ui.TEXT, width=4, capstyle="round")
    canvas.create_line(33, 12, 33, 31, fill=ui.ACCENT, width=4, capstyle="round")
    canvas.create_line(27, 25, 33, 31, 39, 25, fill=ui.ACCENT, width=4, joinstyle="round", capstyle="round")
    canvas.create_line(26, 37, 41, 37, fill=ui.ACCENT, width=3, capstyle="round")


def _make_titlebar_icon(master: tk.Misc, size: int = 32) -> tk.PhotoImage:
    image = tk.PhotoImage(master=master, width=size, height=size)
    image.put(ui.BG, to=(0, 0, size, size))
    white = ui.TEXT
    blue = ui.ACCENT
    import math

    cx = cy = size / 2
    outer = size * 0.39
    inner = size * 0.29
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


def _configure_styles(window) -> None:
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
        thickness=9,
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
        padding=(10, 9),
        font=font("body_sm"),
    )
    style.map(
        "Galaxy.TCombobox",
        fieldbackground=[("readonly", ui.PANEL_3), ("disabled", ui.PANEL_2)],
        foreground=[("readonly", ui.TEXT), ("disabled", ui.SUBTLE)],
        selectbackground=[("readonly", ui.PANEL_3)],
        selectforeground=[("readonly", ui.TEXT)],
        bordercolor=[("focus", ui.FOCUS)],
    )


def _status_item(master, label: str, ready: bool, *, optional: bool = False) -> tk.Frame:
    row = tk.Frame(master, bg=ui.PANEL, pady=3)
    dot = tk.Canvas(row, width=12, height=12, bg=ui.PANEL, bd=0, highlightthickness=0)
    color = ui.SUCCESS if ready else (ui.SUBTLE if optional else ui.DANGER)
    dot.create_oval(2, 2, 10, 10, fill=color, outline="")
    dot.pack(side="left")
    _label(row, label, size="body_sm", color=ui.MUTED).pack(side="left", padx=(8, 0))
    return row


def _metric(master, title: str, variable: tk.Variable) -> tk.Frame:
    cell = tk.Frame(master, bg=ui.PANEL_2, padx=14, pady=10, highlightthickness=1, highlightbackground=ui.BORDER_SOFT)
    _label(cell, title, size="caption", color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w")
    _label(cell, variable=variable, size="title_sm", weight="bold", bg=ui.PANEL_2).pack(anchor="w", pady=(3, 0))
    return cell


def _build_quick_panel_v17(window, engine_module) -> None:
    # Import lazily so this module can replace the existing hook without
    # creating an import cycle during desktop_ui installation.
    import desktop_quick_download as quick

    main = window.cancel_button.master.master
    first_child = main.winfo_children()[0] if main.winfo_children() else None
    panel = tk.Frame(
        main,
        bg=ui.PANEL_2,
        padx=18,
        pady=16,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    if first_child is not None:
        panel.pack(fill="x", before=first_child, pady=(0, 18))
    else:
        panel.pack(fill="x", pady=(0, 18))
    window._quick_download_panel = panel

    head = tk.Frame(panel, bg=ui.PANEL_2)
    head.pack(fill="x")
    title_block = tk.Frame(head, bg=ui.PANEL_2)
    title_block.pack(side="left", fill="x", expand=True)
    _label(title_block, "快速下载", size="title_sm", weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    _label(
        title_block,
        "粘贴网页链接，本机解析真实图片、视频和音频资源",
        size="body_sm",
        color=ui.MUTED,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(3, 0))
    badge = tk.Label(
        head,
        text="LOCAL",
        font=font("caption", bold=True),
        bg=ui.PANEL_3,
        fg=ui.ACCENT_HOVER,
        padx=9,
        pady=5,
    )
    badge.pack(side="right", anchor="n")

    url_row = tk.Frame(panel, bg=ui.PANEL_2)
    url_row.pack(fill="x", pady=(14, 0))
    url_row.grid_columnconfigure(0, weight=1)
    window._quick_url_var = tk.StringVar()
    entry = tk.Entry(
        url_row,
        textvariable=window._quick_url_var,
        font=font("body"),
        bg=ui.PANEL_3,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        selectbackground=ui.ACCENT,
        selectforeground="#FFFFFF",
        relief="flat",
        bd=0,
        highlightthickness=2,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.FOCUS,
    )
    entry.grid(row=0, column=0, sticky="ew", ipady=11)
    window._quick_url_entry = entry
    ui.ActionButton(url_row, text="粘贴", command=lambda: quick._paste_quick_url(window), kind="secondary").grid(row=0, column=1, padx=(10, 0))
    window._quick_parse_button = ui.ActionButton(
        url_row,
        text="解析并预览",
        command=lambda: quick._parse_quick_url(window, engine_module),
        kind="primary",
    )
    window._quick_parse_button.grid(row=0, column=2, padx=(10, 0))
    entry.bind("<Return>", lambda _event: quick._parse_quick_url(window, engine_module))

    controls = tk.Frame(panel, bg=ui.PANEL_2)
    controls.pack(fill="x", pady=(12, 0))
    left = tk.Frame(controls, bg=ui.PANEL_2)
    left.pack(side="left")
    _label(left, "登录环境", size="caption", color=ui.SUBTLE, bg=ui.PANEL_2).pack(side="left")
    window._quick_browser_var = tk.StringVar(value=quick._BROWSER_BY_KEY["none"])
    ttk.Combobox(
        left,
        textvariable=window._quick_browser_var,
        values=tuple(quick._BROWSER_LABELS),
        state="readonly",
        width=18,
        style="Galaxy.TCombobox",
    ).pack(side="left", padx=(8, 16))
    _label(left, "下载 Profile", size="caption", color=ui.SUBTLE, bg=ui.PANEL_2).pack(side="left")
    window._quick_profile_var = tk.StringVar(value=quick._AUTO_PROFILE_LABEL)
    window._quick_profile_ids = {quick._AUTO_PROFILE_LABEL: ""}
    window._quick_profile_combo = ttk.Combobox(
        left,
        textvariable=window._quick_profile_var,
        values=(quick._AUTO_PROFILE_LABEL,),
        state="readonly",
        width=19,
        style="Galaxy.TCombobox",
    )
    window._quick_profile_combo.pack(side="left", padx=(8, 8))
    ui.ActionButton(
        left,
        text="刷新",
        command=lambda: quick._refresh_quick_profiles(window, engine_module),
        kind="ghost",
        compact=True,
    ).pack(side="left")

    window._quick_state_var = tk.StringVar(value="等待链接 · 不会在后台读取剪贴板或自动联网")
    _label(
        panel,
        variable=window._quick_state_var,
        size="body_sm",
        color=ui.CYAN,
        bg=ui.PANEL_2,
        wraplength=820,
        justify="left",
    ).pack(anchor="w", pady=(11, 0))

    preview_panel = tk.Frame(panel, bg=ui.PANEL_3, padx=15, pady=13, highlightthickness=1, highlightbackground=ui.BORDER)
    window._quick_preview_panel = preview_panel
    window._quick_title_var = tk.StringVar()
    window._quick_meta_var = tk.StringVar()
    _label(preview_panel, variable=window._quick_title_var, size="title_sm", weight="bold", bg=ui.PANEL_3, wraplength=760, justify="left").pack(anchor="w")
    _label(preview_panel, variable=window._quick_meta_var, size="body_sm", color=ui.MUTED, bg=ui.PANEL_3).pack(anchor="w", pady=(4, 10))

    format_row = tk.Frame(preview_panel, bg=ui.PANEL_3)
    format_row.pack(fill="x")
    format_row.grid_columnconfigure(1, weight=1)
    format_row.grid_columnconfigure(3, weight=1)
    _label(format_row, "视频", size="caption", color=ui.SUBTLE, bg=ui.PANEL_3).grid(row=0, column=0, sticky="w")
    window._quick_video_var = tk.StringVar()
    window._quick_video_combo = ttk.Combobox(format_row, textvariable=window._quick_video_var, state="disabled", style="Galaxy.TCombobox")
    window._quick_video_combo.grid(row=0, column=1, sticky="ew", padx=(8, 16))
    _label(format_row, "音频", size="caption", color=ui.SUBTLE, bg=ui.PANEL_3).grid(row=0, column=2, sticky="w")
    window._quick_audio_var = tk.StringVar()
    window._quick_audio_combo = ttk.Combobox(format_row, textvariable=window._quick_audio_var, state="disabled", style="Galaxy.TCombobox")
    window._quick_audio_combo.grid(row=0, column=3, sticky="ew", padx=(8, 0))

    footer = tk.Frame(preview_panel, bg=ui.PANEL_3)
    footer.pack(fill="x", pady=(12, 0))
    _label(
        footer,
        "优先真实 format_id；商品图会尝试原尺寸 CDN 变体并自动回退。",
        size="caption",
        color=ui.SUBTLE,
        bg=ui.PANEL_3,
    ).pack(side="left")
    window._quick_download_button = ui.ActionButton(
        footer,
        text="下载所选内容",
        command=lambda: quick._submit_quick_download(window, engine_module),
        kind="primary",
    )
    window._quick_download_button.pack(side="right")
    window._quick_download_button.state(["disabled"])

    window._quick_preview = None
    window._quick_video_display = {}
    window._quick_audio_display = {}
    window._quick_parse_generation = 0
    quick._refresh_quick_profiles(window, engine_module)


def install_native_desktop_v17(engine_module, ui_module):
    global ui
    ui = ui_module
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_native_v17_installed", False):
        return window_cls
    if not getattr(window_cls, "_galaxy_desktop_ui_installed", False):
        raise RuntimeError("install_native_desktop_v17 requires install_desktop_ui first")

    # Quick Download registers its hook later, but its lambda resolves this
    # global at execution time, so replacing the builder here updates the true
    # native EXE surface without changing download business logic.
    import desktop_quick_download as quick
    quick._build_quick_panel = _build_quick_panel_v17

    def build_ui(window) -> None:
        window.configure(bg=ui.BG)
        window.geometry("1320x880")
        window.minsize(1100, 760)
        window.option_add("*Font", "{Segoe UI} 11")
        try:
            window.tk.call("tk", "scaling", 1.0)
        except tk.TclError:
            pass

        _configure_styles(window)
        icon = _make_titlebar_icon(window, 32)
        window._galaxy_icon = icon
        try:
            window.iconphoto(True, icon)
        except tk.TclError:
            pass

        shell = tk.Frame(window, bg=ui.BG)
        shell.pack(fill="both", expand=True)

        header = tk.Frame(shell, bg=ui.BG, padx=28, pady=18)
        header.pack(fill="x")
        identity = tk.Frame(header, bg=ui.BG)
        identity.pack(side="left", fill="x", expand=True)
        mark = tk.Canvas(identity, width=48, height=48, bg=ui.BG, bd=0, highlightthickness=0)
        mark.pack(side="left", padx=(0, 14))
        _brand_mark(mark)
        copy = tk.Frame(identity, bg=ui.BG)
        copy.pack(side="left", anchor="w")
        _label(copy, "Galaxy Local Engine", size="brand", weight="bold", bg=ui.BG).pack(anchor="w")
        _label(
            copy,
            f"本机媒体工作台  ·  Engine {engine_module.VERSION}  ·  UI {NATIVE_UI_REVISION}",
            size="body_sm",
            color=ui.MUTED,
            bg=ui.BG,
        ).pack(anchor="w", pady=(3, 0))

        header_actions = tk.Frame(header, bg=ui.BG)
        header_actions.pack(side="right", anchor="center")
        ui.ActionButton(
            header_actions,
            text="打开 SparkDownloader",
            command=lambda: webbrowser.open(ui.WEBSITE_URL),
            kind="secondary",
            compact=True,
        ).pack(side="left", padx=(0, 8))
        window._copy_diag_button = ui.ActionButton(
            header_actions,
            text="复制诊断",
            command=lambda: ui._copy_diagnostics(window, engine_module),
            kind="ghost",
            compact=True,
        )
        window._copy_diag_button.pack(side="left")

        body = tk.Frame(shell, bg=ui.BG, padx=28, pady=(0, 26))
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=72, uniform="workbench")
        body.grid_columnconfigure(1, weight=28, uniform="workbench")
        body.grid_rowconfigure(0, weight=1)

        main = tk.Frame(body, bg=ui.PANEL, padx=20, pady=20, highlightthickness=1, highlightbackground=ui.BORDER)
        main.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        rail = tk.Frame(body, bg=ui.PANEL, padx=18, pady=18, highlightthickness=1, highlightbackground=ui.BORDER)
        rail.grid(row=0, column=1, sticky="nsew")

        section_head = tk.Frame(main, bg=ui.PANEL)
        section_head.pack(fill="x")
        _label(section_head, "下载工作区", size="title", weight="bold").pack(side="left")
        _label(section_head, "解析、选择、排队、恢复都在本机完成", size="body_sm", color=ui.MUTED).pack(side="right", anchor="s")

        current = tk.Frame(main, bg=ui.PANEL)
        current.pack(fill="x", pady=(18, 0))
        current_head = tk.Frame(current, bg=ui.PANEL)
        current_head.pack(fill="x")
        _label(current_head, "当前任务", size="title_sm", weight="bold").pack(side="left")
        window._queue_summary_var = tk.StringVar(value="等待 0 项")
        _label(current_head, variable=window._queue_summary_var, size="body_sm", color=ui.MUTED).pack(side="right")
        _label(current, variable=window.status_var, size="title", weight="bold").pack(anchor="w", pady=(12, 0))
        _label(
            current,
            variable=window.detail_var,
            size="body",
            color=ui.MUTED,
            justify="left",
            anchor="w",
            wraplength=820,
        ).pack(fill="x", pady=(4, 12))

        progress = tk.Frame(current, bg=ui.PANEL)
        progress.pack(fill="x")
        ttk.Progressbar(progress, variable=window.percent_var, maximum=100, style="Galaxy.Horizontal.TProgressbar").pack(fill="x")
        window._percent_text_var = tk.StringVar(value="0%")
        _label(progress, variable=window._percent_text_var, size="body_sm", weight="bold", color=ui.MUTED).pack(anchor="e", pady=(5, 0))

        metrics = tk.Frame(current, bg=ui.PANEL)
        metrics.pack(fill="x", pady=(12, 0))
        for index, (title, variable) in enumerate((("速度", window.speed_var), ("剩余时间", window.eta_var), ("已下载", window.size_var))):
            metrics.grid_columnconfigure(index, weight=1)
            _metric(metrics, title, variable).grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 0))

        _hairline(main).pack(fill="x", pady=(18, 14))
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
            font=font("body", bold=True),
            bg=ui.PANEL,
            fg=ui.TEXT,
            activebackground=ui.PANEL,
            activeforeground=ui.ACCENT_HOVER,
            relief="flat",
            bd=0,
            highlightthickness=2,
            highlightbackground=ui.PANEL,
            highlightcolor=ui.FOCUS,
            cursor="hand2",
            padx=0,
            pady=8,
            takefocus=True,
        )
        toggle.pack(side="left")
        window._advanced_summary_var = tk.StringVar(value="片段 · 章节 · 字幕/音轨 · SponsorBlock · aria2c")
        _label(toggle_row, variable=window._advanced_summary_var, size="body_sm", color=ui.SUBTLE).pack(side="right")
        window._advanced_panel = tk.Frame(advanced, bg=ui.PANEL_2, padx=16, pady=16, highlightthickness=1, highlightbackground=ui.BORDER_SOFT)
        ui._build_advanced_panel(window, engine_module)

        actions = tk.Frame(main, bg=ui.PANEL)
        actions.pack(fill="x", side="bottom", pady=(18, 0))
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
        _label(queue_copy, variable=window._queue_count_var, size="body_sm", color=ui.MUTED).pack(anchor="w", pady=(3, 0))
        window._queue_clear_button = ui.ActionButton(queue_head, text="清空", command=lambda: ui._clear_queue_from_ui(window), kind="ghost", compact=True)
        window._queue_clear_button.pack(side="right", anchor="n")
        window._queue_clear_button.state(["disabled"])
        window._queue_panel = tk.Frame(rail, bg=ui.PANEL)
        window._queue_panel.pack(fill="both", expand=True, pady=(14, 0))

        runtime_box = tk.Frame(rail, bg=ui.PANEL)
        runtime_box.pack(fill="x", side="bottom", pady=(18, 0))
        _hairline(runtime_box).pack(fill="x", pady=(0, 14))
        _label(runtime_box, "本机组件", size="title_sm", weight="bold").pack(anchor="w")
        component_rows = tk.Frame(runtime_box, bg=ui.PANEL)
        component_rows.pack(fill="x", pady=(8, 12))
        _status_item(component_rows, "FFmpeg", engine_module.ffmpeg_dir() is not None).pack(anchor="w")
        _status_item(component_rows, "yt-dlp", engine_module.external_ytdlp_path(engine_module.app_dir()) is not None).pack(anchor="w")
        _status_item(component_rows, "aria2（可选）", aria2c_available(engine_module), optional=True).pack(anchor="w")
        window._latest_var = tk.StringVar(value=f"Engine {engine_module.VERSION} · UI {NATIVE_UI_REVISION}")
        _label(runtime_box, variable=window._latest_var, size="caption", color=ui.SUBTLE).pack(anchor="w", pady=(0, 8))
        window._update_button = ui.ActionButton(runtime_box, text="检查稳定版更新", command=lambda: ui._check_update(window, engine_module), kind="ghost", compact=True)
        window._update_button.pack(fill="x")

        run_after_build_ui_hooks(window)
        window._galaxy_ui_tick()
        window._galaxy_queue_tick()

    window_cls._build_ui = build_ui
    window_cls._galaxy_native_v17_installed = True
    return window_cls


def run_native_desktop_v17_self_test() -> None:
    assert NATIVE_UI_REVISION == "1.7.0"
    assert TYPE["body"] >= 11
    assert TYPE["caption"] >= 9
    assert callable(install_native_desktop_v17)


if __name__ == "__main__":
    run_native_desktop_v17_self_test()
    print("Native desktop V1.7 self-test passed")
