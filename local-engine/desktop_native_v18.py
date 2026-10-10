from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

import desktop_native_v17 as v17
from desktop_design_tokens import TYPE, font
from desktop_hooks import run_after_build_ui_hooks, show_desktop_presenter
from media_policy import aria2c_available

NATIVE_UI_REVISION = "1.8.0"
ui = None


def _label(master, text=None, *, variable=None, size="body", weight="normal", color=None, bg=None, **kwargs):
    return ui._label(master, text, variable=variable, size=size, weight=weight, color=color or ui.TEXT, bg=bg or master.cget("bg"), **kwargs)


def _line(master):
    return tk.Frame(master, height=1, bg=ui.BORDER_SOFT)


def _present(window, slot: str) -> None:
    try:
        show_desktop_presenter(window, slot)
    except Exception as exc:  # noqa: BLE001
        try:
            window.detail_var.set((str(exc) or f"{slot} unavailable")[:220])
        except Exception:
            pass


def _build_menu(window, engine_module) -> None:
    common = dict(tearoff=False, bg=ui.PANEL, fg=ui.TEXT, activebackground=ui.PANEL_3, activeforeground=ui.TEXT)
    menu = tk.Menu(window, **common)
    file_menu = tk.Menu(menu, **common)
    file_menu.add_command(label="粘贴链接", accelerator="Ctrl+V", command=lambda: __import__("desktop_quick_download")._paste_quick_url(window))
    file_menu.add_separator()
    file_menu.add_command(label="打开下载目录", command=window.open_folder)
    file_menu.add_command(label="退出", command=window.close_app)
    menu.add_cascade(label="文件", menu=file_menu)

    task = tk.Menu(menu, **common)
    task.add_command(label="解析当前链接", command=lambda: __import__("desktop_download_workbench")._parse_quick_url_async(window, engine_module))
    task.add_command(label="下载所选内容", accelerator="Ctrl+Enter", command=lambda: __import__("desktop_quick_download")._submit_quick_download(window, engine_module))
    task.add_separator()
    task.add_command(label="取消当前任务", command=window.cancel)
    task.add_command(label="当前任务详情", command=lambda: __import__("desktop_extras")._show_job_details(window, engine_module))
    task.add_command(label="打开当前文件", command=lambda: __import__("desktop_extras")._open_current_file(window, engine_module))
    task.add_command(label="下载历史", command=lambda: _present(window, "history"))
    menu.add_cascade(label="任务", menu=task)

    view = tk.Menu(menu, **common)
    view.add_command(label="Transcript", command=lambda: _present(window, "transcript"))
    view.add_command(label="任务中心", command=lambda: _present(window, "task-center"))
    view.add_command(label="媒体库", command=lambda: _present(window, "library"))
    menu.add_cascade(label="视图", menu=view)

    tools = tk.Menu(menu, **common)
    tools.add_command(label="工具管理", command=lambda: _present(window, "tools"))
    tools.add_command(label="运行环境", command=lambda: _present(window, "runtime"))
    tools.add_command(label="设置 / Profiles", command=lambda: _present(window, "profiles"))
    menu.add_cascade(label="工具", menu=tools)

    help_menu = tk.Menu(menu, **common)
    help_menu.add_command(label="复制诊断", command=lambda: ui._copy_diagnostics(window, engine_module))
    help_menu.add_command(label="检查稳定版更新", command=lambda: ui._check_update(window, engine_module))
    help_menu.add_separator()
    help_menu.add_command(label="打开 SparkDownloader", command=lambda: webbrowser.open(ui.WEBSITE_URL))
    menu.add_cascade(label="帮助", menu=help_menu)
    window.configure(menu=menu)
    window._v18_menubar = menu


def _row(master, name: str, variable: tk.Variable) -> tk.Frame:
    row = tk.Frame(master, bg=ui.PANEL_2, pady=3)
    _label(row, name, size="caption", color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w")
    _label(row, variable=variable, size="body_sm", bg=ui.PANEL_2, wraplength=250, justify="left").pack(anchor="w", pady=(2, 0))
    return row


def _build_quick_panel_v18(window, engine_module) -> None:
    import desktop_gallery_dl as gallery
    import desktop_original_images as originals
    import desktop_quick_download as quick

    panel = window._v18_source_host
    window._quick_download_panel = panel
    window._galaxy_gallery_dl_fallback_built = True
    window._galaxy_gallery_compact_installed = True
    window._galaxy_queue_header_stable = True

    source = tk.Frame(panel, bg=ui.PANEL, padx=18, pady=14)
    source.pack(fill="x")
    title = tk.Frame(source, bg=ui.PANEL)
    title.pack(fill="x")
    _label(title, "来源", size="title_sm", weight="bold", bg=ui.PANEL).pack(side="left")
    _label(title, "只有主动解析时才会联网", size="body_sm", color=ui.MUTED, bg=ui.PANEL).pack(side="right")

    window._quick_url_var = tk.StringVar()
    window._quick_url_entry = tk.Entry(
        source, textvariable=window._quick_url_var, font=font("body"), bg=ui.PANEL_3, fg=ui.TEXT,
        insertbackground=ui.TEXT, selectbackground=ui.ACCENT, selectforeground="#FFFFFF", relief="flat", bd=0,
        highlightthickness=2, highlightbackground=ui.BORDER, highlightcolor=ui.FOCUS,
    )
    window._quick_url_entry.pack(fill="x", ipady=9, pady=(10, 0))
    window._quick_state_var = tk.StringVar(value="等待链接 · 不会在后台读取剪贴板或自动联网")
    _label(source, variable=window._quick_state_var, size="body_sm", color=ui.CYAN, bg=ui.PANEL, wraplength=820, justify="left").pack(anchor="w", pady=(8, 0))

    commands = window._v18_toolbar_commands
    ui.ActionButton(commands, text="粘贴", command=lambda: quick._paste_quick_url(window), kind="secondary", compact=True).pack(side="left")
    window._quick_parse_button = ui.ActionButton(commands, text="解析", command=lambda: quick._parse_quick_url(window, engine_module), kind="primary", compact=True)
    window._quick_parse_button.pack(side="left", padx=(6, 0))
    window._quick_download_button = ui.ActionButton(commands, text="下载所选", command=lambda: quick._submit_quick_download(window, engine_module), kind="secondary", compact=True)
    window._quick_download_button.pack(side="left", padx=(6, 0))
    window._quick_download_button.state(["disabled"])
    window._quick_url_entry.bind("<Return>", lambda _event: quick._parse_quick_url(window, engine_module))
    window.bind("<Control-Return>", lambda _event: quick._submit_quick_download(window, engine_module), add="+")

    style = ttk.Style(window)
    style.configure("Galaxy.Workbench.TNotebook", background=ui.PANEL, borderwidth=0)
    style.configure("Galaxy.Workbench.TNotebook.Tab", background=ui.PANEL, foreground=ui.MUTED, padding=(14, 8), borderwidth=0, font=font("body_sm", bold=True))
    style.map("Galaxy.Workbench.TNotebook.Tab", background=[("selected", ui.PANEL_2), ("active", ui.PANEL_2)], foreground=[("selected", ui.TEXT), ("active", ui.TEXT)])

    notebook = ttk.Notebook(panel, style="Galaxy.Workbench.TNotebook")
    notebook.pack(fill="both", expand=True, padx=18, pady=(0, 14))
    overview, video_tab, audio_tab, image_tab, info_tab = [tk.Frame(notebook, bg=ui.PANEL, padx=4, pady=12) for _ in range(5)]
    for tab, text in ((overview, "概览"), (video_tab, "视频"), (audio_tab, "音频"), (image_tab, "原图"), (info_tab, "信息")):
        notebook.add(tab, text=text)
    window._v18_resource_notebook = notebook

    window._quick_preview_panel = tk.Frame(overview, bg=ui.PANEL)
    window._quick_title_var = tk.StringVar()
    window._quick_meta_var = tk.StringVar()
    _label(window._quick_preview_panel, variable=window._quick_title_var, size="title", weight="bold", bg=ui.PANEL, wraplength=760, justify="left").pack(anchor="w")
    _label(window._quick_preview_panel, variable=window._quick_meta_var, size="body_sm", color=ui.MUTED, bg=ui.PANEL).pack(anchor="w", pady=(4, 10))
    _label(window._quick_preview_panel, "资源已经按类型拆分；顶部工具栏负责高频下载动作。", size="body_sm", color=ui.SUBTLE, bg=ui.PANEL).pack(anchor="w")
    tk.Frame(window._quick_preview_panel, bg=ui.PANEL).pack(fill="x", pady=(8, 0))

    window._quick_video_var = tk.StringVar()
    _label(video_tab, "视频格式", size="title_sm", weight="bold", bg=ui.PANEL).pack(anchor="w")
    window._quick_video_combo = ttk.Combobox(video_tab, textvariable=window._quick_video_var, state="disabled", style="Galaxy.TCombobox")
    window._quick_video_combo.pack(fill="x", pady=(10, 0))

    window._quick_audio_var = tk.StringVar()
    window._workbench_audio_hint_var = tk.StringVar(value="选择视频格式后会自动判断是否需要独立音轨。")
    window._v18_audio_hint_var = window._workbench_audio_hint_var
    _label(audio_tab, "音频格式", size="title_sm", weight="bold", bg=ui.PANEL).pack(anchor="w")
    _label(audio_tab, variable=window._v18_audio_hint_var, size="body_sm", color=ui.MUTED, bg=ui.PANEL, wraplength=760, justify="left").pack(anchor="w", pady=(3, 10))
    window._quick_audio_combo = ttk.Combobox(audio_tab, textvariable=window._quick_audio_var, state="disabled", style="Galaxy.TCombobox")
    window._quick_audio_combo.pack(fill="x")

    _label(image_tab, "网页原图 / 商品图集", size="title_sm", weight="bold", bg=ui.PANEL).pack(anchor="w")
    _label(image_tab, "优先探测公开原尺寸或更高分辨率变体；失败时按真实像素向下回退。", size="body_sm", color=ui.MUTED, bg=ui.PANEL, wraplength=760, justify="left").pack(anchor="w", pady=(3, 12))
    image_actions = tk.Frame(image_tab, bg=ui.PANEL)
    image_actions.pack(fill="x")
    window._original_images_button = ui.ActionButton(image_actions, text="下载页面原图", command=lambda: originals._download_original_images(window, engine_module), kind="primary")
    window._original_images_button.pack(side="left")
    window._v18_original_images_button = window._original_images_button
    window._gallery_dl_fallback_button = ui.ActionButton(image_actions, text="图库备用", command=lambda: gallery._submit_gallery_fallback(window, engine_module), kind="secondary")
    window._gallery_dl_fallback_button.pack(side="left", padx=(8, 0))
    window._v18_gallery_dl_fallback_button = window._gallery_dl_fallback_button

    window._v18_info_source_var = tk.StringVar(value="等待解析")
    window._v18_info_format_var = tk.StringVar(value="尚未选择格式")
    _label(info_tab, "来源信息", size="title_sm", weight="bold", bg=ui.PANEL).pack(anchor="w")
    _row(info_tab, "当前来源", window._v18_info_source_var).pack(fill="x", pady=(8, 0))
    _row(info_tab, "当前格式", window._v18_info_format_var).pack(fill="x")

    inspector = window._v18_inspector_content
    _label(inspector, "来源属性", size="title_sm", weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    _label(inspector, "登录环境", size="caption", color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w", pady=(12, 4))
    window._quick_browser_var = tk.StringVar(value=quick._BROWSER_BY_KEY["none"])
    ttk.Combobox(inspector, textvariable=window._quick_browser_var, values=tuple(quick._BROWSER_LABELS), state="readonly", style="Galaxy.TCombobox").pack(fill="x")
    _label(inspector, "下载 Profile", size="caption", color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w", pady=(12, 4))
    window._quick_profile_var = tk.StringVar(value=quick._AUTO_PROFILE_LABEL)
    window._quick_profile_ids = {quick._AUTO_PROFILE_LABEL: ""}
    window._quick_profile_combo = ttk.Combobox(inspector, textvariable=window._quick_profile_var, values=(quick._AUTO_PROFILE_LABEL,), state="readonly", style="Galaxy.TCombobox")
    window._quick_profile_combo.pack(fill="x")
    ui.ActionButton(inspector, text="刷新 Profiles", command=lambda: quick._refresh_quick_profiles(window, engine_module), kind="ghost", compact=True).pack(anchor="w", pady=(7, 0))

    _line(inspector).pack(fill="x", pady=14)
    _label(inspector, "高级下载", size="title_sm", weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    window._advanced_open = False
    window._advanced_toggle_var = tk.StringVar(value="展开高级设置  ›")
    tk.Button(inspector, textvariable=window._advanced_toggle_var, command=lambda: ui._toggle_advanced(window), font=font("body_sm", bold=True), bg=ui.PANEL_2, fg=ui.TEXT, activebackground=ui.PANEL_2, activeforeground=ui.ACCENT_HOVER, relief="flat", bd=0, highlightthickness=2, highlightbackground=ui.PANEL_2, highlightcolor=ui.FOCUS, cursor="hand2", padx=0, pady=7, takefocus=True).pack(anchor="w")
    window._advanced_summary_var = tk.StringVar(value="片段 · 章节 · 字幕/音轨 · SponsorBlock · aria2c")
    _label(inspector, variable=window._advanced_summary_var, size="caption", color=ui.SUBTLE, bg=ui.PANEL_2, wraplength=250, justify="left").pack(anchor="w")
    window._advanced_panel = tk.Frame(inspector, bg=ui.PANEL_2)
    ui._build_advanced_panel(window, engine_module)

    window._quick_preview = None
    window._quick_video_display = {}
    window._quick_audio_display = {}
    window._quick_parse_generation = 0
    quick._refresh_quick_profiles(window, engine_module)

    def sync(*_args):
        source_text = quick._text(window._quick_url_var.get(), "等待解析")
        selected = " · ".join(x for x in (quick._text(window._quick_video_var.get()), quick._text(window._quick_audio_var.get())) if x) or "尚未选择格式"
        for variable, value in ((window._v18_info_source_var, source_text), (window._v18_info_format_var, selected), (window._v18_inspector_source_var, source_text), (window._v18_inspector_format_var, selected)):
            variable.set(value[:220])
    for variable in (window._quick_url_var, window._quick_video_var, window._quick_audio_var):
        variable.trace_add("write", sync)
    sync()


def _clean_legacy_chrome(window) -> None:
    phase = tuple(getattr(window, "_workbench_phase_widgets", ()) or ())
    if phase:
        try:
            phase[0].master.destroy()
        except tk.TclError:
            pass
        window._workbench_phase_widgets = ()
    preview = getattr(window, "_quick_preview_panel", None)
    if preview is not None:
        for child in list(preview.winfo_children()):
            try:
                if isinstance(child, tk.Frame) and str(child.cget("bg")) == str(ui.PANEL_3):
                    child.destroy()
            except tk.TclError:
                pass
    window._workbench_audio_hint_var = getattr(window, "_v18_audio_hint_var", getattr(window, "_workbench_audio_hint_var", None))
    try:
        window._quick_download_panel.configure(padx=0, pady=0, highlightthickness=0)
        window._quick_parse_button.configure(text="解析")
        window._quick_download_button.configure(text="下载所选")
    except tk.TclError:
        pass
    for name in ("_job_detail_button", "_open_file_button"):
        button = getattr(window, name, None)
        if button is not None:
            try:
                button.pack_forget()
            except tk.TclError:
                pass
    strip = getattr(window, "_original_images_strip", None)
    if strip is not None:
        try:
            strip.destroy()
        except tk.TclError:
            pass
        window._original_images_button = window._v18_original_images_button
    window._gallery_dl_fallback_button = window._v18_gallery_dl_fallback_button


def install_native_desktop_v18(engine_module, ui_module):
    global ui
    ui = ui_module
    v17.ui = ui_module
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_native_v18_installed", False):
        return window_cls
    if not getattr(window_cls, "_galaxy_desktop_ui_installed", False):
        raise RuntimeError("install_native_desktop_v18 requires install_desktop_ui first")

    import desktop_quick_download as quick
    quick._build_quick_panel = _build_quick_panel_v18

    def build_ui(window) -> None:
        window._galaxy_native_v18 = True
        window.configure(bg=ui.BG)
        window.geometry("1360x900")
        window.minsize(1020, 700)
        window.option_add("*Font", "{Segoe UI} 11")
        v17._configure_styles(window)
        try:
            icon = v17._make_titlebar_icon(window, 32)
            window._galaxy_icon = icon
            window.iconphoto(True, icon)
        except tk.TclError:
            pass
        window.title(f"Galaxy Local Engine · {engine_module.VERSION}")
        _build_menu(window, engine_module)

        shell = tk.Frame(window, bg=ui.BG)
        shell.pack(fill="both", expand=True)
        toolbar = tk.Frame(shell, bg=ui.PANEL, height=52)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)
        identity = tk.Frame(toolbar, bg=ui.PANEL)
        identity.pack(side="left", padx=(14, 10), fill="y")
        _label(identity, "Galaxy", size="title_sm", weight="bold", bg=ui.PANEL).pack(side="left", anchor="center")
        _label(identity, "Local Engine", size="body_sm", color=ui.MUTED, bg=ui.PANEL).pack(side="left", anchor="center", padx=(6, 0))
        window._v18_toolbar_commands = tk.Frame(toolbar, bg=ui.PANEL)
        window._v18_toolbar_commands.pack(side="left", fill="y", pady=6)
        toolbar_right = tk.Frame(toolbar, bg=ui.PANEL)
        toolbar_right.pack(side="right", fill="y", padx=12, pady=6)
        window.cancel_button = ui.ActionButton(toolbar_right, text="取消", command=window.cancel, kind="danger", compact=True)
        window.cancel_button.pack(side="left")
        window.cancel_button.state(["disabled"])
        window.folder_button = ui.ActionButton(toolbar_right, text="打开目录", command=window.open_folder, kind="secondary", compact=True)
        window.folder_button.pack(side="left", padx=(6, 0))
        _line(shell).pack(fill="x")

        body = tk.PanedWindow(shell, orient="horizontal", bg=ui.BORDER_SOFT, sashwidth=5, sashrelief="flat", bd=0, highlightthickness=0, opaqueresize=True)
        body.pack(fill="both", expand=True)
        workspace, inspector = tk.Frame(body, bg=ui.PANEL), tk.Frame(body, bg=ui.PANEL_2, width=300)
        body.add(workspace, minsize=680, stretch="always")
        body.add(inspector, minsize=260, stretch="never")
        window._v18_source_host = tk.Frame(workspace, bg=ui.PANEL)
        window._v18_source_host.pack(fill="both", expand=True)

        task_strip = tk.Frame(workspace, bg=ui.PANEL_2, padx=18, pady=11)
        task_strip.pack(fill="x", side="bottom")
        task_top = tk.Frame(task_strip, bg=ui.PANEL_2)
        task_top.pack(fill="x")
        _label(task_top, variable=window.status_var, size="title_sm", weight="bold", bg=ui.PANEL_2).pack(side="left")
        window._queue_summary_var = tk.StringVar(value="等待 0 项")
        _label(task_top, variable=window._queue_summary_var, size="body_sm", color=ui.MUTED, bg=ui.PANEL_2).pack(side="right")
        _label(task_strip, variable=window.detail_var, size="body_sm", color=ui.MUTED, bg=ui.PANEL_2, wraplength=760, justify="left").pack(fill="x", pady=(3, 7))
        ttk.Progressbar(task_strip, variable=window.percent_var, maximum=100, style="Galaxy.Horizontal.TProgressbar").pack(fill="x")
        stats = tk.Frame(task_strip, bg=ui.PANEL_2)
        stats.pack(fill="x", pady=(6, 0))
        window._percent_text_var = tk.StringVar(value="0%")
        _label(stats, variable=window._percent_text_var, size="caption", weight="bold", color=ui.MUTED, bg=ui.PANEL_2).pack(side="left")
        for name, variable in (("速度", window.speed_var), ("剩余", window.eta_var), ("已下载", window.size_var)):
            _label(stats, f"  {name} ", size="caption", color=ui.SUBTLE, bg=ui.PANEL_2).pack(side="left", padx=(10, 0))
            _label(stats, variable=variable, size="caption", bg=ui.PANEL_2).pack(side="left")

        head = tk.Frame(inspector, bg=ui.PANEL_2, padx=16, pady=14)
        head.pack(fill="x")
        _label(head, "属性", size="title_sm", weight="bold", bg=ui.PANEL_2).pack(anchor="w")
        _label(head, "当前来源与下载设置", size="caption", color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w", pady=(2, 0))
        _line(inspector).pack(fill="x")
        window._v18_inspector_content = tk.Frame(inspector, bg=ui.PANEL_2, padx=16, pady=14)
        window._v18_inspector_content.pack(fill="both", expand=True)
        window._v18_inspector_source_var, window._v18_inspector_format_var = tk.StringVar(value="等待链接"), tk.StringVar(value="尚未选择格式")
        summary = tk.Frame(inspector, bg=ui.PANEL_2, padx=16, pady=12)
        summary.pack(fill="x", side="bottom")
        _line(summary).pack(fill="x", pady=(0, 10))
        _row(summary, "来源", window._v18_inspector_source_var).pack(fill="x")
        _row(summary, "格式", window._v18_inspector_format_var).pack(fill="x")

        queue = tk.Frame(shell, bg=ui.PANEL, height=220)
        queue.pack(fill="x", side="bottom")
        queue.pack_propagate(False)
        _line(queue).pack(fill="x")
        queue_head = tk.Frame(queue, bg=ui.PANEL, padx=14, pady=9)
        queue_head.pack(fill="x")
        qcopy = tk.Frame(queue_head, bg=ui.PANEL)
        qcopy.pack(side="left", fill="x", expand=True)
        _label(qcopy, "下载队列", size="title_sm", weight="bold", bg=ui.PANEL).pack(side="left")
        window._queue_count_var = tk.StringVar(value="当前 0 · 等待 0")
        _label(qcopy, variable=window._queue_count_var, size="body_sm", color=ui.MUTED, bg=ui.PANEL).pack(side="left", padx=(10, 0))
        window._queue_clear_button = ui.ActionButton(queue_head, text="清空", command=lambda: ui._clear_queue_from_ui(window), kind="ghost", compact=True)
        window._queue_clear_button.pack(side="right")
        window._queue_clear_button.state(["disabled"])
        window._queue_panel = tk.Frame(queue, bg=ui.PANEL, padx=14, pady=2)
        window._queue_panel.pack(fill="both", expand=True)

        window._update_button = ui.ActionButton(inspector, text="检查更新", command=lambda: ui._check_update(window, engine_module), kind="ghost", compact=True)
        status = tk.Frame(shell, bg=ui.BG, height=28, padx=10)
        status.pack(fill="x", side="bottom")
        status.pack_propagate(False)
        ffmpeg_ready = engine_module.ffmpeg_dir() is not None
        ytdlp_ready = engine_module.external_ytdlp_path(engine_module.app_dir()) is not None
        aria_ready = aria2c_available(engine_module)
        _label(status, f"FFmpeg {'✓' if ffmpeg_ready else '×'}   yt-dlp {'✓' if ytdlp_ready else '×'}   aria2 {'✓' if aria_ready else '可选'}", size="caption", color=ui.MUTED, bg=ui.BG).pack(side="left")
        window._latest_var = tk.StringVar(value=f"Engine {engine_module.VERSION} · UI {NATIVE_UI_REVISION}")
        _label(status, variable=window._latest_var, size="caption", color=ui.SUBTLE, bg=ui.BG).pack(side="right")

        run_after_build_ui_hooks(window)
        _clean_legacy_chrome(window)
        window._galaxy_ui_tick()
        window._galaxy_queue_tick()

    window_cls._build_ui = build_ui
    window_cls._galaxy_native_v18_installed = True
    return window_cls


def run_native_desktop_v18_self_test() -> None:
    assert NATIVE_UI_REVISION == "1.8.0"
    assert TYPE["body"] >= 11
    assert callable(install_native_desktop_v18)
    assert callable(_build_quick_panel_v18)


if __name__ == "__main__":
    run_native_desktop_v18_self_test()
    print("Native desktop V1.8 self-test passed")
