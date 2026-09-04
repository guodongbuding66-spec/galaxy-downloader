from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook
from headless_music_api import HeadlessMusicApi


def _api(engine_module) -> HeadlessMusicApi:
    return HeadlessMusicApi(engine_module.default_download_dir())


def _show_music(window, engine_module) -> None:
    existing = getattr(window, "_music_workspace_window", None)
    if existing is not None:
        try:
            existing.deiconify(); existing.lift(); return
        except tk.TclError:
            pass
    dialog = tk.Toplevel(window)
    window._music_workspace_window = dialog
    dialog.title("音乐库 · Galaxy Local Engine")
    dialog.geometry("960x660")
    dialog.minsize(820, 540)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=18, pady=16); shell.pack(fill="both", expand=True)
    ui._label(shell, "音乐库", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(shell, "歌曲 · 收藏 · 最近播放 · 播放队列 · 循环/随机/音量状态", size=8, color=ui.MUTED, bg=ui.BG).pack(anchor="w", pady=(3, 10))
    api = _api(engine_module)

    query = tk.StringVar(); favorites = tk.BooleanVar(value=False); status = tk.StringVar(value="就绪")
    top = tk.Frame(shell, bg=ui.BG); top.pack(fill="x")
    tk.Entry(top, textvariable=query, bg=ui.PANEL, fg=ui.TEXT, insertbackground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER).pack(side="left", fill="x", expand=True, ipady=5)
    tk.Checkbutton(top, text="仅收藏", variable=favorites, bg=ui.BG, fg=ui.TEXT, selectcolor=ui.PANEL, activebackground=ui.BG, activeforeground=ui.TEXT).pack(side="left", padx=(8, 0))

    notebook = ttk.Notebook(shell); notebook.pack(fill="both", expand=True, pady=(10, 0))
    songs_tab = tk.Frame(notebook, bg=ui.PANEL, padx=12, pady=12); notebook.add(songs_tab, text="歌曲")
    queue_tab = tk.Frame(notebook, bg=ui.PANEL, padx=12, pady=12); notebook.add(queue_tab, text="播放队列")

    song_list = tk.Listbox(songs_tab, bg=ui.BG, fg=ui.TEXT, selectbackground=ui.PANEL_3, selectforeground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER)
    song_list.pack(fill="both", expand=True)
    songs: list[dict] = []
    queue_list = tk.Listbox(queue_tab, bg=ui.BG, fg=ui.TEXT, selectbackground=ui.PANEL_3, selectforeground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER)
    queue_list.pack(fill="both", expand=True)
    queue_rows: list[dict] = []

    player_row = tk.Frame(queue_tab, bg=ui.PANEL); player_row.pack(fill="x", pady=(10, 0))
    repeat_var = tk.StringVar(value="off"); shuffle_var = tk.BooleanVar(value=False); volume_var = tk.DoubleVar(value=1.0)
    ui._label(player_row, "循环", size=7, color=ui.MUTED).pack(side="left")
    ttk.Combobox(player_row, textvariable=repeat_var, values=("off","all","one"), state="readonly", width=7).pack(side="left", padx=(5, 10))
    tk.Checkbutton(player_row, text="随机", variable=shuffle_var, bg=ui.PANEL, fg=ui.TEXT, selectcolor=ui.BG, activebackground=ui.PANEL, activeforeground=ui.TEXT).pack(side="left")
    ui._label(player_row, "音量 0-1", size=7, color=ui.MUTED).pack(side="left", padx=(10, 0))
    tk.Entry(player_row, textvariable=volume_var, width=7, bg=ui.BG, fg=ui.TEXT, insertbackground=ui.TEXT, relief="flat", highlightthickness=1, highlightbackground=ui.BORDER).pack(side="left", padx=(5, 0))

    def selected_song():
        s = song_list.curselection(); return songs[s[0]] if s else None
    def selected_queue():
        s = queue_list.curselection(); return queue_rows[s[0]] if s else None

    def refresh_queue() -> None:
        data = api.queue(); queue_rows[:] = data.get("queue", [])
        queue_list.delete(0, "end")
        for row in queue_rows:
            track = row.get("track") or {}
            queue_list.insert("end", f"{row.get('position')} · {track.get('artist') or 'Unknown'} — {track.get('title') or track.get('fileName')}")
        player = api.player().get("player", {})
        repeat_var.set(str(player.get("repeatMode") or "off")); shuffle_var.set(bool(player.get("shuffle", False))); volume_var.set(float(player.get("volume", 1.0) or 1.0))

    def refresh(sync: bool = False) -> None:
        try:
            if sync: api.sync()
            data = api.list_songs(query=query.get(), favorites_only=bool(favorites.get()), limit=2000)
            songs[:] = data.get("songs", [])
            song_list.delete(0, "end")
            for track in songs:
                fav = "★" if track.get("favorite") else "☆"
                song_list.insert("end", f"{fav} {track.get('artist') or 'Unknown'} — {track.get('title') or track.get('fileName')}")
            if songs: song_list.selection_set(0)
            refresh_queue(); status.set(f"{len(songs)} 首")
        except Exception as exc: status.set(f"失败：{exc}")

    def favorite() -> None:
        song = selected_song()
        if not song: return
        try:
            api.update_song_state(song["id"], {"favorite": not bool(song.get("favorite"))}); refresh()
        except Exception as exc: status.set(f"失败：{exc}")

    def enqueue() -> None:
        song = selected_song()
        if not song: return
        try:
            api.enqueue({"mediaIds": [song["id"]]}); refresh_queue(); status.set("已加入队列")
        except Exception as exc: status.set(f"失败：{exc}")

    def remove_queue() -> None:
        row = selected_queue()
        if not row: return
        try:
            api.remove_queue_item(row["id"]); refresh_queue()
        except Exception as exc: status.set(f"失败：{exc}")

    def save_player() -> None:
        try:
            api.update_player({"repeatMode": repeat_var.get(), "shuffle": bool(shuffle_var.get()), "volume": float(volume_var.get())})
            status.set("播放器状态已保存"); refresh_queue()
        except Exception as exc: status.set(f"失败：{exc}")

    ui.ActionButton(top, text="搜索", command=refresh, kind="ghost", compact=True).pack(side="right", padx=(8, 0))
    song_actions = tk.Frame(songs_tab, bg=ui.PANEL); song_actions.pack(fill="x", pady=(10, 0))
    ui.ActionButton(song_actions, text="同步音乐库", command=lambda: refresh(True), kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(song_actions, text="收藏/取消", command=favorite, kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(song_actions, text="加入队列", command=enqueue, kind="secondary", compact=True).pack(side="right", padx=(0, 6))
    queue_actions = tk.Frame(queue_tab, bg=ui.PANEL); queue_actions.pack(fill="x", pady=(10, 0))
    ui.ActionButton(queue_actions, text="保存播放器状态", command=save_player, kind="secondary", compact=True).pack(side="left")
    ui.ActionButton(queue_actions, text="清空队列", command=lambda: (api.clear_queue(), refresh_queue()), kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(queue_actions, text="移出队列", command=remove_queue, kind="ghost", compact=True).pack(side="right", padx=(0, 6))
    ui._label(shell, variable=status, size=8, color=ui.MUTED, bg=ui.BG).pack(anchor="w", pady=(8, 0))

    def close() -> None:
        window._music_workspace_window = None; dialog.destroy()
    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh()


def _add_music_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_music_entry_built", False): return
    card = tk.Frame(panel, bg=ui.PANEL_2); card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2); text.pack(side="left", fill="x", expand=True)
    ui._label(text, "音乐库", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(text, "歌曲 · 收藏 · 队列 · 播放状态", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w", pady=(2, 0))
    ui.ActionButton(card, text="打开音乐库", command=lambda: _show_music(window, engine_module), kind="secondary", compact=True).pack(side="right")
    window._galaxy_music_entry_built = True


def install_desktop_music(engine_module):
    cls = engine_module.EngineWindow
    if getattr(cls, "_galaxy_desktop_music_installed", False): return cls
    register_after_build_ui_hook(cls, "desktop-music", lambda window: _add_music_entry(window, engine_module), order=56)
    cls._galaxy_desktop_music_installed = True
    return cls


def run_desktop_music_self_test() -> None:
    assert callable(HeadlessMusicApi)
