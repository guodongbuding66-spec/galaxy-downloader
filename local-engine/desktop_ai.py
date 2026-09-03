from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import desktop_ui as ui
from ai_models import (
    WHISPER_MODELS,
    ai_model_status,
    load_ai_model_settings,
    pull_ollama_model,
    save_ai_model_settings,
)
from ai_workspace import AiWorkspaceError, summary_path, summarize_media, transcript_path, transcribe_media
from desktop_hooks import register_after_build_ui_hook
from media_library import list_media_items, sync_media_library


def _open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _show_ai_workspace(window, engine_module) -> None:
    existing = getattr(window, "_ai_workspace_window", None)
    if existing is not None:
        try:
            existing.deiconify()
            existing.lift()
            return
        except tk.TclError:
            pass

    dialog = tk.Toplevel(window)
    window._ai_workspace_window = dialog
    dialog.title("AI 工作台 · Galaxy Local Engine")
    dialog.geometry("860x620")
    dialog.minsize(760, 540)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=20, pady=18)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "本地 AI 工作台", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "Whisper 负责本地字幕；Ollama 负责本地摘要。没有显式操作时不会下载模型或启动 AI 网络请求。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(4, 12))

    status_var = tk.StringVar(value="检测中…")
    ui._label(shell, variable=status_var, size=8, color=ui.CYAN, bg=ui.BG).pack(anchor="w", pady=(0, 10))

    model_card = tk.Frame(shell, bg=ui.PANEL, padx=14, pady=12, highlightthickness=1, highlightbackground=ui.BORDER)
    model_card.pack(fill="x")
    settings = load_ai_model_settings(engine_module)
    whisper_var = tk.StringVar(value=settings.whisper_model)
    summary_var = tk.StringVar(value=settings.summary_model)

    ui._label(model_card, "Whisper 模型", size=8, weight="bold").grid(row=0, column=0, sticky="w")
    ttk.Combobox(
        model_card,
        textvariable=whisper_var,
        values=WHISPER_MODELS,
        state="readonly",
        width=16,
        style="Galaxy.TCombobox",
    ).grid(row=0, column=1, sticky="w", padx=(8, 18))
    ui._label(model_card, "Ollama 摘要模型", size=8, weight="bold").grid(row=0, column=2, sticky="w")
    summary_entry = tk.Entry(
        model_card,
        textvariable=summary_var,
        width=24,
        font=("Segoe UI", 8),
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
    )
    summary_entry.grid(row=0, column=3, sticky="ew", padx=(8, 0))
    model_card.grid_columnconfigure(3, weight=1)

    media_card = tk.Frame(shell, bg=ui.PANEL, padx=14, pady=12, highlightthickness=1, highlightbackground=ui.BORDER)
    media_card.pack(fill="both", expand=True, pady=(12, 0))
    ui._label(media_card, "媒体库", size=9, weight="bold").pack(anchor="w")
    ui._label(media_card, "只处理 Galaxy 媒体库中仍可用的本地文件。", size=7, color=ui.SUBTLE).pack(anchor="w", pady=(2, 8))

    listbox = tk.Listbox(
        media_card,
        bg=ui.BG,
        fg=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        relief="flat",
        font=("Segoe UI", 9),
        height=12,
    )
    listbox.pack(fill="both", expand=True)
    rows: list[dict] = []

    operation_var = tk.StringVar(value="就绪")
    ui._label(media_card, variable=operation_var, size=8, color=ui.MUTED).pack(anchor="w", pady=(8, 0))

    def refresh_models() -> None:
        data = ai_model_status(engine_module)
        whisper = "Whisper ✓" if data["whisperReady"] else "Whisper 未安装"
        ollama = "Ollama ✓" if data["ollamaReady"] else "Ollama 未安装"
        local = ", ".join(data["ollamaModels"][:5]) or "无本地摘要模型"
        status_var.set(f"{whisper} · {ollama} · {local}")

    def save_models() -> None:
        saved = save_ai_model_settings(
            engine_module,
            whisper_model=whisper_var.get(),
            summary_model=summary_var.get(),
        )
        whisper_var.set(saved.whisper_model)
        summary_var.set(saved.summary_model)
        refresh_models()

    def pull_model() -> None:
        model = summary_var.get().strip()
        if not model:
            messagebox.showinfo(engine_module.APP_NAME, "请先输入 Ollama 模型名称。", parent=dialog)
            return
        operation_var.set(f"正在拉取 {model}…")

        def worker() -> None:
            ok, detail = pull_ollama_model(engine_module, model)
            dialog.after(0, lambda: operation_var.set(detail or ("完成" if ok else "失败")))
            dialog.after(0, refresh_models)

        threading.Thread(target=worker, daemon=True).start()

    model_actions = tk.Frame(model_card, bg=ui.PANEL)
    model_actions.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(10, 0))
    ui.ActionButton(model_actions, text="保存模型设置", command=save_models, kind="secondary", compact=True).pack(side="right")
    ui.ActionButton(model_actions, text="显式拉取 Ollama 模型", command=pull_model, kind="ghost", compact=True).pack(side="right", padx=(0, 6))
    ui.ActionButton(model_actions, text="刷新检测", command=refresh_models, kind="ghost", compact=True).pack(side="left")

    def refresh_media() -> None:
        try:
            sync_media_library(engine_module)
        except Exception:  # noqa: BLE001
            # The catalog is derived state; a sync failure must not block reading existing rows.
            pass
        rows.clear()
        listbox.delete(0, "end")
        for item in list_media_items(engine_module, limit=300):
            if not item.get("available") or item.get("mediaType") not in {"video", "audio"}:
                continue
            rows.append(item)
            listbox.insert("end", f"{item.get('title') or item.get('fileName')}  ·  {item.get('mediaType')}")
        if rows:
            listbox.selection_set(0)

    def selected() -> dict | None:
        selection = listbox.curselection()
        return rows[selection[0]] if selection else None

    def run_task(kind: str) -> None:
        item = selected()
        if item is None:
            messagebox.showinfo(engine_module.APP_NAME, "请选择一个视频或音频。", parent=dialog)
            return
        media_id = str(item.get("id") or "")
        save_models()
        operation_var.set("正在执行本地 AI 任务…")

        def worker() -> None:
            try:
                if kind == "transcribe":
                    result = transcribe_media(engine_module, media_id, model=whisper_var.get())
                else:
                    if not transcript_path(engine_module, media_id).is_file():
                        transcribe_media(engine_module, media_id, model=whisper_var.get())
                    result = summarize_media(engine_module, media_id, model=summary_var.get())
                message = f"完成：{result.path.name}"
            except AiWorkspaceError as exc:
                message = f"失败：{exc}"
            except Exception as exc:  # noqa: BLE001
                message = f"失败：{exc}"
            dialog.after(0, lambda: operation_var.set(message))

        threading.Thread(target=worker, daemon=True).start()

    def open_artifact(kind: str) -> None:
        item = selected()
        if item is None:
            return
        try:
            path = transcript_path(engine_module, item["id"]) if kind == "transcript" else summary_path(engine_module, item["id"])
            if not path.is_file():
                messagebox.showinfo(engine_module.APP_NAME, "该文件尚未生成。", parent=dialog)
                return
            _open_path(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(engine_module.APP_NAME, str(exc), parent=dialog)

    footer = tk.Frame(shell, bg=ui.BG)
    footer.pack(fill="x", pady=(12, 0))
    ui.ActionButton(footer, text="刷新媒体库", command=refresh_media, kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(footer, text="打开摘要", command=lambda: open_artifact("summary"), kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(footer, text="打开字幕", command=lambda: open_artifact("transcript"), kind="ghost", compact=True).pack(side="right", padx=(0, 6))
    ui.ActionButton(footer, text="生成摘要", command=lambda: run_task("summary"), kind="secondary", compact=True).pack(side="right", padx=(0, 6))
    ui.ActionButton(footer, text="Whisper 字幕", command=lambda: run_task("transcribe"), kind="secondary", compact=True).pack(side="right", padx=(0, 6))

    def close() -> None:
        window._ai_workspace_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh_models()
    refresh_media()


def _add_ai_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_ai_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "AI 字幕与摘要", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(text, "本地 Whisper + Ollama；模型下载必须由你显式触发。", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(
        card,
        text="打开 AI 工作台",
        command=lambda: _show_ai_workspace(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_ai_entry_built = True


def install_desktop_ai(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_ai_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-ai",
        lambda window: _add_ai_entry(window, engine_module),
        order=52,
    )
    window_cls._galaxy_desktop_ai_installed = True
    return window_cls


def run_desktop_ai_self_test() -> None:
    assert tuple(WHISPER_MODELS)
