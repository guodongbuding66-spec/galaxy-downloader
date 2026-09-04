from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook
from plugin_marketplace import (
    DEFAULT_MARKETPLACE_URL,
    install_marketplace_plugin,
    load_marketplace,
    marketplace_status,
    refresh_marketplace,
    uninstall_plugin,
)


def _show_marketplace(window, engine_module) -> None:
    existing = getattr(window, "_plugin_marketplace_window", None)
    if existing is not None:
        try:
            existing.deiconify()
            existing.lift()
            return
        except tk.TclError:
            pass

    dialog = tk.Toplevel(window)
    window._plugin_marketplace_window = dialog
    dialog.title("插件市场 · Galaxy Local Engine")
    dialog.geometry("860x600")
    dialog.minsize(740, 500)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "插件市场", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "市场不会后台刷新。只有点击刷新/安装时才联网；安装包必须使用 HTTPS 并通过市场声明的 SHA-256 校验。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=790,
        justify="left",
    ).pack(anchor="w", pady=(4, 12))

    source_row = tk.Frame(shell, bg=ui.BG)
    source_row.pack(fill="x")
    source_var = tk.StringVar(value=DEFAULT_MARKETPLACE_URL)
    status_var = tk.StringVar(value="未刷新")
    tk.Entry(
        source_row,
        textvariable=source_var,
        font=("Segoe UI", 8),
        bg=ui.PANEL,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
    ).pack(side="left", fill="x", expand=True)

    card = tk.Frame(shell, bg=ui.PANEL, padx=14, pady=14, highlightthickness=1, highlightbackground=ui.BORDER)
    card.pack(fill="both", expand=True, pady=(12, 0))
    listbox = tk.Listbox(
        card,
        bg=ui.BG,
        fg=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        relief="flat",
        font=("Segoe UI", 9),
        height=16,
    )
    listbox.pack(fill="both", expand=True)
    rows: list[object] = []
    detail_var = tk.StringVar(value="市场缓存为空。")
    ui._label(card, variable=detail_var, size=8, color=ui.MUTED, wraplength=760, justify="left").pack(
        anchor="w", pady=(9, 0)
    )

    def selected():
        selection = listbox.curselection()
        return rows[selection[0]] if selection else None

    def refresh_view() -> None:
        rows[:] = list(load_marketplace(engine_module))
        state = marketplace_status(engine_module)
        installed = {str(item.get("id")): bool(item.get("installed")) for item in state.get("entries", [])}
        listbox.delete(0, "end")
        for item in rows:
            marker = "已安装" if installed.get(item.plugin_id) else "可安装"
            listbox.insert(
                "end",
                f"{item.name} · v{item.version} · {marker} · {', '.join(item.capabilities)}",
            )
        if rows:
            listbox.selection_set(0)
            show_detail()
        else:
            detail_var.set("市场缓存为空。点击“显式刷新市场”获取索引。")

    def show_detail(*_args) -> None:
        item = selected()
        if item is None:
            detail_var.set("未选择插件。")
            return
        platforms = ", ".join(item.platforms) or "未限制"
        description = item.description or "无描述"
        detail_var.set(
            f"{item.plugin_id} · 平台 {platforms} · SHA-256 {item.sha256[:16]}…\n{description}"
        )

    listbox.bind("<<ListboxSelect>>", show_detail)

    def explicit_refresh() -> None:
        source = source_var.get().strip() or DEFAULT_MARKETPLACE_URL
        status_var.set("正在显式刷新市场索引…")

        def worker() -> None:
            try:
                entries = refresh_marketplace(engine_module, source)
                message = f"市场已刷新：{len(entries)} 个插件"
            except Exception as exc:  # noqa: BLE001
                message = f"刷新失败：{exc}"
            dialog.after(0, lambda: status_var.set(message))
            dialog.after(0, refresh_view)

        threading.Thread(target=worker, daemon=True).start()

    def install_selected() -> None:
        item = selected()
        if item is None:
            return
        if not messagebox.askyesno(
            engine_module.APP_NAME,
            f"安装 {item.name} v{item.version}？\n\n安装包会校验 SHA-256，失败时保留现有插件。",
            parent=dialog,
        ):
            return
        status_var.set(f"正在安装 {item.name}…")

        def worker() -> None:
            try:
                installed = install_marketplace_plugin(engine_module, item.plugin_id)
                message = f"已安装 {installed.name} v{installed.version}"
            except Exception as exc:  # noqa: BLE001
                message = f"安装失败：{exc}"
            dialog.after(0, lambda: status_var.set(message))
            dialog.after(0, refresh_view)

        threading.Thread(target=worker, daemon=True).start()

    def uninstall_selected() -> None:
        item = selected()
        if item is None:
            return
        if not messagebox.askyesno(engine_module.APP_NAME, f"卸载插件 {item.name}？", parent=dialog):
            return
        try:
            removed = uninstall_plugin(engine_module, item.plugin_id)
            status_var.set("插件已卸载" if removed else "插件未安装")
        except Exception as exc:  # noqa: BLE001
            status_var.set(f"卸载失败：{exc}")
        refresh_view()

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    ui._label(footer, variable=status_var, size=8, color=ui.MUTED, bg=ui.BG).pack(side="left", fill="x", expand=True)
    ui.ActionButton(footer, text="卸载", command=uninstall_selected, kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(footer, text="安装选中", command=install_selected, kind="secondary", compact=True).pack(side="right", padx=(0, 6))
    ui.ActionButton(footer, text="显式刷新市场", command=explicit_refresh, kind="ghost", compact=True).pack(side="right", padx=(0, 6))

    def close() -> None:
        window._plugin_marketplace_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh_view()


def _add_marketplace_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_marketplace_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "插件市场", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        text,
        "HTTPS + SHA-256 校验 · 无后台自动安装",
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(
        card,
        text="打开插件市场",
        command=lambda: _show_marketplace(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_marketplace_entry_built = True


def install_desktop_marketplace(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_marketplace_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-plugin-marketplace",
        lambda window: _add_marketplace_entry(window, engine_module),
        order=58,
    )
    window_cls._galaxy_desktop_marketplace_installed = True
    return window_cls


def run_desktop_marketplace_self_test() -> None:
    assert DEFAULT_MARKETPLACE_URL.startswith("https://")
