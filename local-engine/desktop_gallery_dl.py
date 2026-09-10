from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook, show_desktop_presenter
from gallery_dl_executor import MAX_GALLERY_DL_FILES, install_gallery_dl_executor
from tool_manager import tool_inventory


def gallery_fallback_ready(inventory: object) -> bool:
    return bool(isinstance(inventory, dict) and inventory.get("galleryDlReady"))


def gallery_archive_ready(engine_module: object) -> bool:
    state_dir = getattr(engine_module, "state_dir", None)
    if not callable(state_dir):
        return False
    try:
        root = state_dir()
        if root is None or (isinstance(root, str) and not root.strip()):
            return False
        return Path(root).expanduser().is_absolute()
    except Exception:  # noqa: BLE001 - capability detection must fail closed
        return False


def gallery_archive_requested(window: object) -> bool:
    variable = getattr(window, "_gallery_dl_archive_var", None)
    if variable is None:
        return False
    try:
        return bool(variable.get())
    except tk.TclError:
        return False


def gallery_resume_requested(window: object) -> bool:
    """Capture the optional Resume toggle on the Tk/UI thread and fail closed."""
    variable = getattr(window, "_gallery_dl_resume_var", None)
    if variable is None:
        return False
    try:
        return bool(variable.get())
    except tk.TclError:
        return False


def gallery_date_values(window: object) -> tuple[str | None, str | None]:
    """Capture optional Date values on the Tk/UI thread and fail closed on Tcl errors."""
    after_var = getattr(window, "_gallery_dl_date_after_var", None)
    before_var = getattr(window, "_gallery_dl_date_before_var", None)
    try:
        after = str(after_var.get() if after_var is not None else "").strip()
        before = str(before_var.get() if before_var is not None else "").strip()
    except tk.TclError:
        return None, None
    return after or None, before or None


def _window_exists(window: tk.Misc | None) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def _set_submit_controls(window, *, disabled: bool) -> None:
    button = getattr(window, "_gallery_dl_fallback_button", None)
    if button is not None:
        button.state(["disabled" if disabled else "!disabled"])

    archive_check = getattr(window, "_gallery_dl_archive_check", None)
    if archive_check is not None:
        archive_supported = bool(getattr(window, "_gallery_dl_archive_supported", False))
        archive_disabled = disabled or not archive_supported
        try:
            archive_check.configure(
                state="disabled" if archive_disabled else "normal",
                cursor="arrow" if archive_disabled else "hand2",
            )
        except tk.TclError:
            return

    resume_check = getattr(window, "_gallery_dl_resume_check", None)
    if resume_check is not None:
        try:
            resume_check.configure(
                state="disabled" if disabled else "normal",
                cursor="arrow" if disabled else "hand2",
            )
        except tk.TclError:
            return

    for attribute in ("_gallery_dl_date_after_entry", "_gallery_dl_date_before_entry"):
        entry = getattr(window, attribute, None)
        if entry is None:
            continue
        try:
            entry.configure(
                state="disabled" if disabled else "normal",
                cursor="arrow" if disabled else "xterm",
            )
        except tk.TclError:
            return


def _submit_gallery_fallback(window, engine_module) -> None:
    source_var = getattr(window, "_quick_url_var", None)
    source = str(source_var.get() if source_var is not None else "").strip()
    state_var = getattr(window, "_quick_state_var", None)
    if not source:
        if state_var is not None:
            state_var.set("请先粘贴一个图片、图库或社交帖子链接。")
        return

    inventory = tool_inventory(engine_module, refresh=False)
    if not gallery_fallback_ready(inventory):
        if state_var is not None:
            state_var.set("gallery-dl 尚未安装。已打开工具管理；安装完成后再点击这里提交。")
        show_desktop_presenter(window, "tools")
        return

    archive_enabled = bool(getattr(window, "_gallery_dl_archive_supported", False)) and gallery_archive_requested(window)
    resume_enabled = gallery_resume_requested(window)
    date_after, date_before = gallery_date_values(window)
    date_filtered = bool(date_after or date_before)
    _set_submit_controls(window, disabled=True)
    if state_var is not None:
        state_var.set(
            "正在校验公网链接并提交 gallery-dl 任务…"
            + (" Archive 已启用。" if archive_enabled else "")
            + (" Resume 已启用。" if resume_enabled else "")
            + (" 日期过滤已启用。" if date_filtered else "")
        )

    def worker() -> None:
        try:
            validated = engine_module._validated_source_url(source)
            submit = getattr(window, "submit_gallery_dl_task", None)
            if not callable(submit):
                raise RuntimeError("gallery-dl 本机执行器未安装。")
            task_id = str(
                submit(
                    validated,
                    max_files=MAX_GALLERY_DL_FILES,
                    archive_enabled=bool(archive_enabled),
                    resume_enabled=bool(resume_enabled),
                    date_after=date_after,
                    date_before=date_before,
                )
                or ""
            )
            if not task_id:
                raise RuntimeError("gallery-dl 任务未返回任务 ID。")
            ok = True
            archive_detail = " · Archive 已启用" if archive_enabled else ""
            resume_detail = " · Resume 已启用" if resume_enabled else ""
            date_detail = " · 日期过滤已启用" if date_filtered else ""
            message = (
                f"已加入 gallery-dl 任务中心 · {task_id}{archive_detail}{resume_detail}{date_detail}"
                " · 可在任务中心取消或失败后重试。"
            )
        except Exception as exc:  # noqa: BLE001
            ok = False
            message = str(exc) or "gallery-dl 任务提交失败。"

        def finish() -> None:
            if not _window_exists(window):
                return
            _set_submit_controls(window, disabled=False)
            if state_var is not None:
                state_var.set((message if ok else f"gallery-dl 提交失败：{message}")[:280])

        try:
            window.after(0, finish)
        except tk.TclError:
            return

    threading.Thread(target=worker, name="GalaxyGalleryDlSubmit", daemon=True).start()


def _date_entry(master, *, label: str, variable: tk.StringVar) -> tuple[tk.Frame, tk.Entry]:
    field = tk.Frame(master, bg=ui.PANEL_2)
    ui._label(field, label, size=7, weight="bold", color=ui.MUTED, bg=ui.PANEL_2).pack(anchor="w", pady=(0, 3))
    target = tk.Frame(field, bg=ui.PANEL_3, height=44)
    target.pack(fill="x")
    target.pack_propagate(False)
    entry = tk.Entry(
        target,
        textvariable=variable,
        takefocus=True,
        font=("Segoe UI", 8),
        bg=ui.PANEL_3,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        disabledbackground=ui.PANEL_2,
        disabledforeground=ui.SUBTLE,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=ui.BORDER_SOFT,
        highlightcolor=ui.ACCENT,
        cursor="xterm",
    )
    entry.pack(fill="both", expand=True, padx=8)
    return field, entry


def _install_gallery_fallback(window, engine_module) -> None:
    panel = getattr(window, "_quick_download_panel", None)
    if panel is None or getattr(window, "_galaxy_gallery_dl_fallback_built", False):
        return

    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(11, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))

    row = tk.Frame(card, bg=ui.PANEL_2)
    row.pack(fill="x")
    text = tk.Frame(row, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "图片 / 图库 fallback", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        text,
        "常规解析没有合适媒体格式时，可显式交给托管 gallery-dl。不会读取用户 gallery-dl 配置；单任务最多 500 项。",
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
        wraplength=540,
        justify="left",
    ).pack(anchor="w", pady=(2, 0))

    button = ui.ActionButton(
        row,
        text="使用 gallery-dl",
        command=lambda: _submit_gallery_fallback(window, engine_module),
        kind="secondary",
    )
    button.pack(side="right", padx=(14, 0))
    window._gallery_dl_fallback_button = button

    archive_supported = gallery_archive_ready(engine_module)
    archive_row = tk.Frame(card, bg=ui.PANEL_2, height=44)
    archive_row.pack(fill="x", pady=(7, 0))
    archive_row.pack_propagate(False)
    archive_var = tk.BooleanVar(master=window, value=False)
    archive_check = tk.Checkbutton(
        archive_row,
        text="Archive · 跳过已记录项",
        variable=archive_var,
        onvalue=True,
        offvalue=False,
        state="normal" if archive_supported else "disabled",
        takefocus=True,
        anchor="w",
        bg=ui.PANEL_2,
        fg=ui.TEXT,
        activebackground=ui.PANEL_2,
        activeforeground=ui.TEXT,
        selectcolor=ui.PANEL_3,
        disabledforeground=ui.SUBTLE,
        font=("Segoe UI", 8, "bold"),
        bd=0,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER_SOFT,
        highlightcolor=ui.ACCENT,
        padx=4,
        pady=8,
        cursor="hand2" if archive_supported else "arrow",
    )
    archive_check.pack(side="left", fill="y")
    ui._label(
        archive_row,
        (
            "开启后由 Galaxy 状态目录维护记录；重试沿用同一 Archive，不暴露本机路径。"
            if archive_supported
            else "当前状态目录不可用，Archive 已禁用；普通 gallery-dl 下载不受影响。"
        ),
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
        wraplength=430,
        justify="left",
    ).pack(side="left", fill="x", expand=True, padx=(10, 0))

    resume_row = tk.Frame(card, bg=ui.PANEL_2, height=44)
    resume_row.pack(fill="x", pady=(7, 0))
    resume_row.pack_propagate(False)
    resume_var = tk.BooleanVar(master=window, value=False)
    resume_check = tk.Checkbutton(
        resume_row,
        text="Resume · 重试复用断点",
        variable=resume_var,
        onvalue=True,
        offvalue=False,
        takefocus=True,
        anchor="w",
        bg=ui.PANEL_2,
        fg=ui.TEXT,
        activebackground=ui.PANEL_2,
        activeforeground=ui.TEXT,
        selectcolor=ui.PANEL_3,
        disabledforeground=ui.SUBTLE,
        font=("Segoe UI", 8, "bold"),
        bd=0,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER_SOFT,
        highlightcolor=ui.ACCENT,
        padx=4,
        pady=8,
        cursor="hand2",
    )
    resume_check.pack(side="left", fill="y")
    ui._label(
        resume_row,
        "开启后失败/取消后的 Retry 复用同一托管目录和 .part；字节续传仅在远端支持 HTTP Range 时生效。",
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
        wraplength=430,
        justify="left",
    ).pack(side="left", fill="x", expand=True, padx=(10, 0))

    date_row = tk.Frame(card, bg=ui.PANEL_2)
    date_row.pack(fill="x", pady=(8, 0))
    date_after_var = tk.StringVar(master=window, value="")
    date_before_var = tk.StringVar(master=window, value="")
    date_after_field, date_after_entry = _date_entry(date_row, label="After", variable=date_after_var)
    date_after_field.pack(side="left", fill="x", expand=True)
    ui._label(date_row, "→", size=8, weight="bold", color=ui.SUBTLE, bg=ui.PANEL_2).pack(
        side="left", padx=8, pady=(18, 0)
    )
    date_before_field, date_before_entry = _date_entry(date_row, label="Before", variable=date_before_var)
    date_before_field.pack(side="left", fill="x", expand=True)
    ui._label(
        date_row,
        "可选日期过滤 · 建议 YYYY-MM-DD。由 gallery-dl 原生 date-after / date-before 校验和执行。",
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
        wraplength=280,
        justify="left",
    ).pack(side="left", fill="x", expand=True, padx=(12, 0), pady=(18, 0))

    window._gallery_dl_archive_supported = archive_supported
    window._gallery_dl_archive_var = archive_var
    window._gallery_dl_archive_check = archive_check
    window._gallery_dl_resume_var = resume_var
    window._gallery_dl_resume_check = resume_check
    window._gallery_dl_date_after_var = date_after_var
    window._gallery_dl_date_before_var = date_before_var
    window._gallery_dl_date_after_entry = date_after_entry
    window._gallery_dl_date_before_entry = date_before_entry
    window._galaxy_gallery_dl_fallback_built = True


def install_desktop_gallery_dl(engine_module):
    window_cls = engine_module.EngineWindow
    install_gallery_dl_executor(engine_module)
    if getattr(window_cls, "_galaxy_desktop_gallery_dl_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-gallery-dl",
        lambda window: _install_gallery_fallback(window, engine_module),
        order=47,
    )
    window_cls._galaxy_desktop_gallery_dl_installed = True
    return window_cls


def run_desktop_gallery_dl_self_test() -> None:
    class _EngineWithState:
        @staticmethod
        def state_dir() -> Path:
            return Path.cwd().resolve()

    class _EngineWithBrokenState:
        @staticmethod
        def state_dir():
            raise RuntimeError("broken state root")

    class _ArchiveVar:
        @staticmethod
        def get() -> bool:
            return True

    class _ResumeVar:
        @staticmethod
        def get() -> bool:
            return True

    class _DateVar:
        def __init__(self, value: str) -> None:
            self.value = value

        def get(self) -> str:
            return self.value

    class _Window:
        _gallery_dl_archive_var = _ArchiveVar()
        _gallery_dl_resume_var = _ResumeVar()
        _gallery_dl_date_after_var = _DateVar(" 2026-01-01 ")
        _gallery_dl_date_before_var = _DateVar("")

    assert gallery_fallback_ready({"galleryDlReady": True}) is True
    assert gallery_fallback_ready({"galleryDlReady": False}) is False
    assert gallery_fallback_ready(None) is False
    assert gallery_archive_ready(_EngineWithState()) is True
    assert gallery_archive_ready(_EngineWithBrokenState()) is False
    assert gallery_archive_ready(object()) is False
    assert gallery_archive_requested(_Window()) is True
    assert gallery_archive_requested(object()) is False
    assert gallery_resume_requested(_Window()) is True
    assert gallery_resume_requested(object()) is False
    assert gallery_date_values(_Window()) == ("2026-01-01", None)
    assert gallery_date_values(object()) == (None, None)
    assert MAX_GALLERY_DL_FILES == 500
