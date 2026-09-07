from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook
from headless_music_api import HeadlessMusicApi


MAX_LYRICS_DISPLAY_ROWS = 5_000


def _api(engine_module) -> HeadlessMusicApi:
    return HeadlessMusicApi(engine_module.default_download_dir())


def _count_label(value: object, noun: str) -> str:
    try:
        count = max(0, int(value or 0))
    except (TypeError, ValueError):
        count = 0
    return f"{count} {noun}"


def _format_album(row: dict[str, Any]) -> str:
    album = str(row.get("album") or "Unknown Album").strip() or "Unknown Album"
    artist = str(row.get("albumArtist") or row.get("artist") or "Unknown Artist").strip() or "Unknown Artist"
    year = str(row.get("year") or "").strip()
    count = _count_label(row.get("trackCount") or row.get("tracks") or row.get("count"), "首")
    suffix = f" · {year}" if year and year != "0" else ""
    return f"{album} — {artist}{suffix} · {count}"


def _format_artist(row: dict[str, Any]) -> str:
    artist = str(row.get("artist") or row.get("name") or "Unknown Artist").strip() or "Unknown Artist"
    tracks = _count_label(row.get("trackCount") or row.get("tracks") or row.get("count"), "首")
    albums_raw = row.get("albumCount") or row.get("albums")
    if albums_raw is None:
        return f"{artist} · {tracks}"
    return f"{artist} · {_count_label(albums_raw, '张专辑')} · {tracks}"


def _format_track(track: dict[str, Any], *, show_favorite: bool = True, show_plays: bool = False) -> str:
    favorite = "★ " if show_favorite and track.get("favorite") else ("☆ " if show_favorite else "")
    artist = str(track.get("artist") or "Unknown Artist")
    title = str(track.get("title") or track.get("fileName") or "Unknown Track")
    suffix = ""
    if show_plays:
        try:
            plays = max(0, int(track.get("playCount") or 0))
        except (TypeError, ValueError):
            plays = 0
        suffix = f" · 播放 {plays} 次"
    return f"{favorite}{artist} — {title}{suffix}"


def _format_timestamp(seconds: object) -> str:
    try:
        value = max(0.0, float(seconds or 0.0))
    except (TypeError, ValueError):
        value = 0.0
    total = int(value)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _render_lyrics_payload(payload: dict[str, Any]) -> tuple[str, str]:
    lyrics = payload.get("lyrics") if isinstance(payload, dict) else None
    if not isinstance(lyrics, dict):
        return "暂无歌词", "none"
    kind = str(lyrics.get("kind") or "none")
    synced = lyrics.get("synced")
    if isinstance(synced, list) and synced:
        lines: list[str] = []
        for row in synced[:MAX_LYRICS_DISPLAY_ROWS]:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()
            if text:
                lines.append(f"[{_format_timestamp(row.get('time'))}]  {text}")
        if len(synced) > MAX_LYRICS_DISPLAY_ROWS:
            lines.append(f"\n… 仅显示前 {MAX_LYRICS_DISPLAY_ROWS} 行，共 {len(synced)} 行")
        return ("\n".join(lines) or "暂无歌词"), kind
    text = str(lyrics.get("text") or "").strip()
    return (text or "暂无歌词"), kind


def _show_music(window, engine_module) -> None:
    existing = getattr(window, "_music_workspace_window", None)
    if existing is not None:
        try:
            existing.deiconify()
            existing.lift()
            return
        except tk.TclError:
            pass

    dialog = tk.Toplevel(window)
    window._music_workspace_window = dialog
    dialog.title("音乐库 · Galaxy Local Engine")
    dialog.geometry("1040x720")
    dialog.minsize(860, 580)
    dialog.configure(bg=ui.BG)
    dialog.transient(window)

    shell = tk.Frame(dialog, bg=ui.BG, padx=18, pady=16)
    shell.pack(fill="both", expand=True)
    ui._label(shell, "音乐库", size=16, weight="bold", bg=ui.BG).pack(anchor="w")
    ui._label(
        shell,
        "歌曲 · 专辑 · 艺术家 · 收藏 · 播放历史 · 歌词 · 队列",
        size=8,
        color=ui.MUTED,
        bg=ui.BG,
    ).pack(anchor="w", pady=(3, 10))

    api = _api(engine_module)
    query = tk.StringVar()
    favorites = tk.BooleanVar(value=False)
    status = tk.StringVar(value="就绪")

    top = tk.Frame(shell, bg=ui.BG)
    top.pack(fill="x")
    search_entry = tk.Entry(
        top,
        textvariable=query,
        bg=ui.PANEL,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    )
    search_entry.pack(side="left", fill="x", expand=True, ipady=5)
    tk.Checkbutton(
        top,
        text="仅收藏",
        variable=favorites,
        bg=ui.BG,
        fg=ui.TEXT,
        selectcolor=ui.PANEL,
        activebackground=ui.BG,
        activeforeground=ui.TEXT,
    ).pack(side="left", padx=(8, 0))

    notebook = ttk.Notebook(shell)
    notebook.pack(fill="both", expand=True, pady=(10, 0))

    songs_tab = tk.Frame(notebook, bg=ui.PANEL, padx=12, pady=12)
    albums_tab = tk.Frame(notebook, bg=ui.PANEL, padx=12, pady=12)
    artists_tab = tk.Frame(notebook, bg=ui.PANEL, padx=12, pady=12)
    history_tab = tk.Frame(notebook, bg=ui.PANEL, padx=12, pady=12)
    lyrics_tab = tk.Frame(notebook, bg=ui.PANEL, padx=12, pady=12)
    queue_tab = tk.Frame(notebook, bg=ui.PANEL, padx=12, pady=12)
    notebook.add(songs_tab, text="歌曲")
    notebook.add(albums_tab, text="专辑")
    notebook.add(artists_tab, text="艺术家")
    notebook.add(history_tab, text="播放历史")
    notebook.add(lyrics_tab, text="歌词")
    notebook.add(queue_tab, text="播放队列")

    listbox_options = {
        "bg": ui.BG,
        "fg": ui.TEXT,
        "selectbackground": ui.PANEL_3,
        "selectforeground": ui.TEXT,
        "relief": "flat",
        "highlightthickness": 1,
        "highlightbackground": ui.BORDER,
        "activestyle": "none",
    }

    song_list = tk.Listbox(songs_tab, **listbox_options)
    song_list.pack(fill="both", expand=True)
    songs: list[dict[str, Any]] = []

    album_list = tk.Listbox(albums_tab, **listbox_options)
    album_list.pack(fill="both", expand=True)
    album_rows: list[dict[str, Any]] = []

    artist_list = tk.Listbox(artists_tab, **listbox_options)
    artist_list.pack(fill="both", expand=True)
    artist_rows: list[dict[str, Any]] = []

    history_columns = tk.Frame(history_tab, bg=ui.PANEL)
    history_columns.pack(fill="both", expand=True)
    recent_panel = tk.Frame(history_columns, bg=ui.PANEL)
    recent_panel.pack(side="left", fill="both", expand=True, padx=(0, 6))
    popular_panel = tk.Frame(history_columns, bg=ui.PANEL)
    popular_panel.pack(side="left", fill="both", expand=True, padx=(6, 0))
    ui._label(recent_panel, "最近播放", size=8, weight="bold", bg=ui.PANEL).pack(anchor="w", pady=(0, 6))
    ui._label(popular_panel, "最多播放", size=8, weight="bold", bg=ui.PANEL).pack(anchor="w", pady=(0, 6))
    recent_list = tk.Listbox(recent_panel, **listbox_options)
    recent_list.pack(fill="both", expand=True)
    popular_list = tk.Listbox(popular_panel, **listbox_options)
    popular_list.pack(fill="both", expand=True)
    recent_rows: list[dict[str, Any]] = []
    popular_rows: list[dict[str, Any]] = []

    lyrics_header = tk.StringVar(value="选择歌曲后查看歌词")
    ui._label(lyrics_tab, variable=lyrics_header, size=8, weight="bold", bg=ui.PANEL).pack(anchor="w", pady=(0, 6))
    lyrics_text = ScrolledText(
        lyrics_tab,
        wrap="word",
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        padx=10,
        pady=10,
    )
    lyrics_text.pack(fill="both", expand=True)
    lyrics_text.insert("1.0", "暂无歌词")
    lyrics_text.configure(state="disabled")

    queue_list = tk.Listbox(queue_tab, **listbox_options)
    queue_list.pack(fill="both", expand=True)
    queue_rows: list[dict[str, Any]] = []

    player_row = tk.Frame(queue_tab, bg=ui.PANEL)
    player_row.pack(fill="x", pady=(10, 0))
    repeat_var = tk.StringVar(value="off")
    shuffle_var = tk.BooleanVar(value=False)
    volume_var = tk.DoubleVar(value=1.0)
    ui._label(player_row, "循环", size=7, color=ui.MUTED, bg=ui.PANEL).pack(side="left")
    ttk.Combobox(player_row, textvariable=repeat_var, values=("off", "all", "one"), state="readonly", width=7).pack(
        side="left", padx=(5, 10)
    )
    tk.Checkbutton(
        player_row,
        text="随机",
        variable=shuffle_var,
        bg=ui.PANEL,
        fg=ui.TEXT,
        selectcolor=ui.BG,
        activebackground=ui.PANEL,
        activeforeground=ui.TEXT,
    ).pack(side="left")
    ui._label(player_row, "音量 0-1", size=7, color=ui.MUTED, bg=ui.PANEL).pack(side="left", padx=(10, 0))
    tk.Entry(
        player_row,
        textvariable=volume_var,
        width=7,
        bg=ui.BG,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
    ).pack(side="left", padx=(5, 0))

    def selected_song() -> dict[str, Any] | None:
        selected = song_list.curselection()
        return songs[selected[0]] if selected else None

    def selected_queue() -> dict[str, Any] | None:
        selected = queue_list.curselection()
        return queue_rows[selected[0]] if selected else None

    def refresh_queue() -> None:
        data = api.queue()
        queue_rows[:] = data.get("queue", [])
        queue_list.delete(0, "end")
        for row in queue_rows:
            track = row.get("track") or {}
            queue_list.insert("end", f"{row.get('position')} · {_format_track(track, show_favorite=False)}")
        player = api.player().get("player", {})
        repeat_var.set(str(player.get("repeatMode") or "off"))
        shuffle_var.set(bool(player.get("shuffle", False)))
        volume_var.set(float(player.get("volume", 1.0) or 1.0))

    def refresh_songs(*, sync: bool = False) -> None:
        if sync:
            api.sync()
        data = api.list_songs(query=query.get(), favorites_only=bool(favorites.get()), limit=2000)
        songs[:] = data.get("songs", [])
        song_list.delete(0, "end")
        for track in songs:
            song_list.insert("end", _format_track(track))
        if songs:
            song_list.selection_set(0)
            song_list.activate(0)
        status.set(f"{len(songs)} 首歌曲")

    def refresh_catalogs() -> None:
        albums_data = api.list_albums(limit=500)
        album_rows[:] = albums_data.get("albums", [])
        album_list.delete(0, "end")
        for row in album_rows:
            album_list.insert("end", _format_album(row))

        artists_data = api.list_artists(limit=500)
        artist_rows[:] = artists_data.get("artists", [])
        artist_list.delete(0, "end")
        for row in artist_rows:
            artist_list.insert("end", _format_artist(row))

    def refresh_history() -> None:
        recent_data = api.recent(limit=200)
        recent_rows[:] = recent_data.get("songs", [])
        recent_list.delete(0, "end")
        for track in recent_rows:
            last_played = str(track.get("lastPlayedAt") or "").strip()
            suffix = f" · {last_played}" if last_played else ""
            recent_list.insert("end", f"{_format_track(track, show_favorite=False)}{suffix}")

        popular_data = api.most_played(limit=200)
        popular_rows[:] = popular_data.get("songs", [])
        popular_list.delete(0, "end")
        for track in popular_rows:
            popular_list.insert("end", _format_track(track, show_favorite=False, show_plays=True))

    def refresh_all(*, sync: bool = False) -> None:
        try:
            refresh_songs(sync=sync)
            refresh_catalogs()
            refresh_history()
            refresh_queue()
        except Exception as exc:
            status.set(f"失败：{exc}")

    def favorite() -> None:
        song = selected_song()
        if not song:
            status.set("请先选择歌曲")
            return
        try:
            api.update_song_state(song["id"], {"favorite": not bool(song.get("favorite"))})
            refresh_songs()
            refresh_catalogs()
        except Exception as exc:
            status.set(f"失败：{exc}")

    def enqueue() -> None:
        song = selected_song()
        if not song:
            status.set("请先选择歌曲")
            return
        try:
            api.enqueue({"mediaIds": [song["id"]]})
            refresh_queue()
            status.set("已加入队列")
        except Exception as exc:
            status.set(f"失败：{exc}")

    def remove_queue() -> None:
        row = selected_queue()
        if not row:
            status.set("请先选择队列项目")
            return
        try:
            api.remove_queue_item(row["id"])
            refresh_queue()
            status.set("已移出队列")
        except Exception as exc:
            status.set(f"失败：{exc}")

    def save_player() -> None:
        try:
            api.update_player(
                {
                    "repeatMode": repeat_var.get(),
                    "shuffle": bool(shuffle_var.get()),
                    "volume": float(volume_var.get()),
                }
            )
            status.set("播放器状态已保存")
            refresh_queue()
        except Exception as exc:
            status.set(f"失败：{exc}")

    def show_lyrics() -> None:
        song = selected_song()
        if not song:
            status.set("请先选择歌曲")
            return
        try:
            payload = api.song_lyrics(song["id"])
            text, kind = _render_lyrics_payload(payload)
            lyrics_header.set(f"{song.get('artist') or 'Unknown Artist'} — {song.get('title') or song.get('fileName') or 'Unknown Track'} · {kind}")
            lyrics_text.configure(state="normal")
            lyrics_text.delete("1.0", "end")
            lyrics_text.insert("1.0", text)
            lyrics_text.configure(state="disabled")
            lyrics_text.see("1.0")
            notebook.select(lyrics_tab)
            status.set("歌词已加载" if kind != "none" else "没有可用歌词")
        except Exception as exc:
            status.set(f"失败：{exc}")

    def browse_album() -> None:
        selected = album_list.curselection()
        if not selected:
            status.set("请先选择专辑")
            return
        row = album_rows[selected[0]]
        query.set(str(row.get("album") or ""))
        favorites.set(False)
        try:
            refresh_songs()
            notebook.select(songs_tab)
        except Exception as exc:
            status.set(f"失败：{exc}")

    def browse_artist() -> None:
        selected = artist_list.curselection()
        if not selected:
            status.set("请先选择艺术家")
            return
        row = artist_rows[selected[0]]
        query.set(str(row.get("artist") or row.get("name") or ""))
        favorites.set(False)
        try:
            refresh_songs()
            notebook.select(songs_tab)
        except Exception as exc:
            status.set(f"失败：{exc}")

    def clear_search() -> None:
        query.set("")
        favorites.set(False)
        try:
            refresh_songs()
        except Exception as exc:
            status.set(f"失败：{exc}")

    ui.ActionButton(top, text="搜索", command=lambda: refresh_songs(), kind="ghost", compact=True).pack(side="right", padx=(8, 0))
    ui.ActionButton(top, text="清除", command=clear_search, kind="ghost", compact=True).pack(side="right", padx=(8, 0))

    song_actions = tk.Frame(songs_tab, bg=ui.PANEL)
    song_actions.pack(fill="x", pady=(10, 0))
    ui.ActionButton(song_actions, text="同步音乐库", command=lambda: refresh_all(sync=True), kind="ghost", compact=True).pack(side="left")
    ui.ActionButton(song_actions, text="查看歌词", command=show_lyrics, kind="ghost", compact=True).pack(side="right")
    ui.ActionButton(song_actions, text="收藏/取消", command=favorite, kind="ghost", compact=True).pack(side="right", padx=(0, 6))
    ui.ActionButton(song_actions, text="加入队列", command=enqueue, kind="secondary", compact=True).pack(side="right", padx=(0, 6))

    album_actions = tk.Frame(albums_tab, bg=ui.PANEL)
    album_actions.pack(fill="x", pady=(10, 0))
    ui.ActionButton(album_actions, text="浏览所选专辑", command=browse_album, kind="secondary", compact=True).pack(side="right")

    artist_actions = tk.Frame(artists_tab, bg=ui.PANEL)
    artist_actions.pack(fill="x", pady=(10, 0))
    ui.ActionButton(artist_actions, text="浏览所选艺术家", command=browse_artist, kind="secondary", compact=True).pack(side="right")

    history_actions = tk.Frame(history_tab, bg=ui.PANEL)
    history_actions.pack(fill="x", pady=(10, 0))
    ui.ActionButton(history_actions, text="刷新历史", command=lambda: _guard(refresh_history, status), kind="ghost", compact=True).pack(side="right")

    queue_actions = tk.Frame(queue_tab, bg=ui.PANEL)
    queue_actions.pack(fill="x", pady=(10, 0))
    ui.ActionButton(queue_actions, text="保存播放器状态", command=save_player, kind="secondary", compact=True).pack(side="left")
    ui.ActionButton(
        queue_actions,
        text="清空队列",
        command=lambda: _guard(lambda: (api.clear_queue(), refresh_queue()), status, success="队列已清空"),
        kind="ghost",
        compact=True,
    ).pack(side="right")
    ui.ActionButton(queue_actions, text="移出队列", command=remove_queue, kind="ghost", compact=True).pack(side="right", padx=(0, 6))

    song_list.bind("<Double-Button-1>", lambda _event: show_lyrics())
    album_list.bind("<Double-Button-1>", lambda _event: browse_album())
    artist_list.bind("<Double-Button-1>", lambda _event: browse_artist())
    search_entry.bind("<Return>", lambda _event: refresh_songs())
    dialog.bind("<Escape>", lambda _event: clear_search())

    ui._label(shell, variable=status, size=8, color=ui.MUTED, bg=ui.BG).pack(anchor="w", pady=(8, 0))

    def close() -> None:
        window._music_workspace_window = None
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", close)
    refresh_all()


def _guard(callback, status: tk.StringVar, *, success: str | None = None) -> None:
    try:
        callback()
        if success:
            status.set(success)
    except Exception as exc:
        status.set(f"失败：{exc}")


def _add_music_entry(window, engine_module) -> None:
    panel = getattr(window, "_advanced_panel", None)
    if panel is None or getattr(window, "_galaxy_music_entry_built", False):
        return
    card = tk.Frame(panel, bg=ui.PANEL_2)
    card.pack(fill="x", pady=(10, 0))
    ui._divider(card, bg=ui.PANEL_2).pack(fill="x", pady=(0, 9))
    text = tk.Frame(card, bg=ui.PANEL_2)
    text.pack(side="left", fill="x", expand=True)
    ui._label(text, "音乐库", size=8, weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(text, "歌曲 · 专辑 · 艺术家 · 历史 · 歌词 · 队列", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(
        anchor="w", pady=(2, 0)
    )
    ui.ActionButton(
        card,
        text="打开音乐库",
        command=lambda: _show_music(window, engine_module),
        kind="secondary",
        compact=True,
    ).pack(side="right")
    window._galaxy_music_entry_built = True


def install_desktop_music(engine_module):
    cls = engine_module.EngineWindow
    if getattr(cls, "_galaxy_desktop_music_installed", False):
        return cls
    register_after_build_ui_hook(cls, "desktop-music", lambda window: _add_music_entry(window, engine_module), order=56)
    cls._galaxy_desktop_music_installed = True
    return cls


def run_desktop_music_self_test() -> None:
    assert callable(HeadlessMusicApi)
    assert _format_album({"album": "Discovery", "artist": "Daft Punk", "trackCount": 14}) == "Discovery — Daft Punk · 14 首"
    assert _format_artist({"artist": "Daft Punk", "albumCount": 2, "trackCount": 31}) == "Daft Punk · 2 张专辑 · 31 首"
    assert _format_timestamp(65.2) == "01:05"
    text, kind = _render_lyrics_payload({"lyrics": {"kind": "lrc", "synced": [{"time": 65.2, "text": "Hello"}], "text": ""}})
    assert kind == "lrc"
    assert text == "[01:05]  Hello"
    assert callable(getattr(HeadlessMusicApi, "list_albums", None))
    assert callable(getattr(HeadlessMusicApi, "list_artists", None))
    assert callable(getattr(HeadlessMusicApi, "recent", None))
    assert callable(getattr(HeadlessMusicApi, "most_played", None))
    assert callable(getattr(HeadlessMusicApi, "song_lyrics", None))
