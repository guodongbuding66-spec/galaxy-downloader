from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import desktop_ui as ui
from ai_provider_manager import (
    load_ai_providers,
    load_prompt_library,
    provider_has_key,
    save_ai_provider,
)
from bilibili_advanced import export_bilibili_sidecars
from desktop_hooks import register_after_build_ui_hook
from local_media_import import import_local_media_batch
from media_library import list_media_items, sync_media_library
from media_postprocess import remux_media
from music_workspace import attach_lyrics, music_library_v2
from reader_library import import_book, list_books_v2
from telegram_transfer import (
    TelegramUploadSettings,
    load_telegram_upload_settings,
    save_telegram_upload_settings,
    upload_to_telegram,
)
from transcript_workspace import asr_provider_status, search_transcript


def _entry(master, variable, width=30, *, secret: bool = False):
    return tk.Entry(
        master,
        textvariable=variable,
        width=width,
        show="•" if secret else "",
        font=("Segoe UI", 8),
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
    )


def _listbox(master, height=12):
    return tk.Listbox(
        master,
        height=height,
        bg=ui.BG,
        fg=ui.TEXT,
        selectbackground=ui.PANEL_3,
        selectforeground=ui.TEXT,
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        relief="flat",
        font=("Segoe UI", 8),
    )


def _show_advanced_workbench(window, engine_module) -> None:
    existing = getattr(window, "_advanced54_window", None)
    if existing is not None:
        try:
            existing.deiconify()
            existing.lift()
            return
        except tk.TclError:
            pass

    dialog = tk.Toplevel(window)
    window._advanced54_window = dialog
    dialog.title("高级工作台 · Galaxy Local Engine")
    dialog.geometry("980x700")
    dialog.minsize(860, 600)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=18, pady=16)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "高级工作台", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "本地导入、Transcript 检索、AI Provider、阅读/音乐、Bilibili Sidecar 与 Telegram 上传。联网操作均需显式点击。",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(3, 10))

    notebook = ttk.Notebook(shell, style="Galaxy.TNotebook")
    notebook.pack(fill="both", expand=True)

    # Local library / transcript / postprocess
    library_tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14)
    notebook.add(library_tab, text="媒体与 Transcript")
    library_rows: list[dict] = []
    media_list = _listbox(library_tab, 12)
    media_list.pack(fill="both", expand=True)
    library_status = tk.StringVar(value="就绪")
    ui._label(library_tab, variable=library_status, size=7, color=ui.MUTED).pack(anchor="w", pady=(6, 0))

    def refresh_media() -> None:
        try:
            sync_media_library(engine_module)
        except Exception:  # noqa: BLE001
            pass
        library_rows[:] = [item for item in list_media_items(engine_module, limit=500) if item.get("available")]
        media_list.delete(0, "end")
        for item in library_rows:
            media_list.insert("end", f"{item.get('mediaType')} · {item.get('title') or item.get('fileName')}")
        if library_rows:
            media_list.selection_set(0)

    def selected_media() -> dict | None:
        selected = media_list.curselection()
        return library_rows[selected[0]] if selected else None

    transcript_query = tk.StringVar()
    transcript_row = tk.Frame(library_tab, bg=ui.PANEL)
    transcript_row.pack(fill="x", pady=(9, 0))
    ui._label(transcript_row, "Transcript", size=7, color=ui.MUTED).pack(side="left")
    _entry(transcript_row, transcript_query, 38).pack(side="left", fill="x", expand=True, padx=(7, 8))
    transcript_result = tk.StringVar(value="")

    def search_text() -> None:
        media = selected_media()
        media_id = str(media.get("id") or "") if media else ""
        rows = search_transcript(engine_module, transcript_query.get(), media_id=media_id, limit=30)
        if not rows:
            transcript_result.set("没有匹配的已索引 Transcript")
            return
        preview = " | ".join(f"{row['startSeconds']:.1f}s {row['text'][:70]}" for row in rows[:5])
        transcript_result.set(preview[:700])

    ui.ActionButton(transcript_row, text="搜索", command=search_text, kind="ghost", compact=True).pack(side="right")
    ui._label(library_tab, variable=transcript_result, size=7, color=ui.SUBTLE, wraplength=850, justify="left").pack(anchor="w", pady=(5, 0))

    actions = tk.Frame(library_tab, bg=ui.PANEL)
    actions.pack(fill="x", pady=(10, 0))

    def import_media() -> None:
        values = filedialog.askopenfilenames(
            parent=dialog,
            title="导入本地媒体",
            filetypes=(("Media", "*.mp4 *.mkv *.webm *.mov *.m4v *.avi *.ts *.mp3 *.m4a *.aac *.flac *.wav *.ogg *.opus"),),
        )
        if not values:
            return
        try:
            results = import_local_media_batch(engine_module, values)
            library_status.set(f"已导入 {len(results)} 个媒体文件")
            refresh_media()
        except Exception as exc:  # noqa: BLE001
            library_status.set(f"导入失败：{exc}")

    def remux(container: str) -> None:
        media = selected_media()
        if not media:
            return
        try:
            result = remux_media(
                engine_module,
                media["id"],
                container=container,
                metadata={"title": media.get("title") or media.get("fileName")},
            )
            library_status.set(f"已输出 {result.path.name}")
        except Exception as exc:  # noqa: BLE001
            library_status.set(f"处理失败：{exc}")

    ui.ActionButton(actions, text="导入本地媒体", command=import_media, kind="secondary", compact=True).pack(side="left")
    ui.ActionButton(actions, text="刷新", command=refresh_media, kind="ghost", compact=True).pack(side="left", padx=(6, 0))
    ui.ActionButton(actions, text="Remux MKV", command=lambda: remux("mkv"), kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(actions, text="Remux MP4", command=lambda: remux("mp4"), kind="ghost", compact=True).pack(side="right", padx=(0, 6))

    # AI providers + prompt library
    ai_tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14)
    notebook.add(ai_tab, text="AI Provider")
    provider_rows = load_ai_providers(engine_module)
    provider_map = {item.id: item for item in provider_rows}
    provider_var = tk.StringVar(value=provider_rows[0].id if provider_rows else "openai")
    provider_name = tk.StringVar()
    provider_url = tk.StringVar()
    provider_model = tk.StringVar()
    provider_key = tk.StringVar()
    provider_status = tk.StringVar(value="选择 Provider 后保存；API Key 不会显示在状态响应中。")

    def load_provider_fields(*_args) -> None:
        provider = provider_map.get(provider_var.get())
        if provider is None:
            return
        provider_name.set(provider.name)
        provider_url.set(provider.base_url)
        provider_model.set(provider.model)
        provider_key.set("")
        provider_status.set("API Key 已保存" if provider_has_key(engine_module, provider.id) else "尚未保存 API Key")

    header = tk.Frame(ai_tab, bg=ui.PANEL)
    header.pack(fill="x")
    ttk.Combobox(
        header,
        textvariable=provider_var,
        values=tuple(provider_map),
        state="readonly",
        width=18,
        style="Galaxy.TCombobox",
    ).pack(side="left")
    ui._label(header, variable=provider_status, size=7, color=ui.MUTED).pack(side="left", padx=(10, 0))
    provider_var.trace_add("write", load_provider_fields)

    form = tk.Frame(ai_tab, bg=ui.PANEL)
    form.pack(fill="x", pady=(12, 0))
    for col in range(2):
        form.grid_columnconfigure(col * 2 + 1, weight=1)
    ui._label(form, "名称", size=7, color=ui.MUTED).grid(row=0, column=0, sticky="w")
    _entry(form, provider_name, 25).grid(row=0, column=1, sticky="ew", padx=(6, 16))
    ui._label(form, "模型", size=7, color=ui.MUTED).grid(row=0, column=2, sticky="w")
    _entry(form, provider_model, 30).grid(row=0, column=3, sticky="ew", padx=(6, 0))
    ui._label(form, "Endpoint", size=7, color=ui.MUTED).grid(row=1, column=0, sticky="w", pady=(8, 0))
    _entry(form, provider_url, 52).grid(row=1, column=1, columnspan=3, sticky="ew", padx=(6, 0), pady=(8, 0))
    ui._label(form, "API Key", size=7, color=ui.MUTED).grid(row=2, column=0, sticky="w", pady=(8, 0))
    _entry(form, provider_key, 52, secret=True).grid(row=2, column=1, columnspan=3, sticky="ew", padx=(6, 0), pady=(8, 0))

    def save_provider_settings() -> None:
        current = provider_map.get(provider_var.get())
        if current is None:
            return
        try:
            saved = save_ai_provider(
                engine_module,
                provider_id=current.id,
                name=provider_name.get(),
                protocol=current.protocol,
                base_url=provider_url.get(),
                model=provider_model.get(),
                api_key=provider_key.get(),
                enabled=True,
                allow_local=current.id in {"ollama", "lmstudio"},
            )
            provider_map[saved.id] = saved
            provider_key.set("")
            provider_status.set("Provider 设置已保存")
        except Exception as exc:  # noqa: BLE001
            provider_status.set(f"保存失败：{exc}")

    ui.ActionButton(ai_tab, text="保存 Provider", command=save_provider_settings, kind="secondary", compact=True).pack(anchor="e", pady=(10, 0))
    prompts = load_prompt_library(engine_module)
    ui._label(ai_tab, "Prompt Library", size=9, weight="bold").pack(anchor="w", pady=(14, 4))
    prompt_list = _listbox(ai_tab, 8)
    prompt_list.pack(fill="both", expand=True)
    for prompt in prompts:
        prompt_list.insert("end", f"{prompt.title} · {prompt.id}")

    # Reader / music
    reader_tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14)
    notebook.add(reader_tab, text="阅读与音乐")
    reader_status = tk.StringVar(value="就绪")
    reader_list = _listbox(reader_tab, 10)
    reader_list.pack(fill="both", expand=True)

    def refresh_books() -> None:
        reader_list.delete(0, "end")
        for book in list_books_v2(engine_module):
            reader_list.insert("end", f"{book['kind'].upper()} · {book['title']} · {book['progress']:.0f}%")

    def import_reader_book() -> None:
        value = filedialog.askopenfilename(parent=dialog, title="导入阅读文件", filetypes=(("Books", "*.pdf *.epub *.cbz"),))
        if not value:
            return
        try:
            book = import_book(engine_module, value)
            reader_status.set(f"已导入 {book['title']}")
            refresh_books()
        except Exception as exc:  # noqa: BLE001
            reader_status.set(f"导入失败：{exc}")

    music_rows: list[dict] = []
    music_list = _listbox(reader_tab, 7)
    music_list.pack(fill="x", pady=(10, 0))

    def refresh_music() -> None:
        music_rows[:] = music_library_v2(engine_module)
        music_list.delete(0, "end")
        for item in music_rows:
            lyrics = "LRC" if item.get("hasSyncedLyrics") else "无歌词"
            music_list.insert("end", f"{item.get('title') or item.get('fileName')} · {lyrics}")
        if music_rows:
            music_list.selection_set(0)

    def attach_selected_lyrics() -> None:
        selected = music_list.curselection()
        if not selected:
            return
        value = filedialog.askopenfilename(parent=dialog, title="选择 LRC", filetypes=(("LRC", "*.lrc"),))
        if not value:
            return
        try:
            count = attach_lyrics(engine_module, music_rows[selected[0]]["id"], value)
            reader_status.set(f"歌词已关联 · {count} 行")
            refresh_music()
        except Exception as exc:  # noqa: BLE001
            reader_status.set(f"歌词失败：{exc}")

    reader_actions = tk.Frame(reader_tab, bg=ui.PANEL)
    reader_actions.pack(fill="x", pady=(8, 0))
    ui.ActionButton(reader_actions, text="导入 PDF/EPUB/CBZ", command=import_reader_book, kind="secondary", compact=True).pack(side="left")
    ui.ActionButton(reader_actions, text="刷新书库", command=refresh_books, kind="ghost", compact=True).pack(side="left", padx=(6, 0))
    ui.ActionButton(reader_actions, text="关联 LRC", command=attach_selected_lyrics, kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(reader_actions, text="刷新音乐", command=refresh_music, kind="ghost", compact=True).pack(side="right", padx=(0, 6))
    ui._label(reader_tab, variable=reader_status, size=7, color=ui.MUTED).pack(anchor="w", pady=(6, 0))

    # Bilibili + Telegram explicit network operations
    transfer_tab = tk.Frame(notebook, bg=ui.PANEL, padx=14, pady=14)
    notebook.add(transfer_tab, text="Bilibili / Telegram")
    bili_url = tk.StringVar()
    bili_page = tk.StringVar(value="1")
    network_status = tk.StringVar(value="联网操作不会自动运行。")
    bili_row = tk.Frame(transfer_tab, bg=ui.PANEL)
    bili_row.pack(fill="x")
    ui._label(bili_row, "Bilibili", size=7, color=ui.MUTED).pack(side="left")
    _entry(bili_row, bili_url, 52).pack(side="left", fill="x", expand=True, padx=(7, 8))
    ui._label(bili_row, "P", size=7, color=ui.MUTED).pack(side="left")
    _entry(bili_row, bili_page, 5).pack(side="left", padx=(5, 8))

    def export_sidecars() -> None:
        network_status.set("正在获取 Bilibili 元数据与弹幕…")

        def worker() -> None:
            try:
                result = export_bilibili_sidecars(engine_module, bili_url.get(), page=int(bili_page.get() or 1))
                message = f"Sidecar 已保存：{result.root}"
            except Exception as exc:  # noqa: BLE001
                message = f"Bilibili 失败：{exc}"
            dialog.after(0, lambda: network_status.set(message))

        threading.Thread(target=worker, daemon=True).start()

    ui.ActionButton(bili_row, text="导出弹幕/NFO", command=export_sidecars, kind="secondary", compact=True).pack(side="right")

    tg = load_telegram_upload_settings(engine_module)
    tg_chat = tk.StringVar(value=tg.chat_id)
    tg_mode = tk.StringVar(value=tg.mode)
    tg_token = tk.StringVar()
    tg_row = tk.Frame(transfer_tab, bg=ui.PANEL)
    tg_row.pack(fill="x", pady=(14, 0))
    ui._label(tg_row, "Telegram Chat", size=7, color=ui.MUTED).pack(side="left")
    _entry(tg_row, tg_chat, 24).pack(side="left", padx=(7, 10))
    ttk.Combobox(tg_row, textvariable=tg_mode, values=("bot", "user"), state="readonly", width=8, style="Galaxy.TCombobox").pack(side="left")
    ui._label(tg_row, "Bot Token", size=7, color=ui.MUTED).pack(side="left", padx=(12, 0))
    _entry(tg_row, tg_token, 28, secret=True).pack(side="left", fill="x", expand=True, padx=(7, 0))

    def save_telegram() -> None:
        try:
            save_telegram_upload_settings(
                engine_module,
                TelegramUploadSettings(mode=tg_mode.get(), chat_id=tg_chat.get(), send_as="document"),
                bot_token=tg_token.get(),
            )
            tg_token.set("")
            network_status.set("Telegram 设置已保存")
        except Exception as exc:  # noqa: BLE001
            network_status.set(f"Telegram 设置失败：{exc}")

    def upload_selected() -> None:
        media = selected_media()
        if not media:
            network_status.set("请先在“媒体与 Transcript”中选择媒体")
            return
        network_status.set("正在上传 Telegram…")

        def worker() -> None:
            try:
                results = upload_to_telegram(engine_module, media_id=media["id"])
                message = f"Telegram 上传完成 · {len(results)} 个请求"
            except Exception as exc:  # noqa: BLE001
                message = f"Telegram 上传失败：{exc}"
            dialog.after(0, lambda: network_status.set(message))

        threading.Thread(target=worker, daemon=True).start()

    tg_actions = tk.Frame(transfer_tab, bg=ui.PANEL)
    tg_actions.pack(fill="x", pady=(8, 0))
    ui.ActionButton(tg_actions, text="保存 Telegram", command=save_telegram, kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(tg_actions, text="上传所选媒体", command=upload_selected, kind="secondary", compact=True).pack(side="right")
    ui._label(transfer_tab, variable=network_status, size=7, color=ui.MUTED, wraplength=850, justify="left").pack(anchor="w", pady=(10, 0))

    asr = asr_provider_status(engine_module)
    ready_asr = ", ".join(item["id"] for item in asr if item["ready"]) or "无"
    ui._label(transfer_tab, f"ASR Provider 就绪：{ready_asr}", size=7, color=ui.SUBTLE).pack(anchor="w", pady=(12, 0))

    def close() -> None:
        window._advanced54_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    load_provider_fields()
    refresh_media()
    refresh_books()
    refresh_music()


def _add_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_advanced54_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "高级工作台", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        text,
        "本地导入 · Transcript · AI Provider · Reader · Bilibili · Telegram",
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(
        card,
        text="打开高级工作台",
        command=lambda: _show_advanced_workbench(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_advanced54_entry_built = True


def install_desktop_advanced(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_advanced_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-advanced54",
        lambda window: _add_entry(window, engine_module),
        order=56,
    )
    window_cls._galaxy_desktop_advanced_installed = True
    return window_cls


def run_desktop_advanced_self_test() -> None:
    assert callable(import_local_media_batch)
    assert callable(search_transcript)
    assert callable(save_ai_provider)
    assert callable(import_book)
    assert callable(export_bilibili_sidecars)
    assert callable(upload_to_telegram)
