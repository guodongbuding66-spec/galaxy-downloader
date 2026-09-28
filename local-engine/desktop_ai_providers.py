from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

import desktop_ui as ui
from ai_provider_registry import (
    AiProviderConfigError,
    delete_ai_provider,
    provider_public_status,
    reset_ai_provider,
    save_ai_provider,
)
from ai_provider_runtime import test_provider_connection
from desktop_hooks import register_after_build_ui_hook

_PROTOCOLS = ("openai", "anthropic", "google", "azure-openai", "ollama")


def _window_exists(window: tk.Misc | None) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def _ready_label(row: dict[str, Any]) -> str:
    if not row.get("enabled"):
        return "Disabled"
    if row.get("allowLocal"):
        return "Local"
    if row.get("hasApiKey"):
        return "Ready"
    return "Credential missing"


def _test_label(result: dict[str, Any] | None) -> str:
    if not result:
        return "Not tested"
    if result.get("testing"):
        return "Testing…"
    code = str(result.get("code") or ("OK" if result.get("success") else "FAILED"))
    return f"Connected · {code}" if result.get("success") else code


def _show_provider_workspace(window, engine_module) -> None:
    existing = getattr(window, "_ai_provider_window", None)
    if _window_exists(existing):
        existing.deiconify()
        existing.lift()
        return

    dialog = tk.Toplevel(window)
    window._ai_provider_window = dialog
    dialog.title("AI Providers · Galaxy Local Engine")
    dialog.geometry("1080x700")
    dialog.minsize(920, 620)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "AI Providers", size="title", weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "管理模型端点、环境变量凭据引用与连接测试。API Key 只从 env:VARIABLE_NAME 读取，不在此窗口显示或保存明文。",
        size="body_sm",
        color=ui.MUTED,
        bg=ui.BG,
        wraplength=970,
        justify="left",
    ).pack(anchor="w", pady=(4, 10))

    status_var = tk.StringVar(value="正在读取 Provider 配置…")
    ui._label(shell, variable=status_var, size="body_sm", color=ui.MUTED, bg=ui.BG).pack(anchor="w", pady=(0, 10))

    body = tk.Frame(shell, bg=ui.BG)
    body.pack(fill="both", expand=True)

    list_card = tk.Frame(body, bg=ui.PANEL, padx=12, pady=12, highlightthickness=1, highlightbackground=ui.BORDER)
    list_card.pack(side="left", fill="both", expand=True)

    style = ttk.Style(dialog)
    style.configure(
        "Galaxy.AIProviders.Treeview",
        background=ui.PANEL,
        fieldbackground=ui.PANEL,
        foreground=ui.TEXT,
        rowheight=32,
        borderwidth=0,
    )
    style.configure(
        "Galaxy.AIProviders.Treeview.Heading",
        background=ui.PANEL_2,
        foreground=ui.MUTED,
        relief="flat",
        font=(ui.FONT_FAMILY, ui.TYPE["body_sm"], "bold"),
    )
    style.map(
        "Galaxy.AIProviders.Treeview",
        background=[("selected", ui.PANEL_3)],
        foreground=[("selected", ui.TEXT)],
    )

    columns = ("name", "protocol", "model", "ready", "test")
    tree = ttk.Treeview(
        list_card,
        columns=columns,
        show="headings",
        selectmode="browse",
        style="Galaxy.AIProviders.Treeview",
    )
    for key, label, width in (
        ("name", "Provider", 160),
        ("protocol", "Protocol", 110),
        ("model", "Model", 170),
        ("ready", "Config", 130),
        ("test", "Connection", 145),
    ):
        tree.heading(key, text=label)
        tree.column(key, width=width, minwidth=90, stretch=key in {"name", "model"})
    scroll = ttk.Scrollbar(list_card, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)

    editor = tk.Frame(body, bg=ui.PANEL, padx=14, pady=12, highlightthickness=1, highlightbackground=ui.BORDER)
    editor.pack(side="left", fill="y", padx=(12, 0))
    ui._label(editor, "Provider 配置", size="title_sm", weight="bold").grid(row=0, column=0, columnspan=2, sticky="w")

    provider_id_var = tk.StringVar()
    name_var = tk.StringVar()
    protocol_var = tk.StringVar(value="openai")
    model_var = tk.StringVar()
    base_url_var = tk.StringVar()
    credential_var = tk.StringVar()
    timeout_var = tk.StringVar(value="180")
    enabled_var = tk.BooleanVar(value=True)
    allow_local_var = tk.BooleanVar(value=False)

    fields: list[tuple[str, tk.Widget]] = []
    id_entry = ui._entry(editor, provider_id_var, 30)
    fields.append(("ID", id_entry))
    name_entry = ui._entry(editor, name_var, 30)
    fields.append(("Name", name_entry))
    protocol_box = ttk.Combobox(
        editor,
        textvariable=protocol_var,
        values=_PROTOCOLS,
        state="readonly",
        width=28,
        style="Galaxy.TCombobox",
    )
    fields.append(("Protocol", protocol_box))
    model_entry = ui._entry(editor, model_var, 30)
    fields.append(("Model", model_entry))
    base_url_entry = ui._entry(editor, base_url_var, 30)
    fields.append(("Base URL", base_url_entry))
    credential_entry = ui._entry(editor, credential_var, 30)
    fields.append(("Credential ref", credential_entry))
    timeout_box = ttk.Combobox(
        editor,
        textvariable=timeout_var,
        values=("30", "60", "120", "180", "300", "600"),
        state="readonly",
        width=28,
        style="Galaxy.TCombobox",
    )
    fields.append(("Timeout (s)", timeout_box))

    for index, (label, widget) in enumerate(fields, start=1):
        ui._label(editor, label, size="body_sm", color=ui.MUTED).grid(
            row=index,
            column=0,
            sticky="w",
            pady=(8 if index > 1 else 10, 0),
        )
        widget.grid(row=index, column=1, sticky="ew", padx=(10, 0), pady=(8 if index > 1 else 10, 0))

    checks = tk.Frame(editor, bg=ui.PANEL)
    checks.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 0))
    ui._check(checks, "Enabled", enabled_var).pack(side="left")
    ui._check(checks, "Allow local endpoint", allow_local_var).pack(side="left", padx=(12, 0))

    ui._label(
        editor,
        "凭据引用示例：env:OPENAI_API_KEY。Local endpoint 仅在显式勾选后允许 loopback HTTP。",
        size="caption",
        color=ui.SUBTLE,
        wraplength=340,
        justify="left",
    ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 0))

    editor.grid_columnconfigure(1, weight=1)

    rows: dict[str, dict[str, Any]] = {}
    tests: dict[str, dict[str, Any]] = {}
    edit_original_id = {"value": ""}
    testing = {"providerId": ""}

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))

    test_button = ui.ActionButton(footer, text="Test", command=lambda: run_test(), kind="secondary", compact=True)
    test_button.pack(side="left")
    refresh_button = ui.ActionButton(footer, text="Refresh", command=lambda: refresh(), kind="ghost", compact=True)
    refresh_button.pack(side="left", padx=(7, 0))
    new_button = ui.ActionButton(footer, text="New Provider", command=lambda: new_provider(), kind="ghost", compact=True)
    new_button.pack(side="left", padx=(7, 0))
    reset_delete_button = ui.ActionButton(footer, text="Reset", command=lambda: reset_or_delete(), kind="ghost", compact=True)
    reset_delete_button.pack(side="right")
    save_button = ui.ActionButton(footer, text="Save", command=lambda: save_provider(), kind="primary", compact=True)
    save_button.pack(side="right", padx=(0, 7))

    def selected() -> dict[str, Any] | None:
        selection = tree.selection()
        return rows.get(selection[0]) if selection else None

    def load_editor(row: dict[str, Any] | None) -> None:
        value = row or {}
        provider_id = str(value.get("id") or "")
        edit_original_id["value"] = provider_id
        provider_id_var.set(provider_id)
        name_var.set(str(value.get("name") or ""))
        protocol_var.set(str(value.get("protocol") or "openai"))
        model_var.set(str(value.get("model") or ""))
        base_url_var.set(str(value.get("baseUrl") or ""))
        credential_var.set(str(value.get("credentialReference") or ""))
        timeout_var.set(str(value.get("timeoutSeconds") or 180))
        enabled_var.set(bool(value.get("enabled", True)))
        allow_local_var.set(bool(value.get("allowLocal", False)))
        id_entry.configure(state="disabled" if provider_id else "normal")
        reset_delete_button.configure(text="Delete" if value.get("custom") else "Reset")
        if row is None:
            name_entry.focus_set()

    def sync_buttons() -> None:
        row = selected()
        busy = bool(testing["providerId"])
        test_button.state(["disabled"] if row is None or busy else ["!disabled"])
        reset_delete_button.state(["disabled"] if row is None else ["!disabled"])
        if row is not None:
            reset_delete_button.configure(text="Delete" if row.get("custom") else "Reset")

    def refresh(select_id: str = "") -> None:
        current = select_id or str((selected() or {}).get("id") or "")
        try:
            provider_rows = provider_public_status(engine_module)
        except Exception as exc:  # noqa: BLE001
            provider_rows = []
            status_var.set(f"Provider 读取失败：{exc}")

        for iid in tree.get_children():
            tree.delete(iid)
        rows.clear()
        for row in provider_rows:
            provider_id = str(row.get("id") or "")
            if not provider_id:
                continue
            rows[provider_id] = row
            tree.insert(
                "",
                "end",
                iid=provider_id,
                values=(
                    row.get("name") or provider_id,
                    row.get("protocol") or "—",
                    row.get("model") or "—",
                    _ready_label(row),
                    _test_label(tests.get(provider_id)),
                ),
            )
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
        if provider_rows and not testing["providerId"]:
            status_var.set(f"{len(provider_rows)} 个 Provider · API Key 明文不会显示")
        sync_buttons()

    def on_selection(_event=None) -> None:
        row = selected()
        if row is not None:
            load_editor(row)
        sync_buttons()

    def new_provider() -> None:
        tree.selection_remove(tree.selection())
        load_editor(None)
        status_var.set("新建 Custom Provider；ID 保存后不可修改。")
        sync_buttons()

    def save_provider() -> None:
        provider_id = edit_original_id["value"] or provider_id_var.get()
        try:
            saved = save_ai_provider(
                engine_module,
                provider_id=provider_id,
                name=name_var.get(),
                protocol=protocol_var.get(),
                base_url=base_url_var.get(),
                model=model_var.get(),
                enabled=enabled_var.get(),
                allow_local=allow_local_var.get(),
                timeout_seconds=timeout_var.get(),
                credential_reference=credential_var.get(),
            )
        except AiProviderConfigError as exc:
            status_var.set(f"保存失败：{exc}")
            return
        tests.pop(saved.id, None)
        status_var.set(f"已保存 {saved.name}")
        refresh(saved.id)

    def reset_or_delete() -> None:
        row = selected()
        if row is None:
            return
        provider_id = str(row.get("id") or "")
        try:
            if row.get("custom"):
                if not messagebox.askyesno(
                    engine_module.APP_NAME,
                    f"删除 Custom Provider “{row.get('name') or provider_id}”？",
                    parent=dialog,
                ):
                    return
                delete_ai_provider(engine_module, provider_id)
                tests.pop(provider_id, None)
                status_var.set(f"已删除 {provider_id}")
                refresh()
            else:
                reset_ai_provider(engine_module, provider_id)
                tests.pop(provider_id, None)
                status_var.set(f"已恢复 {provider_id} 默认配置")
                refresh(provider_id)
        except AiProviderConfigError as exc:
            status_var.set(f"操作失败：{exc}")

    def run_test() -> None:
        row = selected()
        if row is None or testing["providerId"]:
            return
        provider_id = str(row.get("id") or "")
        testing["providerId"] = provider_id
        tests[provider_id] = {"testing": True}
        status_var.set(f"正在测试 {row.get('name') or provider_id}…")
        refresh(provider_id)

        def worker() -> None:
            try:
                result = test_provider_connection(engine_module, provider_id)
            except Exception as exc:  # noqa: BLE001
                result = {"success": False, "code": "PROVIDER_ERROR", "detail": str(exc)[:300]}
            def finish() -> None:
                if not _window_exists(dialog):
                    return
                testing["providerId"] = ""
                tests[provider_id] = dict(result)
                detail = str(result.get("detail") or "")
                code = str(result.get("code") or "")
                status_var.set(
                    f"{'连接成功' if result.get('success') else '连接失败'} · {code}"
                    + (f" · {detail[:180]}" if detail else "")
                )
                refresh(provider_id)
            dialog.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    tree.bind("<<TreeviewSelect>>", on_selection)

    def close() -> None:
        window._ai_provider_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh()


def _add_provider_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_ai_provider_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "AI Providers", size="body_sm", weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        text,
        "OpenAI / Anthropic / Gemini / DeepSeek / OpenRouter / Groq / xAI / Ollama / LM Studio / Azure。",
        size="caption",
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(
        card,
        text="管理 Providers",
        command=lambda: _show_provider_workspace(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_ai_provider_entry_built = True


def install_desktop_ai_providers(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_ai_providers_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-ai-providers",
        lambda window: _add_provider_entry(window, engine_module),
        order=53,
    )
    window_cls._galaxy_desktop_ai_providers_installed = True
    return window_cls


def run_desktop_ai_providers_self_test() -> None:
    assert _PROTOCOLS == ("openai", "anthropic", "google", "azure-openai", "ollama")
    assert _ready_label({"enabled": False}) == "Disabled"
    assert _ready_label({"enabled": True, "allowLocal": True}) == "Local"
    assert _ready_label({"enabled": True, "hasApiKey": True}) == "Ready"
    assert _ready_label({"enabled": True}) == "Credential missing"
    assert _test_label({"success": True, "code": "OK"}) == "Connected · OK"
    assert _test_label({"success": False, "code": "AUTH"}) == "AUTH"
    assert _test_label({"testing": True}) == "Testing…"
