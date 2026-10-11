from __future__ import annotations

import tkinter as tk

import desktop_ui as ui
from bandwidth_policy import load_bandwidth_preference, normalize_bandwidth_kbps, save_bandwidth_preference
from desktop_hooks import register_after_build_ui_hook
from transfer_preferences import (
    load_aria2_connections_preference,
    save_aria2_connections_preference,
)


def _render_bandwidth_control(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_bandwidth_control_built", False):
        return

    card = tk.Frame(
        panel,
        bg=ui.PANEL_2,
        padx=0,
        pady=0,
    )
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))

    row = tk.Frame(card, bg=ui.PANEL_2)
    row.pack(fill="x")
    text = tk.Frame(row, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "带宽限制", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        text,
        "单位 KiB/s；0 表示不限速。统一限制媒体、Torrent / Magnet 与 aria2 HTTP 下载，不影响解析和本机处理。",
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(2, 0))

    variable = tk.StringVar(value=str(load_bandwidth_preference(engine_module)))
    window._bandwidth_limit_var = variable
    entry = tk.Entry(
        row,
        textvariable=variable,
        width=12,
        font=("Segoe UI", 8),
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
        justify="right",
    )
    entry.pack(side="right", padx=(10, 0))

    status = tk.StringVar(value="不限速" if load_bandwidth_preference(engine_module) == 0 else "已启用")
    window._bandwidth_status_var = status

    def save() -> None:
        limit = save_bandwidth_preference(engine_module, variable.get())
        variable.set(str(limit))
        status.set("不限速" if limit == 0 else f"{limit:,} KiB/s")

    def reset() -> None:
        variable.set("0")
        save()

    actions = tk.Frame(card, bg=ui.PANEL_2)
    actions.pack(fill="x", pady=(7, 0))
    ui._label(actions, variable=status, size=7, color=ui.MUTED, bg=ui.PANEL_2).pack(side="left")
    ui.ActionButton(actions, text="不限速", command=reset, kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(actions, text="保存限速", command=save, kind="secondary", compact=True).pack(side="right", padx=(0, 6))

    aria2_row = tk.Frame(card, bg=ui.PANEL_2)
    aria2_row.pack(fill="x", pady=(12, 0))
    aria2_text = tk.Frame(aria2_row, bg=ui.PANEL_2)
    aria2_text.pack(side="left", fill="x", expand=True)
    ui._label(aria2_text, "aria2 最大连接数", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        aria2_text,
        "范围 1–16；新建 Torrent / Magnet 与 aria2 HTTP 任务使用该值，恢复任务保留创建时设置。",
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(2, 0))

    aria2_variable = tk.StringVar(value=str(load_aria2_connections_preference(engine_module)))
    window._aria2_connections_var = aria2_variable
    aria2_entry = tk.Spinbox(
        aria2_row,
        from_=1,
        to=16,
        increment=1,
        textvariable=aria2_variable,
        width=6,
        font=("Segoe UI", 8),
        bg=ui.BG,
        fg=ui.TEXT,
        buttonbackground=ui.PANEL_3,
        insertbackground=ui.TEXT,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
        justify="right",
    )
    aria2_entry.pack(side="right", padx=(10, 0))

    aria2_status = tk.StringVar(value=f"{load_aria2_connections_preference(engine_module)} 个连接")
    window._aria2_connections_status_var = aria2_status

    def save_aria2() -> None:
        connections = save_aria2_connections_preference(engine_module, aria2_variable.get())
        aria2_variable.set(str(connections))
        aria2_status.set(f"{connections} 个连接")

    aria2_actions = tk.Frame(card, bg=ui.PANEL_2)
    aria2_actions.pack(fill="x", pady=(7, 0))
    ui._label(aria2_actions, variable=aria2_status, size=7, color=ui.MUTED, bg=ui.PANEL_2).pack(side="left")
    ui.ActionButton(aria2_actions, text="保存连接数", command=save_aria2, kind="secondary", compact=True).pack(side="right")

    window._galaxy_bandwidth_control_built = True


def install_desktop_bandwidth(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_bandwidth_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-bandwidth",
        lambda window: _render_bandwidth_control(window, engine_module),
        order=48,
    )
    window_cls._galaxy_desktop_bandwidth_installed = True
    return window_cls


def run_desktop_bandwidth_self_test() -> None:
    assert normalize_bandwidth_kbps("1024") == 1024
    assert normalize_bandwidth_kbps("-1") == 0
