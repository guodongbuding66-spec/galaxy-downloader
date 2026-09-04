from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook
from headless_asr_api import HeadlessAsrApiError
from headless_sensevoice_asr_api import SenseVoiceHeadlessAsrApi

_PROVIDERS = ("auto", "whisper", "faster-whisper", "sensevoice")
_PROFILES = ("fast", "balanced", "accurate")
_LEGACY_DEVICES = ("auto", "cpu", "cuda")
_SENSEVOICE_DEVICES = ("auto", "cpu", "mps", "cuda")
_DEVICES = _SENSEVOICE_DEVICES
_COMPUTE = ("default", "int8", "int8_float16", "float16", "float32")
_COMPUTE_PROVIDERS = {"auto", "faster-whisper"}


def _api(engine_module) -> SenseVoiceHeadlessAsrApi:
    return SenseVoiceHeadlessAsrApi(engine_module.default_download_dir())


def _provider_controls(
    provider: object,
    device: object,
    compute: object,
) -> tuple[tuple[str, ...], str, str, bool]:
    selected = str(provider or "auto").strip().lower()
    if selected not in _PROVIDERS:
        selected = "auto"

    devices = _SENSEVOICE_DEVICES if selected == "sensevoice" else _LEGACY_DEVICES
    selected_device = str(device or "auto").strip().lower()
    if selected_device not in devices:
        selected_device = "auto"

    compute_enabled = selected in _COMPUTE_PROVIDERS
    selected_compute = str(compute or "default").strip().lower()
    if selected_compute not in _COMPUTE or not compute_enabled:
        selected_compute = "default"
    return devices, selected_device, selected_compute, compute_enabled


def _show_asr_workspace(window, engine_module) -> None:
    existing = getattr(window, "_asr_workspace_window", None)
    if existing is not None:
        try:
            existing.deiconify(); existing.lift(); return
        except tk.TclError:
            pass

    dialog = tk.Toplevel(window)
    window._asr_workspace_window = dialog
    dialog.title("ASR 与模型 · Galaxy Local Engine")
    dialog.geometry("900x660")
    dialog.minsize(800, 560)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=18, pady=16)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "ASR 与模型", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "Whisper / faster-whisper / SenseVoice 路由、偏好和模型生命周期。模型只在你点击安装时下载。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(3, 12))

    api = _api(engine_module)
    provider_var = tk.StringVar(value="auto")
    profile_var = tk.StringVar(value="balanced")
    model_var = tk.StringVar(value="")
    language_var = tk.StringVar(value="")
    device_var = tk.StringVar(value="auto")
    compute_var = tk.StringVar(value="default")
    status_var = tk.StringVar(value="检测中…")

    settings = tk.Frame(
        shell,
        bg=ui.PANEL,
        padx=14,
        pady=12,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    settings.pack(fill="x")

    controls: dict[str, ttk.Combobox] = {}
    fields = (
        ("Provider", "provider", provider_var, _PROVIDERS),
        ("Profile", "profile", profile_var, _PROFILES),
        ("Device", "device", device_var, _DEVICES),
        ("Compute", "compute", compute_var, _COMPUTE),
    )
    for index, (label, key, variable, values) in enumerate(fields):
        ui._label(settings, label, size=7, color=ui.MUTED).grid(
            row=0,
            column=index,
            sticky="w",
            padx=(0 if index == 0 else 10, 0),
        )
        box = ttk.Combobox(
            settings,
            textvariable=variable,
            values=values,
            state="readonly",
            width=16,
            style="Galaxy.TCombobox",
        )
        box.grid(
            row=1,
            column=index,
            sticky="ew",
            padx=(0 if index == 0 else 10, 0),
            pady=(4, 0),
        )
        controls[key] = box
        settings.grid_columnconfigure(index, weight=1)

    lower = tk.Frame(settings, bg=ui.PANEL)
    lower.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))
    ui._label(lower, "Model", size=7, color=ui.MUTED).pack(side="left")
    tk.Entry(
        lower,
        textvariable=model_var,
        width=18,
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    ).pack(side="left", padx=(6, 12))
    ui._label(lower, "Language", size=7, color=ui.MUTED).pack(side="left")
    tk.Entry(
        lower,
        textvariable=language_var,
        width=10,
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    ).pack(side="left", padx=(6, 12))
    ui._label(lower, variable=status_var, size=7, color=ui.CYAN, bg=ui.PANEL).pack(
        side="left", fill="x", expand=True
    )

    model_card = tk.Frame(
        shell,
        bg=ui.PANEL,
        padx=14,
        pady=12,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    model_card.pack(fill="both", expand=True, pady=(12, 0))
    ui._label(model_card, "模型状态", size=9, weight="bold").pack(anchor="w")
    model_list = tk.Listbox(
        model_card,
        bg=ui.BG,
        fg=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        font=("Segoe UI", 9),
    )
    model_list.pack(fill="both", expand=True, pady=(8, 0))
    rows: list[dict] = []

    def sync_provider_controls(*, clear_incompatible_model: bool = False) -> None:
        previous_model = model_var.get().strip().lower()
        devices, device, compute, compute_enabled = _provider_controls(
            provider_var.get(),
            device_var.get(),
            compute_var.get(),
        )
        controls["device"].configure(values=devices)
        device_var.set(device)
        compute_var.set(compute)
        controls["compute"].configure(state="readonly" if compute_enabled else "disabled")
        if clear_incompatible_model and provider_var.get() == "sensevoice" and previous_model not in {"", "small"}:
            model_var.set("")

    def on_provider_changed(_event=None) -> None:
        sync_provider_controls(clear_incompatible_model=True)
        try:
            recommendation = api.recommend(
                {"provider": provider_var.get(), "profile": profile_var.get()}
            ).get("recommendation", {})
            status_var.set(
                f"推荐：{recommendation.get('provider','-')} / {recommendation.get('model','-')}"
            )
        except Exception as exc:
            status_var.set(f"失败：{exc}")

    controls["provider"].bind("<<ComboboxSelected>>", on_provider_changed)

    def refresh() -> None:
        try:
            pref = api.preferences()
            saved = pref.get("settings", {})
            provider_var.set(str(saved.get("provider") or "auto"))
            profile_var.set(str(saved.get("profile") or "balanced"))
            model_var.set(str(saved.get("model") or ""))
            language_var.set(str(saved.get("language") or ""))
            device_var.set(str(saved.get("device") or "auto") or "auto")
            compute_var.set(str(saved.get("computeType") or "default") or "default")
            sync_provider_controls()
            data = api.models()
            rows[:] = list(data.get("models", []))
            model_list.delete(0, "end")
            for row in rows:
                state = "已安装" if row.get("installed") else "未安装"
                model_list.insert(
                    "end",
                    f"{row.get('provider')} · {row.get('model')} · {state}",
                )
            recommendation = api.recommend(
                {"provider": provider_var.get(), "profile": profile_var.get()}
            ).get("recommendation", {})
            status_var.set(
                f"推荐：{recommendation.get('provider','-')} / {recommendation.get('model','-')}"
            )
        except Exception as exc:
            status_var.set(f"失败：{exc}")

    def save() -> None:
        try:
            sync_provider_controls(clear_incompatible_model=True)
            result = api.save_preferences(
                {
                    "provider": provider_var.get(),
                    "profile": profile_var.get(),
                    "model": model_var.get(),
                    "language": language_var.get(),
                    "device": device_var.get(),
                    "computeType": compute_var.get(),
                }
            )
            recommendation = result.get("recommendation", {})
            status_var.set(
                f"已保存 · 推荐 {recommendation.get('provider','-')} / {recommendation.get('model','-')}"
            )
        except HeadlessAsrApiError as exc:
            status_var.set(f"失败：{exc}")

    def selected_model() -> tuple[str, str] | None:
        selection = model_list.curselection()
        if not selection:
            return None
        row = rows[selection[0]]
        return str(row.get("provider") or ""), str(row.get("model") or "")

    def model_action(action: str) -> None:
        selected = selected_model()
        if not selected:
            messagebox.showinfo(engine_module.APP_NAME, "请选择模型。", parent=dialog)
            return
        provider, model = selected
        status_var.set(f"正在{('安装' if action == 'install' else '删除')} {provider}/{model}…")

        def worker() -> None:
            try:
                result = (
                    api.install_model(provider, model)
                    if action == "install"
                    else api.remove_model(provider, model)
                )
                operation = result.get("operation", {})
                message = str(
                    operation.get("detail")
                    or ("完成" if operation.get("success") else "失败")
                )
            except Exception as exc:
                message = f"失败：{exc}"
            dialog.after(0, lambda: status_var.set(message))
            dialog.after(0, refresh)

        threading.Thread(target=worker, daemon=True).start()

    actions = tk.Frame(shell, bg=ui.BG)
    actions.pack(fill="x", pady=(12, 0))
    ui.ActionButton(actions, text="刷新", command=refresh, kind="ghost", compact=True).pack(
        side="left"
    )
    ui.ActionButton(
        actions,
        text="保存偏好",
        command=save,
        kind="secondary",
        compact=True,
    ).pack(side="left", padx=(6, 0))
    ui.ActionButton(
        actions,
        text="删除模型",
        command=lambda: model_action("delete"),
        kind="ghost",
        compact=True,
    ).pack(side="right")
    ui.ActionButton(
        actions,
        text="显式安装模型",
        command=lambda: model_action("install"),
        kind="secondary",
        compact=True,
    ).pack(side="right", padx=(0, 6))

    def close() -> None:
        window._asr_workspace_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh()


def _add_asr_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_asr_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "ASR / 模型管理", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        text,
        "Whisper + faster-whisper + SenseVoice；自动硬件推荐，模型下载始终需要显式触发。",
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(
        card,
        text="打开 ASR",
        command=lambda: _show_asr_workspace(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_asr_entry_built = True


def install_desktop_asr(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_asr_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-asr",
        lambda window: _add_asr_entry(window, engine_module),
        order=53,
    )
    window_cls._galaxy_desktop_asr_installed = True
    return window_cls


def run_desktop_asr_self_test() -> None:
    assert _PROVIDERS == ("auto", "whisper", "faster-whisper", "sensevoice")
    assert "mps" in _DEVICES and "cuda" in _DEVICES

    devices, device, compute, enabled = _provider_controls("sensevoice", "mps", "int8")
    assert devices == _SENSEVOICE_DEVICES
    assert device == "mps"
    assert compute == "default" and enabled is False

    devices, device, compute, enabled = _provider_controls("faster-whisper", "mps", "float16")
    assert devices == _LEGACY_DEVICES
    assert device == "auto"
    assert compute == "float16" and enabled is True

    devices, device, compute, enabled = _provider_controls("whisper", "cuda", "int8")
    assert device == "cuda"
    assert compute == "default" and enabled is False
