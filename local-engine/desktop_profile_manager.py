from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Mapping

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook
from download_profiles import (
    MAX_IMPORT_BYTES,
    DownloadProfileError,
    create_profile,
    delete_profile,
    duplicate_profile,
    export_profiles,
    import_profiles,
    list_profiles,
    resolve_profile,
    update_profile,
)

_AUTO_PROFILE_LABEL = "Auto match"
_CONTAINER_VALUES = ("", "mp4", "mkv", "webm")
_BROWSER_VALUES = ("none", "edge", "chrome", "firefox", "brave")
_POST_PROCESS_VALUES = ("", "none", "remux", "convert")


def _window_exists(window: tk.Misc | None) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def _split_patterns(value: object) -> list[str]:
    text = str(value or "")
    return [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]


def _settings_summary(settings: Mapping[str, Any] | None) -> str:
    value = dict(settings or {})
    parts = [str(value.get("video") or "best")]
    container = str(value.get("container") or "").strip()
    if container:
        parts.append(container.upper())
    browser = str(value.get("browser") or "none").strip()
    if browser and browser != "none":
        parts.append(browser.title())
    directory = str(value.get("directory") or "").strip()
    if directory:
        parts.append(directory)
    return " · ".join(parts)


def _merge_editable_settings(
    base_settings: Mapping[str, Any] | None,
    *,
    video: object,
    audio: object,
    container: object,
    subtitle: object,
    archive: bool,
    browser: object,
    directory: object,
    filename: object,
    rate_limit_mib: object,
    chapters: bool,
    sponsor_block: bool,
    post_process: object,
) -> dict[str, Any]:
    base = dict(base_settings or {})
    script = dict(base.get("script") or {})
    rate_text = str(rate_limit_mib or "").strip()
    return {
        "video": str(video or "").strip(),
        "audio": str(audio or "").strip(),
        "container": str(container or "").strip(),
        "subtitle": str(subtitle or "").strip(),
        "archive": bool(archive),
        "browser": str(browser or "").strip(),
        "directory": str(directory or "").strip(),
        "filename": str(filename or "").strip(),
        "rateLimitMiB": None if not rate_text else rate_text,
        "chapters": bool(chapters),
        "sponsorBlock": bool(sponsor_block),
        "postProcess": str(post_process or "").strip(),
        # Scripts are intentionally not editable or executable in this phase.
        # Preserve imported/core state exactly while the UI manages safe fields.
        "script": script,
    }


def preview_profile_match(engine_module, url: object, *, manual_profile_id: object | None = None) -> dict[str, Any]:
    manual = manual_profile_id not in {None, ""}
    profile = resolve_profile(engine_module, url, manual_profile_id=manual_profile_id if manual else None)
    if profile is None:
        return {"matched": False, "mode": "manual" if manual else "auto", "profileId": "", "profileName": ""}
    return {
        "matched": True,
        "mode": "manual" if manual else "auto",
        "profileId": str(profile.get("id") or ""),
        "profileName": str(profile.get("name") or ""),
        "settings": dict(profile.get("settings") or {}),
        "patterns": list(profile.get("patterns") or []),
    }


def _show_profile_workspace(window, engine_module) -> None:
    existing = getattr(window, "_download_profile_window", None)
    if _window_exists(existing):
        existing.deiconify()
        existing.lift()
        return

    dialog = tk.Toplevel(window)
    window._download_profile_window = dialog
    dialog.title("Download Profiles · Galaxy Local Engine")
    dialog.geometry("1180x780")
    dialog.minsize(1020, 680)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "Download Profiles", size="title", weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "集中管理下载预设与 URL Pattern。手动 Profile 始终优先于自动匹配；本阶段不会执行 Profile 中的脚本。",
        size="body_sm",
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=1060,
        justify="left",
    ).pack(anchor="w", pady=(4, 8))

    status_var = tk.StringVar(value="正在读取 Profiles…")
    ui._label(shell, variable=status_var, size="body_sm", color=ui.MUTED, bg=ui.BG).pack(anchor="w", pady=(0, 10))

    body = tk.PanedWindow(shell, orient="horizontal", bg=ui.BG, sashwidth=5, bd=0, relief="flat")
    body.pack(fill="both", expand=True)

    list_card = tk.Frame(body, bg=ui.PANEL, padx=12, pady=12, highlightthickness=1, highlightbackground=ui.BORDER)
    editor = tk.Frame(body, bg=ui.PANEL, padx=14, pady=12, highlightthickness=1, highlightbackground=ui.BORDER)
    body.add(list_card, minsize=430)
    body.add(editor, minsize=500)

    list_head = tk.Frame(list_card, bg=ui.PANEL)
    list_head.pack(fill="x")
    count_var = tk.StringVar(value="0 profiles")
    ui._label(list_head, "Profiles", size="title_sm", weight="bold").pack(side="left")
    ui._label(list_head, variable=count_var, size="body_sm", color=ui.MUTED).pack(side="left", padx=(10, 0))

    style = ttk.Style(dialog)
    style.configure(
        "Galaxy.DownloadProfiles.Treeview",
        background=ui.PANEL,
        fieldbackground=ui.PANEL,
        foreground=ui.TEXT,
        rowheight=31,
        borderwidth=0,
    )
    style.configure(
        "Galaxy.DownloadProfiles.Treeview.Heading",
        background=ui.PANEL_2,
        foreground=ui.MUTED,
        relief="flat",
        font=(ui.FONT_FAMILY, ui.TYPE["body_sm"], "bold"),
    )
    style.map(
        "Galaxy.DownloadProfiles.Treeview",
        background=[("selected", ui.PANEL_3)],
        foreground=[("selected", ui.TEXT)],
    )

    columns = ("name", "patterns", "settings")
    tree = ttk.Treeview(
        list_card,
        columns=columns,
        show="headings",
        selectmode="browse",
        style="Galaxy.DownloadProfiles.Treeview",
    )
    for key, label, width, stretch in (
        ("name", "Profile", 155, True),
        ("patterns", "Patterns", 80, False),
        ("settings", "Settings", 250, True),
    ):
        tree.heading(key, text=label)
        tree.column(key, width=width, minwidth=70, stretch=stretch)
    tree_scroll = ttk.Scrollbar(list_card, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=tree_scroll.set)
    tree_scroll.pack(side="right", fill="y", pady=(8, 0))
    tree.pack(fill="both", expand=True, pady=(8, 0))

    rows: dict[str, dict[str, Any]] = {}
    editing = {"id": ""}

    ui._label(editor, "Profile Editor", size="title_sm", weight="bold").grid(row=0, column=0, columnspan=4, sticky="w")

    name_var = tk.StringVar()
    video_var = tk.StringVar(value="best")
    audio_var = tk.StringVar(value="best")
    container_var = tk.StringVar()
    subtitle_var = tk.StringVar()
    browser_var = tk.StringVar(value="none")
    directory_var = tk.StringVar()
    filename_var = tk.StringVar()
    rate_var = tk.StringVar()
    post_process_var = tk.StringVar()
    archive_var = tk.BooleanVar(value=False)
    chapters_var = tk.BooleanVar(value=False)
    sponsor_var = tk.BooleanVar(value=False)

    def add_field(row_index: int, column: int, label: str, widget: tk.Widget) -> None:
        ui._label(editor, label, size="body_sm", color=ui.MUTED).grid(
            row=row_index, column=column, sticky="w", pady=(9, 0), padx=(0 if column == 0 else 12, 0)
        )
        widget.grid(row=row_index + 1, column=column, sticky="ew", pady=(3, 0), padx=(0 if column == 0 else 12, 0))

    name_entry = ui._entry(editor, name_var, 28)
    add_field(1, 0, "Name", name_entry)
    video_entry = ui._entry(editor, video_var, 22)
    add_field(1, 1, "Video", video_entry)
    audio_entry = ui._entry(editor, audio_var, 22)
    add_field(3, 0, "Audio", audio_entry)
    container_box = ttk.Combobox(editor, textvariable=container_var, values=_CONTAINER_VALUES, state="readonly", style="Galaxy.TCombobox")
    add_field(3, 1, "Container", container_box)
    subtitle_entry = ui._entry(editor, subtitle_var, 22)
    add_field(5, 0, "Subtitle", subtitle_entry)
    browser_box = ttk.Combobox(editor, textvariable=browser_var, values=_BROWSER_VALUES, state="readonly", style="Galaxy.TCombobox")
    add_field(5, 1, "Browser", browser_box)
    directory_entry = ui._entry(editor, directory_var, 22)
    add_field(7, 0, "Relative directory", directory_entry)
    filename_entry = ui._entry(editor, filename_var, 22)
    add_field(7, 1, "Filename template", filename_entry)
    rate_entry = ui._entry(editor, rate_var, 22)
    add_field(9, 0, "Rate limit (MiB/s)", rate_entry)
    post_box = ttk.Combobox(editor, textvariable=post_process_var, values=_POST_PROCESS_VALUES, state="readonly", style="Galaxy.TCombobox")
    add_field(9, 1, "Post process", post_box)

    flags = tk.Frame(editor, bg=ui.PANEL)
    flags.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(12, 0))
    ui._check(flags, "Archive", archive_var).pack(side="left")
    ui._check(flags, "Chapters", chapters_var).pack(side="left", padx=(12, 0))
    ui._check(flags, "SponsorBlock", sponsor_var).pack(side="left", padx=(12, 0))

    ui._label(editor, "URL Patterns · one pattern per line", size="body_sm", color=ui.MUTED).grid(
        row=12, column=0, columnspan=2, sticky="w", pady=(12, 0)
    )
    patterns_text = tk.Text(
        editor,
        height=5,
        wrap="none",
        bg=ui.PANEL_2,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        relief="flat",
        borderwidth=0,
        highlightthickness=ui.FOCUS_RING_WIDTH,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.FOCUS,
        padx=9,
        pady=7,
        font=(ui.FONT_FAMILY, ui.TYPE["body_sm"]),
        takefocus=True,
    )
    patterns_text.grid(row=13, column=0, columnspan=2, sticky="nsew", pady=(4, 0))

    ui._label(
        editor,
        "Script 配置仅由 core 保存并原样保留；本窗口不编辑、不运行 pre/post scripts。",
        size="caption",
        color=ui.SUBTLE,
        wraplength=560,
        justify="left",
    ).grid(row=14, column=0, columnspan=2, sticky="w", pady=(8, 0))

    preview = tk.Frame(editor, bg=ui.PANEL_2, padx=10, pady=10)
    preview.grid(row=15, column=0, columnspan=2, sticky="ew", pady=(12, 0))
    ui._label(preview, "URL Match Preview", size="body_sm", weight="bold", bg=ui.PANEL_2).grid(row=0, column=0, columnspan=3, sticky="w")
    preview_url_var = tk.StringVar()
    manual_var = tk.StringVar(value=_AUTO_PROFILE_LABEL)
    preview_result_var = tk.StringVar(value="输入 URL 后可预览自动/手动 Profile 解析结果。")
    preview_entry = ui._entry(preview, preview_url_var, 42)
    preview_entry.grid(row=1, column=0, sticky="ew", pady=(7, 0))
    manual_box = ttk.Combobox(preview, textvariable=manual_var, state="readonly", width=24, style="Galaxy.TCombobox")
    manual_box.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(7, 0))
    ui._label(preview, variable=preview_result_var, size="caption", color=ui.MUTED, bg=ui.PANEL_2, wraplength=520, justify="left").grid(
        row=2, column=0, columnspan=3, sticky="w", pady=(7, 0)
    )
    preview.grid_columnconfigure(0, weight=1)

    editor.grid_columnconfigure(0, weight=1)
    editor.grid_columnconfigure(1, weight=1)
    editor.grid_rowconfigure(13, weight=1)

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    ui.ActionButton(footer, text="Refresh", command=lambda: refresh(), kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(footer, text="New Profile", command=lambda: new_profile(), kind="ghost", compact=True).pack(side="left", padx=(7, 0))
    duplicate_button = ui.ActionButton(footer, text="Duplicate", command=lambda: duplicate_selected(), kind="ghost", compact=True)
    duplicate_button.pack(side="left", padx=(7, 0))
    import_button = ui.ActionButton(footer, text="Import JSON", command=lambda: import_json(), kind="ghost", compact=True)
    import_button.pack(side="left", padx=(7, 0))
    export_button = ui.ActionButton(footer, text="Export JSON", command=lambda: export_json(), kind="ghost", compact=True)
    export_button.pack(side="left", padx=(7, 0))
    delete_button = ui.ActionButton(footer, text="Delete", command=lambda: delete_selected(), kind="ghost", compact=True)
    delete_button.pack(side="right")
    save_button = ui.ActionButton(footer, text="Save Profile", command=lambda: save_profile(), kind="primary", compact=True)
    save_button.pack(side="right", padx=(0, 7))

    manual_ids: dict[str, str] = {_AUTO_PROFILE_LABEL: ""}

    def selected() -> dict[str, Any] | None:
        selection = tree.selection()
        return rows.get(selection[0]) if selection else None

    def set_patterns(patterns: list[str]) -> None:
        patterns_text.delete("1.0", "end")
        if patterns:
            patterns_text.insert("1.0", "\n".join(patterns))

    def load_editor(row: dict[str, Any] | None) -> None:
        value = row or {}
        settings = dict(value.get("settings") or {})
        editing["id"] = str(value.get("id") or "")
        name_var.set(str(value.get("name") or ""))
        video_var.set(str(settings.get("video") or "best"))
        audio_var.set(str(settings.get("audio") or "best"))
        container_var.set(str(settings.get("container") or ""))
        subtitle_var.set(str(settings.get("subtitle") or ""))
        browser_var.set(str(settings.get("browser") or "none"))
        directory_var.set(str(settings.get("directory") or ""))
        filename_var.set(str(settings.get("filename") or ""))
        rate = settings.get("rateLimitMiB")
        rate_var.set("" if rate is None else str(rate))
        post_process_var.set(str(settings.get("postProcess") or ""))
        archive_var.set(bool(settings.get("archive", False)))
        chapters_var.set(bool(settings.get("chapters", False)))
        sponsor_var.set(bool(settings.get("sponsorBlock", False)))
        set_patterns(list(value.get("patterns") or []))
        if row is None:
            name_entry.focus_set()

    def sync_actions() -> None:
        has_selection = selected() is not None
        duplicate_button.state(["!disabled"] if has_selection else ["disabled"])
        delete_button.state(["!disabled"] if has_selection else ["disabled"])

    def refresh(select_id: str = "") -> None:
        current = select_id or str((selected() or {}).get("id") or "")
        try:
            profile_rows = list_profiles(engine_module)
        except DownloadProfileError as exc:
            profile_rows = []
            status_var.set(f"读取失败：{exc}")
        for iid in tree.get_children():
            tree.delete(iid)
        rows.clear()
        manual_ids.clear()
        manual_ids[_AUTO_PROFILE_LABEL] = ""
        manual_labels = [_AUTO_PROFILE_LABEL]
        for row in profile_rows:
            profile_id = str(row.get("id") or "")
            if not profile_id:
                continue
            rows[profile_id] = row
            patterns = list(row.get("patterns") or [])
            tree.insert("", "end", iid=profile_id, values=(row.get("name") or profile_id, len(patterns), _settings_summary(row.get("settings"))))
            label = f"{row.get('name') or profile_id} · {profile_id[:8]}"
            manual_ids[label] = profile_id
            manual_labels.append(label)
        manual_box.configure(values=tuple(manual_labels))
        if manual_var.get() not in manual_ids:
            manual_var.set(_AUTO_PROFILE_LABEL)
        if current and current in rows:
            tree.selection_set(current)
            tree.see(current)
            load_editor(rows[current])
        elif tree.get_children():
            first = tree.get_children()[0]
            tree.selection_set(first)
            load_editor(rows[first])
        else:
            load_editor(None)
        count_var.set(f"{len(profile_rows)} profiles")
        if profile_rows:
            status_var.set(f"{len(profile_rows)} 个 Profile · URL Pattern 自动匹配已启用")
        else:
            status_var.set("暂无 Profile；可新建或导入 JSON。")
        sync_actions()

    def on_selection(_event=None) -> None:
        row = selected()
        if row is not None:
            load_editor(row)
        sync_actions()

    def new_profile() -> None:
        tree.selection_remove(*tree.selection())
        load_editor(None)
        status_var.set("新建 Profile；保存前不会修改现有下载设置。")
        sync_actions()

    def editor_settings() -> dict[str, Any]:
        current = rows.get(editing["id"], {})
        return _merge_editable_settings(
            current.get("settings"),
            video=video_var.get(),
            audio=audio_var.get(),
            container=container_var.get(),
            subtitle=subtitle_var.get(),
            archive=archive_var.get(),
            browser=browser_var.get(),
            directory=directory_var.get(),
            filename=filename_var.get(),
            rate_limit_mib=rate_var.get(),
            chapters=chapters_var.get(),
            sponsor_block=sponsor_var.get(),
            post_process=post_process_var.get(),
        )

    def save_profile() -> None:
        try:
            patterns = _split_patterns(patterns_text.get("1.0", "end-1c"))
            settings = editor_settings()
            if editing["id"]:
                saved = update_profile(engine_module, editing["id"], name=name_var.get(), settings=settings, patterns=patterns)
            else:
                saved = create_profile(engine_module, name_var.get(), settings=settings, patterns=patterns)
        except DownloadProfileError as exc:
            status_var.set(f"保存失败：{exc}")
            return
        refresh(str(saved.get("id") or ""))
        status_var.set(f"已保存 {saved.get('name') or 'Profile'}")

    def duplicate_selected() -> None:
        row = selected()
        if row is None:
            return
        try:
            copied = duplicate_profile(engine_module, row["id"])
        except DownloadProfileError as exc:
            status_var.set(f"复制失败：{exc}")
            return
        refresh(str(copied.get("id") or ""))
        status_var.set(f"已复制为 {copied.get('name')}")

    def delete_selected() -> None:
        row = selected()
        if row is None:
            return
        if not messagebox.askyesno(engine_module.APP_NAME, f"删除 Profile “{row.get('name') or row.get('id')}”？", parent=dialog):
            return
        try:
            delete_profile(engine_module, row["id"])
        except DownloadProfileError as exc:
            status_var.set(f"删除失败：{exc}")
            return
        refresh()
        status_var.set("Profile 已删除")

    def export_json() -> None:
        path = filedialog.asksaveasfilename(
            parent=dialog,
            title="Export Download Profiles",
            defaultextension=".json",
            filetypes=(("JSON", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            content = export_profiles(engine_module)
            Path(path).write_text(content, encoding="utf-8")
        except (DownloadProfileError, OSError) as exc:
            status_var.set(f"导出失败：{exc}")
            return
        status_var.set(f"已导出到 {Path(path).name}")

    def import_json() -> None:
        path = filedialog.askopenfilename(
            parent=dialog,
            title="Import Download Profiles",
            filetypes=(("JSON", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return
        replace = messagebox.askyesno(
            engine_module.APP_NAME,
            "是否用导入文件替换全部现有 Profiles？\n选择“否”将合并导入并自动处理 ID 冲突。",
            parent=dialog,
        )
        try:
            source_path = Path(path)
            with source_path.open("rb") as handle:
                content = handle.read(MAX_IMPORT_BYTES + 1)
            if len(content) > MAX_IMPORT_BYTES:
                raise DownloadProfileError("profile import payload size is invalid")
            imported = import_profiles(engine_module, content, replace=replace)
        except (DownloadProfileError, OSError) as exc:
            status_var.set(f"导入失败：{exc}")
            return
        refresh()
        status_var.set(f"导入完成 · 当前 {len(imported)} 个 Profile")

    def run_preview() -> None:
        manual_id = manual_ids.get(manual_var.get(), "")
        try:
            result = preview_profile_match(engine_module, preview_url_var.get(), manual_profile_id=manual_id or None)
        except DownloadProfileError as exc:
            preview_result_var.set(f"匹配失败：{exc}")
            return
        if not result["matched"]:
            preview_result_var.set("Auto match · 未匹配任何 Profile")
            return
        mode = "Manual override" if result["mode"] == "manual" else "Auto match"
        preview_result_var.set(f"{mode} · {result['profileName']} · {_settings_summary(result.get('settings'))}")

    ui.ActionButton(preview, text="Preview", command=run_preview, kind="secondary", compact=True).grid(
        row=1, column=2, padx=(8, 0), pady=(7, 0)
    )
    tree.bind("<<TreeviewSelect>>", on_selection)

    def close() -> None:
        window._download_profile_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh()


def _add_profile_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_download_profile_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "Download Profiles", size="body_sm", weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        text,
        "预设、URL Pattern、手动覆盖、导入/导出与匹配预览。",
        size="caption",
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(
        card,
        text="管理 Profiles",
        command=lambda: _show_profile_workspace(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_download_profile_entry_built = True


def install_desktop_profile_manager(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_profile_manager_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-profile-manager",
        lambda window: _add_profile_entry(window, engine_module),
        order=58,
    )
    window_cls._galaxy_desktop_profile_manager_installed = True
    return window_cls


def run_desktop_profile_manager_self_test() -> None:
    assert _split_patterns("youtube.com/*\n\n*.youtube.com/*") == ["youtube.com/*", "*.youtube.com/*"]
    assert _settings_summary({"video": "2160p", "container": "mkv", "browser": "chrome"}) == "2160p · MKV · Chrome"
    merged = _merge_editable_settings(
        {"script": {"enabled": False, "postDownload": "echo preserved"}},
        video="best",
        audio="best",
        container="mp4",
        subtitle="",
        archive=True,
        browser="none",
        directory="Video",
        filename="",
        rate_limit_mib="12.5",
        chapters=True,
        sponsor_block=False,
        post_process="remux",
    )
    assert merged["script"]["postDownload"] == "echo preserved"
    assert merged["rateLimitMiB"] == "12.5"
