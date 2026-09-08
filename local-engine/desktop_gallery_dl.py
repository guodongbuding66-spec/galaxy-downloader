from __future__ import annotations

import threading
import tkinter as tk

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook, show_desktop_presenter
from gallery_dl_executor import MAX_GALLERY_DL_FILES, install_gallery_dl_executor
from tool_manager import tool_inventory


def gallery_fallback_ready(inventory: object) -> bool:
    return bool(isinstance(inventory, dict) and inventory.get("galleryDlReady"))


def _window_exists(window: tk.Misc | None) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def _submit_gallery_fallback(window, engine_module) -> None:
    source_var = getattr(window, "_quick_url_var", None)
    source = str(source_var.get() if source_var is not None else "").strip()
    state_var = getattr(window, "_quick_state_var", None)
    button = getattr(window, "_gallery_dl_fallback_button", None)
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

    if button is not None:
        button.state(["disabled"])
    if state_var is not None:
        state_var.set("正在校验公网链接并提交 gallery-dl 任务…")

    def worker() -> None:
        try:
            validated = engine_module._validated_source_url(source)
            submit = getattr(window, "submit_gallery_dl_task", None)
            if not callable(submit):
                raise RuntimeError("gallery-dl 本机执行器未安装。")
            task_id = str(submit(validated, max_files=MAX_GALLERY_DL_FILES) or "")
            if not task_id:
                raise RuntimeError("gallery-dl 任务未返回任务 ID。")
            ok = True
            message = f"已加入 gallery-dl 任务中心 · {task_id} · 可在任务中心取消或失败后重试。"
        except Exception as exc:  # noqa: BLE001
            ok = False
            message = str(exc) or "gallery-dl 任务提交失败。"

        def finish() -> None:
            if not _window_exists(window):
                return
            if button is not None:
                button.state(["!disabled"])
            if state_var is not None:
                state_var.set((message if ok else f"gallery-dl 提交失败：{message}")[:280])

        try:
            window.after(0, finish)
        except tk.TclError:
            pass

    threading.Thread(target=worker, name="GalaxyGalleryDlSubmit", daemon=True).start()


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
    assert gallery_fallback_ready({"galleryDlReady": True}) is True
    assert gallery_fallback_ready({"galleryDlReady": False}) is False
    assert gallery_fallback_ready(None) is False
    assert MAX_GALLERY_DL_FILES == 500
