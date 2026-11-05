from __future__ import annotations

import importlib.util
import tkinter as tk
import webbrowser
from tkinter import ttk

from desktop_design_tokens import COLOR, LAYOUT, TYPE, font
from desktop_hooks import run_after_build_ui_hooks
from media_policy import aria2c_available
from desktop_workbench_motion import ModeTabs, ProgressMeter, system_reduces_motion
from desktop_workbench_style import ORBIT, button, configure_orbit, icon_image

NATIVE_UI_REVISION = "1.8.0"
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


def _text_wrap(label, container, *, inset=0):
    def resize(event):
        label.configure(wraplength=max(70, event.width - inset))
    container.bind("<Configure>", resize, add="+")
    return label


def _scrollable_workbench(parent, window, *, column=0):
    outer = tk.Frame(parent, bg=ORBIT["shell"])
    outer.grid(row=0, column=column, sticky="nsew", padx=(0, 14) if column == 0 else 0)
    outer.grid_rowconfigure(0, weight=1)
    outer.grid_columnconfigure(0, weight=1)
    canvas = tk.Canvas(outer, bg=ORBIT["shell"], highlightthickness=0, bd=0, yscrollincrement=16)
    canvas.grid(row=0, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(outer, orient="vertical", style="Orbit.Vertical.TScrollbar", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    content = tk.Frame(canvas, bg=ORBIT["shell"])
    content_id = canvas.create_window((0, 0), window=content, anchor="nw")

    def size_changed(_event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
        if content.winfo_reqheight() > canvas.winfo_height() + 2:
            scroll.grid(row=0, column=1, sticky="ns", padx=(3, 0))
        else:
            scroll.grid_remove()
            canvas.yview_moveto(0)

    def fit(event):
        canvas.itemconfigure(content_id, width=event.width)
        size_changed()

    def owns(widget, boundary):
        while widget is not None and widget is not boundary:
            widget = getattr(widget, "master", None)
        return widget is boundary

    def wheel(event):
        target = window.winfo_containing(event.x_root, event.y_root)
        if owns(target, outer) and content.winfo_reqheight() > canvas.winfo_height():
            # Do not steal a combobox list or text widget's own scrolling.
            if target and target.winfo_class() in ("TCombobox", "Listbox", "Text", "Treeview"):
                return None
            delta = getattr(event, "delta", 0)
            sign = -1 if getattr(event, "num", 0) == 4 or delta > 0 else 1
            canvas.yview_scroll(sign * max(1, abs(delta) // 120) * 3, "units")
            return "break"
        return None

    def reveal(event):
        child = event.widget
        if not owns(child, content):
            return
        top = child.winfo_rooty() - canvas.winfo_rooty()
        height = canvas.winfo_height()
        bottom = top + child.winfo_height()
        if top < 0 or bottom > height:
            offset = child.winfo_rooty() - content.winfo_rooty()
            offset -= (height - child.winfo_height() - 12) if bottom > height else 12
            canvas.yview_moveto(max(0, offset) / max(1, content.winfo_reqheight()))

    content.bind("<Configure>", size_changed)
    canvas.bind("<Configure>", fit)
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        window.bind(sequence, wheel, add="+")
    window.bind("<FocusIn>", reveal, add="+")
    setattr(window, "_workbench_canvas" if column == 0 else "_rail_canvas", canvas)
    return outer, content


def _card(parent, *, padx=18, pady=15):
    return tk.Frame(parent, bg=ORBIT["white"], padx=padx, pady=pady, highlightthickness=1, highlightbackground=ORBIT["line"])


def _hero(parent):
    hero = tk.Frame(parent, bg=ORBIT["hero"], padx=20, pady=15)
    hero.pack(fill="x", pady=(0, 14))
    copy = tk.Frame(hero, bg=ORBIT["hero"])
    copy.pack(side="left", fill="x", expand=True)
    tk.Label(copy, text="G A L A X Y   /   L O C A L", bg=ORBIT["hero"], fg=ORBIT["hero_quiet"], font=("Segoe UI", 9, "bold"), anchor="w", bd=0).pack(fill="x")
    _label(copy, "媒体下载工作台", size="display", weight="bold", color=ORBIT["hero_text"], bg=ORBIT["hero"]).pack(anchor="w", pady=(3, 1))
    _label(copy, "粘贴链接，选好画质，再保存到本机。", size="body_sm", color=ORBIT["hero_quiet"], bg=ORBIT["hero"]).pack(anchor="w")
    # A static orbit motif supports the brand without running an idle animation.
    art = tk.Canvas(hero, width=145, height=86, bg=ORBIT["hero"], bd=0, highlightthickness=0)
    art.pack(side="right", padx=(14, 0))
    for inset in (0, 10, 20):
        art.create_oval(41 + inset, -17 + inset, 147 - inset, 91 - inset, outline=ORBIT["hero_line"], width=1)
    art.create_line(15, 67, 145, 30, fill=ORBIT["hero_line"], width=1)
    art.create_oval(91, 32, 100, 41, fill="#AFC6FF", outline="")
    art.create_oval(43, 58, 48, 63, fill="#82A6F7", outline="")
    art.create_oval(121, 11, 126, 16, fill="#82A6F7", outline="")
    return hero


def _build_quick_panel_v17(window, engine_module):
    import desktop_quick_download as quick

    panel = _card(window._orbit_main, padx=16, pady=13)
    panel.pack(fill="x", after=window._orbit_hero, pady=(0, 14))
    window._quick_download_panel = panel
    head = tk.Frame(panel, bg=ui.PANEL)
    head.pack(fill="x", pady=(0, 7))
    _label(head, "新建下载", size="title_sm", weight="bold").pack(side="left")
    _label(head, "Ctrl + L 定位链接", size="caption", color=ui.SUBTLE).pack(side="right")

    def switch_mode(index):
        window._orbit_video_controls.pack_forget()
        window._orbit_image_details.pack_forget()
        window._orbit_profile_field.grid_remove()
        window._orbit_advanced_container.pack_forget()
        if index == 0:
            window._orbit_profile_field.grid()
            window._orbit_video_controls.pack(fill="x", before=state, pady=(9, 0))
            window._orbit_advanced_container.pack(fill="x", pady=(0, 14))
        else:
            window._orbit_image_details.pack(fill="x", before=state, pady=(9, 0))
        hint.set("商品页或图片页面链接" if index else "视频或音频链接")
        if not window._quick_url_var.get().strip():
            window._quick_state_var.set("粘贴商品页链接后按 Enter 下载原图。" if index else "粘贴链接后按 Enter 解析。")

    tabs = ModeTabs(panel, window._orbit_reduced, switch_mode)
    tabs.pack(fill="x", pady=(0, 13))
    window._orbit_tabs = tabs
    hint = tk.StringVar(value="视频或音频链接")
    _label(panel, variable=hint, size="body_sm", weight="bold").pack(anchor="w", pady=(0, 6))
    url_row = tk.Frame(panel, bg=ui.PANEL)
    url_row.pack(fill="x")
    url_row.grid_columnconfigure(0, weight=1)
    window._quick_url_var = tk.StringVar()
    entry = tk.Entry(url_row, textvariable=window._quick_url_var, font=font("body"), bg=ORBIT["inset"], fg=ui.TEXT,
                     insertbackground=ui.TEXT, selectbackground=ui.ACCENT, selectforeground=COLOR["on_accent"],
                     relief="flat", bd=0, highlightthickness=1, highlightbackground=ui.BORDER, highlightcolor=ui.FOCUS)
    entry.grid(row=0, column=0, sticky="ew", ipady=10)
    window._quick_url_entry = entry
    button(url_row, "粘贴", lambda: quick._paste_quick_url(window)).grid(row=0, column=1, padx=(8, 0))

    options = tk.Frame(panel, bg=ui.PANEL)
    options.pack(fill="x", pady=(10, 0))
    for i in (0, 1):
        options.grid_columnconfigure(i, weight=1, uniform="options")
    browser_field = tk.Frame(options, bg=ui.PANEL)
    browser_field.grid(row=0, column=0, sticky="ew", padx=(0, 6))
    _label(browser_field, "浏览器登录", size="caption", color=ui.MUTED).pack(anchor="w", pady=(0, 4))
    window._quick_browser_var = tk.StringVar(value=quick._BROWSER_BY_KEY["none"])
    ttk.Combobox(browser_field, textvariable=window._quick_browser_var, values=tuple(quick._BROWSER_LABELS), state="readonly", width=12, style="Galaxy.TCombobox").pack(fill="x")
    profile = tk.Frame(options, bg=ui.PANEL)
    profile.grid(row=0, column=1, sticky="ew", padx=(6, 0))
    window._orbit_profile_field = profile
    profile_head = tk.Frame(profile, bg=ui.PANEL)
    profile_head.pack(fill="x", pady=(0, 4))
    _label(profile_head, "下载预设", size="caption", color=ui.MUTED).pack(side="left")
    window._quick_profile_var = tk.StringVar(value=quick._AUTO_PROFILE_LABEL)
    window._quick_profile_ids = {quick._AUTO_PROFILE_LABEL: ""}
    window._quick_profile_combo = ttk.Combobox(profile, textvariable=window._quick_profile_var, values=(quick._AUTO_PROFILE_LABEL,), state="readonly", width=12, style="Galaxy.TCombobox")
    window._quick_profile_combo.pack(fill="x")
    window._quick_profile_combo.bind("<ButtonPress-1>", lambda _event: quick._refresh_quick_profiles(window, engine_module), add="+")
    window._quick_profile_combo.bind("<FocusIn>", lambda _event: quick._refresh_quick_profiles(window, engine_module), add="+")

    video = tk.Frame(panel, bg=ui.PANEL)
    video.pack(fill="x", pady=(9, 0))
    window._orbit_video_controls = video
    actions = tk.Frame(video, bg=ui.PANEL)
    actions.pack(fill="x")
    _label(actions, "最佳可用画质", size="caption", weight="bold", bg=ORBIT["inset"], color=ui.CYAN, padx=8, pady=5).pack(side="left")
    window._quick_parse_button = button(actions, "解析并预览", lambda: quick._parse_quick_url(window, engine_module), kind="Primary", icon="arrow")
    window._quick_parse_button.pack(side="right")

    preview = tk.Frame(video, bg=ui.PANEL_3, padx=12, pady=11)
    window._quick_preview_panel = preview
    window._quick_title_var = tk.StringVar()
    window._quick_meta_var = tk.StringVar()
    _text_wrap(_label(preview, variable=window._quick_title_var, size="title_sm", weight="bold", bg=ui.PANEL_3, justify="left"), preview, inset=26).pack(anchor="w")
    _label(preview, variable=window._quick_meta_var, size="caption", color=ui.MUTED, bg=ui.PANEL_3).pack(anchor="w", pady=(3, 8))
    formats = tk.Frame(preview, bg=ui.PANEL_3)
    formats.pack(fill="x")
    for i, kind in enumerate(("video", "audio")):
        formats.grid_columnconfigure(i, weight=1, uniform="formats")
        field = tk.Frame(formats, bg=ui.PANEL_3)
        field.grid(row=0, column=i, sticky="ew", padx=(0, 6) if i == 0 else (6, 0))
        _label(field, "视频" if i == 0 else "音频", size="caption", color=ui.MUTED, bg=ui.PANEL_3).pack(anchor="w")
        variable = tk.StringVar()
        combo = ttk.Combobox(field, textvariable=variable, state="disabled", width=12, style="Galaxy.TCombobox")
        combo.pack(fill="x", pady=(4, 0))
        setattr(window, f"_quick_{kind}_var", variable)
        setattr(window, f"_quick_{kind}_combo", combo)
    footer = tk.Frame(preview, bg=ui.PANEL_3)
    footer.pack(fill="x", pady=(9, 0))
    window._quick_download_button = button(footer, "下载 / 加入队列", lambda: quick._submit_quick_download(window, engine_module), kind="Primary", icon="download")
    window._quick_download_button.pack(side="right")
    window._quick_download_button.state(["disabled"])

    window._orbit_image_details = tk.Frame(panel, bg=ui.PANEL)
    window._quick_state_var = tk.StringVar(value="粘贴链接后按 Enter 解析。")
    state = _text_wrap(_label(panel, variable=window._quick_state_var, size="caption", color=ui.MUTED, justify="left", anchor="w"), panel, inset=34)
    state.pack(fill="x", pady=(6, 0))
    window._quick_preview = None
    window._quick_video_display = {}
    window._quick_audio_display = {}
    window._quick_parse_generation = 0
    quick._refresh_quick_profiles(window, engine_module)


def _system_row(parent, name, status, color):
    row = tk.Frame(parent, bg=ui.PANEL)
    row.pack(fill="x", pady=(5, 0))
    _label(row, name, size="body_sm").pack(side="left")
    _label(row, status, size="caption", color=color).pack(side="right")


def _make_nav(window, sidebar):
    def invoke(name):
        control = getattr(window, name, None)
        if control is not None:
            control.invoke()

    def nav(label, icon, action, *, active=False, parent=sidebar):
        control = button(parent, label, action, kind="Nav", icon=icon)
        control.pack(fill="x", pady=(0, 3))
        if active:
            control.state(["selected"])
        return control

    def focus_composer():
        window._workbench_canvas.yview_moveto(0)
        window._quick_url_entry.focus_set()

    _label(sidebar, "工作区", size="caption", color=ORBIT["nav_quiet"], bg=ORBIT["nav"]).pack(anchor="w", padx=11, pady=(15, 7))
    nav("下载工作台", "download", focus_composer, active=True)
    nav("下载队列", "queue", lambda: invoke("_queue_manager_button"))
    nav("历史记录", "history", lambda: invoke("_history_button"))
    nav("媒体库", "library", lambda: invoke("_media_library_button"))
    bottom = tk.Frame(sidebar, bg=ORBIT["nav"])
    bottom.pack(side="bottom", fill="x")
    menu = tk.Menu(window, tearoff=False, font=font("body_sm"))
    for label, name in (("媒体工具", "_tools_button"), ("转录", "_transcript_button"), ("订阅", "_subscriptions_button"), ("去水印工作台", "_media_cleanup_button"), ("诊断日志", "_diagnostic_log_button"), ("复制诊断", "_copy_diag_button"), ("检查稳定版更新", "_update_button")):
        if getattr(window, name, None) is not None:
            menu.add_command(label=label, command=lambda value=name: invoke(value))
    menu.add_command(label="打开网页工作台", command=lambda: webbrowser.open(ui.WEBSITE_URL))
    menu.add_separator()
    menu.add_checkbutton(label="减少动效", variable=window._orbit_reduce_motion)

    def show_menu():
        menu.tk_popup(more.winfo_rootx(), more.winfo_rooty(), 0)
        menu.grab_release()

    more = nav("更多工具", "tools", show_menu, parent=bottom)
    nav("设置", "settings", lambda: invoke("_settings_button"), parent=bottom)
    _label(bottom, "LOCAL ENGINE", size="caption", color=ORBIT["nav_quiet"], bg=ORBIT["nav"]).pack(anchor="w", padx=11, pady=(9, 0))
    window._orbit_tools_menu = menu


def install_native_desktop_v17(engine_module, ui_module):
    global ui
    ui = ui_module
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_native_v17_installed", False):
        return window_cls
    if not getattr(window_cls, "_galaxy_desktop_ui_installed", False):
        raise RuntimeError("install_native_desktop_v17 requires install_desktop_ui first")

    import desktop_quick_download as quick
    quick._build_quick_panel = _build_quick_panel_v17

    def build_ui(window):
        window._orbit_shell = True
        window._galaxy_queue_header_stable = True  # This shell owns the queue toolbar layout.
        window.title("Galaxy · 媒体下载工作台")
        window.configure(bg=ORBIT["shell"])
        window.geometry("1280x800")
        window.minsize(960, 640)
        window.option_add("*Font", "{Segoe UI} 11")
        _configure_styles(window)
        configure_orbit(window)
        window._orbit_reduce_motion = tk.BooleanVar(value=system_reduces_motion())
        window._orbit_reduced = lambda: bool(window._orbit_reduce_motion.get())
        icon = _make_titlebar_icon(window)
        window._galaxy_icon = icon
        window.iconphoto(True, icon)

        shell = tk.Frame(window, bg=ORBIT["shell"])
        shell.pack(fill="both", expand=True)
        sidebar = tk.Frame(shell, bg=ORBIT["nav"], width=157, padx=11, pady=16)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        logo = tk.Frame(sidebar, bg=ORBIT["nav"])
        logo.pack(fill="x", padx=7)
        mark = tk.Label(logo, bg=ORBIT["nav_selected"], bd=0, padx=7, pady=6)
        mark._orbit_icon = icon_image(mark, "download", "#C7D7FF", size=19, pad=0)
        mark.configure(image=mark._orbit_icon)
        mark.pack(side="left", padx=(0, 8))
        _label(logo, "Galaxy", size="title_sm", weight="bold", bg=ORBIT["nav"], color=ORBIT["hero_text"]).pack(side="left")

        stage = tk.Frame(shell, bg=ORBIT["shell"], padx=18)
        stage.pack(side="left", fill="both", expand=True)
        header = tk.Frame(stage, bg=ORBIT["shell"])
        header.pack(fill="x", pady=(8, 9))
        _label(header, "工作区  /  下载", size="body_sm", weight="bold", bg=ORBIT["shell"], color=ui.MUTED).pack(side="left")
        window.folder_button = button(header, "下载目录", window.open_folder, icon="library")
        window.folder_button.pack(side="right")
        # Existing extensions still register the same actions. Orbit routes them
        # through the navigation/menu instead of packing them into the title bar.
        header_actions = tk.Frame(stage)
        window._copy_diag_button = ui.ActionButton(header_actions, text="复制诊断", command=lambda: ui._copy_diagnostics(window, engine_module), kind="ghost", compact=True)
        window._copy_diag_button.pack()

        statusbar = tk.Frame(stage, bg=ORBIT["shell"])
        statusbar.pack(fill="x", side="bottom", pady=(7, 9))
        _label(statusbar, f"本机引擎  ·  v{engine_module.VERSION}", size="caption", bg=ORBIT["shell"], color=ui.MUTED).pack(side="left")
        _label(statusbar, "文件保存在此设备", size="caption", bg=ORBIT["shell"], color=ui.SUBTLE).pack(side="right")

        body = tk.Frame(stage, bg=ORBIT["shell"])
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0, minsize=270)
        body.grid_rowconfigure(0, weight=1)
        _, main = _scrollable_workbench(body, window)
        rail_outer, rail = _scrollable_workbench(body, window, column=1)
        window._orbit_main = main
        window._orbit_hero = _hero(main)

        current = _card(main, padx=16, pady=12)
        current.pack(fill="x", pady=(0, 14))
        current_head = tk.Frame(current, bg=ui.PANEL)
        current_head.pack(fill="x")
        _label(current_head, "当前传输", size="title_sm", weight="bold").pack(side="left")
        window._queue_summary_var = tk.StringVar(value="等待 0 项")
        _label(current_head, variable=window._queue_summary_var, size="caption", color=ui.MUTED).pack(side="right")
        transfer_state = tk.StringVar()
        def sync_status(*_args):
            status = window.status_var.get()
            transfer_state.set("等待下载" if status == "Ready" else status)
        window.status_var.trace_add("write", sync_status)
        sync_status()
        _label(current, variable=transfer_state, size="body_sm", color=ui.MUTED).pack(anchor="w", pady=(6, 5))
        detail_text = tk.StringVar()
        def sync_detail(*_args):
            value = window.detail_var.get()
            detail_text.set("解析链接后可在此查看传输进度。" if value == "Waiting for a download job" else value)
        window.detail_var.trace_add("write", sync_detail)
        sync_detail()
        _text_wrap(_label(current, variable=detail_text, size="caption", color=ui.SUBTLE, justify="left"), current, inset=34).pack(anchor="w", pady=(0, 9))
        meter = ProgressMeter(current, window.percent_var, window._orbit_reduced)
        meter.pack(fill="x")
        window._orbit_meter = meter
        window._percent_text_var = tk.StringVar(value="0%")
        metrics = tk.Frame(current, bg=ui.PANEL)
        metrics.pack(fill="x", pady=(8, 0))
        for index, (name, value) in enumerate((("速度", window.speed_var), ("剩余", window.eta_var), ("已下载", window.size_var), ("进度", window._percent_text_var))):
            metrics.grid_columnconfigure(index, weight=1, uniform="metrics")
            cell = tk.Frame(metrics, bg=ui.PANEL)
            cell.grid(row=0, column=index, sticky="ew", padx=(0, 5))
            _label(cell, name, size="caption", color=ui.SUBTLE).pack(anchor="w")
            _label(cell, variable=value, size="body_sm", weight="bold").pack(anchor="w", pady=(2, 0))
        actions = tk.Frame(current, bg=ui.PANEL)
        actions.pack(fill="x", pady=(6, 0))
        window.cancel_button = button(actions, "取消任务", window.cancel, kind="Danger")
        window.cancel_button.pack(side="left")
        window.cancel_button.state(["disabled"])

        advanced = _card(main, padx=12, pady=5)
        advanced.pack(fill="x", pady=(0, 14))
        window._orbit_advanced_container = advanced
        window._advanced_open = False
        window._advanced_toggle_var = tk.StringVar(value="高级下载设置  ›")
        window._advanced_summary_var = tk.StringVar(value="片段、字幕、音轨与加速")
        advanced_head = tk.Frame(advanced, bg=ui.PANEL)
        advanced_head.pack(fill="x")
        window._orbit_advanced_button = button(advanced_head, "", lambda: ui._toggle_advanced(window), kind="Quiet", textvariable=window._advanced_toggle_var)
        window._orbit_advanced_button.pack(side="left")
        _label(advanced_head, variable=window._advanced_summary_var, size="caption", color=ui.SUBTLE).pack(side="right")
        window._advanced_panel = tk.Frame(advanced, bg=ui.PANEL_2, padx=10, pady=10)
        ui._build_advanced_panel(window, engine_module)
        window._orbit_clipboard_slot = tk.Frame(window._advanced_panel, bg=ui.PANEL_2)
        window._orbit_clipboard_slot.pack(fill="x")

        queue_card = _card(rail, padx=13, pady=13)
        queue_card.pack(fill="x", pady=(0, 14))
        _label(queue_card, "下载队列", size="title_sm", weight="bold").pack(anchor="w")
        window._queue_count_var = tk.StringVar(value="当前 0 · 等待 0")
        _label(queue_card, variable=window._queue_count_var, size="caption", color=ui.MUTED).pack(anchor="w", pady=(3, 8))
        window._queue_panel = tk.Frame(queue_card, bg=ui.PANEL)
        window._queue_panel.pack(fill="x")
        queue_head = tk.Frame(queue_card, bg=ui.PANEL)
        queue_head.pack(fill="x", pady=(7, 0))
        window._queue_clear_button = button(queue_head, "清空", lambda: ui._clear_queue_from_ui(window), kind="Quiet")
        window._queue_clear_button.pack(side="right")
        window._queue_clear_button.state(["disabled"])

        runtime = _card(rail, padx=13, pady=13)
        runtime.pack(fill="x")
        _label(runtime, "引擎组件", size="title_sm", weight="bold").pack(anchor="w", pady=(0, 4))
        ffmpeg = engine_module.ffmpeg_dir() is not None
        external = engine_module.external_ytdlp_path(engine_module.app_dir()) is not None
        bundled = importlib.util.find_spec("yt_dlp") is not None
        _system_row(runtime, "FFmpeg", "已就绪" if ffmpeg else "待配置", ui.SUCCESS if ffmpeg else ui.WARNING)
        _system_row(runtime, "yt-dlp", "已就绪" if external else "内置" if bundled else "待配置", ui.SUCCESS if external or bundled else ui.WARNING)
        _system_row(runtime, "aria2", "已就绪" if aria2c_available(engine_module) else "可选", ui.SUBTLE)
        window._latest_var = tk.StringVar(value=f"界面 {NATIVE_UI_REVISION}")
        _label(runtime, variable=window._latest_var, size="caption", color=ui.SUBTLE).pack(anchor="w", pady=(8, 3))
        window._update_button = button(runtime, "检查更新", lambda: ui._check_update(window, engine_module), kind="Quiet")
        window._update_button.pack(anchor="w")

        run_after_build_ui_hooks(window)
        for child in queue_head.winfo_children():
            child.pack_forget()
        pause = getattr(window, "_queue_pause_button", None)
        if pause is not None:
            pause.pack(side="left")
        window._queue_clear_button.pack(side="right")
        _make_nav(window, sidebar)

        def submit_link(_event):
            target = window._original_images_button if window._orbit_tabs.index else window._quick_parse_button
            target.invoke()
            return "break"
        window._quick_url_entry.bind("<Return>", submit_link)

        def responsive(event):
            wide = event.width >= 770
            if wide and not rail_outer.winfo_manager():
                body.grid_columnconfigure(1, minsize=270)
                rail_outer.grid()
            elif not wide and rail_outer.winfo_manager():
                rail_outer.grid_remove()
                body.grid_columnconfigure(1, minsize=0)
        body.bind("<Configure>", responsive, add="+")

        def reduce_changed(*_args):
            if window._orbit_reduced():
                window._orbit_tabs.tween.finish()
                meter.tween.finish()
        window._orbit_reduce_motion.trace_add("write", reduce_changed)
        window._galaxy_ui_tick()
        window._galaxy_queue_tick()

    window_cls._build_ui = build_ui
    window_cls._galaxy_native_v17_installed = True
    return window_cls


def run_native_desktop_v17_self_test():
    assert NATIVE_UI_REVISION == "1.8.0"
    assert TYPE["body"] >= 11 and TYPE["caption"] >= 9
    assert callable(install_native_desktop_v17)


if __name__ == "__main__":
    run_native_desktop_v17_self_test()
    print("Native Orbit workbench self-test passed")
