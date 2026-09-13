from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Any

import desktop_ui as ui
from telegram_download import (
    TelegramTransferError,
    browse_public_telegram,
    browse_telegram_chat,
    download_public_telegram,
    download_telegram_chat,
    list_telegram_chats,
)


def _human_size(value: object) -> str:
    try:
        size = max(0, int(value or 0))
    except (TypeError, ValueError):
        size = 0
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(size)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{size} B"


def _kind_label(kind: object) -> str:
    return {"image": "图片", "video": "视频", "document": "文档"}.get(str(kind or "").lower(), "—")


def _message_values(message: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(message.get("messageId") or ""),
        _kind_label(message.get("mediaKind")),
        str(message.get("fileName") or "")[:80],
        _human_size(message.get("sizeBytes")),
        str(message.get("date") or "")[:24],
        str(message.get("text") or "")[:140],
    )


def build_telegram_download_tab(notebook: ttk.Notebook, dialog: tk.Misc, engine_module) -> tk.Frame:
    tab = tk.Frame(notebook, bg=ui.PANEL, padx=16, pady=14)
    notebook.add(tab, text="Telegram 下载")

    ui._label(tab, "Telegram 下载 / Chat Browser", size=10, weight="bold").pack(anchor="w")
    ui._label(
        tab,
        "公共帖子 / 频道、Chat Browser 与批量媒体下载均通过已配置的 User Session adapter；Bot Token 不用于读取任意频道历史。",
        size=7,
        color=ui.SUBTLE,
    ).pack(anchor="w", pady=(3, 9))

    status_var = tk.StringVar(value="请输入公共 t.me 链接 / @username，或搜索 User Session 中的 Chat。")
    source_var = tk.StringVar(value="")
    chat_query_var = tk.StringVar(value="")
    chat_choice_var = tk.StringVar(value="")
    limit_var = tk.StringVar(value="50")
    image_var = tk.BooleanVar(value=True)
    video_var = tk.BooleanVar(value=True)
    document_var = tk.BooleanVar(value=True)

    source_card = tk.Frame(
        tab,
        bg=ui.PANEL_2,
        padx=12,
        pady=10,
        highlightthickness=1,
        highlightbackground=ui.BORDER_SOFT,
    )
    source_card.pack(fill="x")

    public_row = tk.Frame(source_card, bg=ui.PANEL_2)
    public_row.pack(fill="x")
    public_field = tk.Frame(public_row, bg=ui.PANEL_2)
    public_field.pack(side="left", fill="x", expand=True)
    ui._label(public_field, "Public Post / Channel", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w")
    source_entry = tk.Entry(
        public_field,
        textvariable=source_var,
        bg=ui.PANEL_3,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
        font=("Segoe UI", 8),
    )
    source_entry.pack(fill="x", pady=(3, 0), ipady=6)

    limit_field = tk.Frame(public_row, bg=ui.PANEL_2)
    limit_field.pack(side="left", padx=(10, 0))
    ui._label(limit_field, "最多消息", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w")
    limit_spin = tk.Spinbox(
        limit_field,
        from_=1,
        to=100,
        textvariable=limit_var,
        width=7,
        bg=ui.PANEL_3,
        fg=ui.TEXT,
        buttonbackground=ui.PANEL_3,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
        font=("Segoe UI", 8),
    )
    limit_spin.pack(pady=(3, 0), ipady=5)

    public_button = ui.ActionButton(
        public_row,
        text="浏览公共来源",
        command=lambda: None,
        kind="secondary",
        compact=True,
    )
    public_button.pack(side="right", padx=(10, 0), pady=(15, 0))

    chat_row = tk.Frame(source_card, bg=ui.PANEL_2)
    chat_row.pack(fill="x", pady=(9, 0))
    chat_search_field = tk.Frame(chat_row, bg=ui.PANEL_2)
    chat_search_field.pack(side="left", fill="x", expand=True)
    ui._label(chat_search_field, "Chat Browser 搜索", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w")
    chat_query_entry = tk.Entry(
        chat_search_field,
        textvariable=chat_query_var,
        bg=ui.PANEL_3,
        fg=ui.TEXT,
        insertbackground=ui.TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ui.BORDER,
        highlightcolor=ui.ACCENT,
        font=("Segoe UI", 8),
    )
    chat_query_entry.pack(fill="x", pady=(3, 0), ipady=6)

    search_chats_button = ui.ActionButton(
        chat_row,
        text="搜索 Chat",
        command=lambda: None,
        kind="ghost",
        compact=True,
    )
    search_chats_button.pack(side="left", padx=(8, 0), pady=(15, 0))

    chat_choice_field = tk.Frame(chat_row, bg=ui.PANEL_2)
    chat_choice_field.pack(side="left", fill="x", expand=True, padx=(10, 0))
    ui._label(chat_choice_field, "Chat", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(anchor="w")
    chat_combo = ttk.Combobox(chat_choice_field, textvariable=chat_choice_var, state="readonly", width=32)
    chat_combo.pack(fill="x", pady=(3, 0), ipady=4)

    browse_chat_button = ui.ActionButton(
        chat_row,
        text="浏览 Chat",
        command=lambda: None,
        kind="secondary",
        compact=True,
    )
    browse_chat_button.pack(side="right", padx=(8, 0), pady=(15, 0))

    filter_row = tk.Frame(source_card, bg=ui.PANEL_2)
    filter_row.pack(fill="x", pady=(9, 0))
    ui._label(filter_row, "媒体类型", size=7, color=ui.SUBTLE, bg=ui.PANEL_2).pack(side="left")
    filter_controls: list[tk.Checkbutton] = []
    for text, variable in (("图片", image_var), ("视频", video_var), ("文档", document_var)):
        control = tk.Checkbutton(
            filter_row,
            text=text,
            variable=variable,
            onvalue=True,
            offvalue=False,
            takefocus=True,
            bg=ui.PANEL_2,
            fg=ui.TEXT,
            activebackground=ui.PANEL_2,
            activeforeground=ui.TEXT,
            selectcolor=ui.PANEL_3,
            font=("Segoe UI", 8),
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground=ui.BORDER_SOFT,
            highlightcolor=ui.ACCENT,
            cursor="hand2",
        )
        control.pack(side="left", padx=(8, 0))
        filter_controls.append(control)

    ui._label(
        filter_row,
        "最大 100 条；下载文件只写入 Galaxy 管理的 Telegram 目录。",
        size=7,
        color=ui.MUTED,
        bg=ui.PANEL_2,
    ).pack(side="right")

    result_card = tk.Frame(tab, bg=ui.PANEL, pady=10)
    result_card.pack(fill="both", expand=True)
    table_frame = tk.Frame(result_card, bg=ui.PANEL)
    table_frame.pack(fill="both", expand=True)

    style = ttk.Style(dialog)
    style.configure(
        "GalaxyTelegram.Treeview",
        background=ui.PANEL_2,
        fieldbackground=ui.PANEL_2,
        foreground=ui.TEXT,
        borderwidth=0,
        rowheight=28,
        font=("Segoe UI", 8),
    )
    style.configure(
        "GalaxyTelegram.Treeview.Heading",
        background=ui.PANEL_3,
        foreground=ui.MUTED,
        relief="flat",
        font=("Segoe UI", 8, "bold"),
    )
    style.map(
        "GalaxyTelegram.Treeview",
        background=[("selected", ui.ACCENT)],
        foreground=[("selected", "#ffffff")],
    )

    columns = ("id", "type", "name", "size", "date", "text")
    tree = ttk.Treeview(
        table_frame,
        columns=columns,
        show="headings",
        selectmode="extended",
        style="GalaxyTelegram.Treeview",
        height=10,
    )
    headings = {
        "id": ("ID", 68, "center"),
        "type": ("类型", 60, "center"),
        "name": ("文件", 180, "w"),
        "size": ("大小", 76, "e"),
        "date": ("日期", 132, "w"),
        "text": ("消息", 260, "w"),
    }
    for key, (title, width, anchor) in headings.items():
        tree.heading(key, text=title, anchor=anchor)
        tree.column(key, width=width, minwidth=52, anchor=anchor, stretch=key in {"name", "text"})
    scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    footer = tk.Frame(tab, bg=ui.PANEL)
    footer.pack(fill="x", pady=(2, 0))
    ui._label(footer, variable=status_var, size=7, color=ui.MUTED).pack(side="left", fill="x", expand=True)

    download_loaded_button = ui.ActionButton(
        footer,
        text="下载当前列表",
        command=lambda: None,
        kind="ghost",
        compact=True,
    )
    download_loaded_button.pack(side="right")
    download_selected_button = ui.ActionButton(
        footer,
        text="下载所选",
        command=lambda: None,
        kind="secondary",
        compact=True,
    )
    download_selected_button.pack(side="right", padx=(0, 7))

    chat_keys: dict[str, str] = {}
    message_ids: dict[str, int] = {}
    current_source: dict[str, Any] = {}
    busy_buttons = [public_button, search_chats_button, browse_chat_button, download_loaded_button, download_selected_button]

    def selected_media_kinds() -> list[str]:
        kinds: list[str] = []
        if image_var.get():
            kinds.append("image")
        if video_var.get():
            kinds.append("video")
        if document_var.get():
            kinds.append("document")
        return kinds

    def parse_limit() -> int:
        try:
            return max(1, min(int(limit_var.get().strip()), 100))
        except (TypeError, ValueError):
            return 50

    def set_busy(busy: bool) -> None:
        for control in busy_buttons:
            try:
                control.state(["disabled" if busy else "!disabled"])
            except (AttributeError, tk.TclError):
                pass
        for control in (source_entry, chat_query_entry, limit_spin, *filter_controls):
            try:
                control.configure(state="disabled" if busy else "normal")
            except tk.TclError:
                pass
        try:
            chat_combo.configure(state="disabled" if busy else "readonly")
        except tk.TclError:
            pass

    def render_messages(messages: list[dict[str, Any]], *, source_context: dict[str, Any]) -> None:
        for item in tree.get_children():
            tree.delete(item)
        message_ids.clear()
        current_source.clear()
        current_source.update(source_context)
        for index, message in enumerate(messages):
            try:
                message_id = int(message.get("messageId") or 0)
            except (TypeError, ValueError):
                continue
            if message_id < 1:
                continue
            item_id = f"telegram-{message_id}-{index}"
            message_ids[item_id] = message_id
            tree.insert("", "end", iid=item_id, values=_message_values(message))
        if messages:
            first = tree.get_children()[0]
            tree.focus(first)
            tree.selection_set(first)

    def finish_error(prefix: str, error: BaseException) -> None:
        set_busy(False)
        detail = " ".join(str(error or "").split())[:220]
        status_var.set(f"{prefix}：{detail or '未知错误'}")

    def browse_public() -> None:
        source = source_var.get().strip()
        limit = parse_limit()
        kinds = selected_media_kinds()
        if not source:
            status_var.set("请输入 public t.me / telegram.me 链接或 @username。")
            return
        if not kinds:
            status_var.set("至少选择一种媒体类型。")
            return
        set_busy(True)
        status_var.set("正在通过 User Session adapter 读取公共来源…")

        def worker() -> None:
            try:
                result = browse_public_telegram(engine_module, source, limit=limit, media_kinds=kinds)
                messages = list(result.get("messages") or [])
                context = {"kind": "public", "source": source, "mediaKinds": list(kinds)}

                def finish() -> None:
                    set_busy(False)
                    render_messages(messages, source_context=context)
                    status_var.set(f"已加载 {len(messages)} 条公共消息。" if messages else "没有找到符合筛选条件的媒体消息。")

                dialog.after(0, finish)
            except Exception as exc:  # noqa: BLE001
                try:
                    dialog.after(0, lambda error=exc: finish_error("公共来源读取失败", error))
                except tk.TclError:
                    return

        threading.Thread(target=worker, name="GalaxyTelegramBrowsePublic", daemon=True).start()

    def search_chats() -> None:
        query = chat_query_var.get().strip()
        limit = parse_limit()
        set_busy(True)
        status_var.set("正在读取 User Session Chat 列表…")

        def worker() -> None:
            try:
                result = list_telegram_chats(engine_module, query=query, limit=limit)
                rows = list(result.get("chats") or [])

                def finish() -> None:
                    set_busy(False)
                    chat_keys.clear()
                    labels: list[str] = []
                    for row in rows:
                        key = str(row.get("chatKey") or "")
                        title = str(row.get("title") or row.get("username") or key or "Chat")[:80]
                        username = str(row.get("username") or "")
                        kind = str(row.get("type") or "")
                        suffix = " · ".join(part for part in (kind, f"@{username}" if username else "") if part)
                        label = f"{title} — {suffix}" if suffix else title
                        if label in chat_keys:
                            label = f"{label} [{len(labels) + 1}]"
                        chat_keys[label] = key
                        labels.append(label)
                    chat_combo.configure(values=tuple(labels))
                    chat_choice_var.set(labels[0] if labels else "")
                    status_var.set(f"找到 {len(labels)} 个 Chat。" if labels else "没有找到 Chat。")

                dialog.after(0, finish)
            except Exception as exc:  # noqa: BLE001
                try:
                    dialog.after(0, lambda error=exc: finish_error("Chat 搜索失败", error))
                except tk.TclError:
                    return

        threading.Thread(target=worker, name="GalaxyTelegramSearchChats", daemon=True).start()

    def browse_chat() -> None:
        choice = chat_choice_var.get().strip()
        chat_key = chat_keys.get(choice, "")
        limit = parse_limit()
        kinds = selected_media_kinds()
        if not chat_key:
            status_var.set("请先搜索并选择一个 Chat。")
            return
        if not kinds:
            status_var.set("至少选择一种媒体类型。")
            return
        set_busy(True)
        status_var.set("正在读取 Chat 消息…")

        def worker() -> None:
            try:
                result = browse_telegram_chat(engine_module, chat_key, limit=limit, media_kinds=kinds)
                messages = list(result.get("messages") or [])
                context = {"kind": "chat", "chatKey": chat_key, "mediaKinds": list(kinds)}

                def finish() -> None:
                    set_busy(False)
                    render_messages(messages, source_context=context)
                    status_var.set(f"已加载 {len(messages)} 条 Chat 消息。" if messages else "没有找到符合筛选条件的媒体消息。")

                dialog.after(0, finish)
            except Exception as exc:  # noqa: BLE001
                try:
                    dialog.after(0, lambda error=exc: finish_error("Chat 读取失败", error))
                except tk.TclError:
                    return

        threading.Thread(target=worker, name="GalaxyTelegramBrowseChat", daemon=True).start()

    def start_download(*, selected_only: bool) -> None:
        items = list(tree.selection()) if selected_only else list(tree.get_children())
        ids = [message_ids[item] for item in items if item in message_ids]
        context = dict(current_source)
        if not ids:
            status_var.set("请先加载消息并选择要下载的项目。" if selected_only else "当前列表没有可下载项目。")
            return
        ids = ids[:100]
        kinds = list(context.get("mediaKinds") or ["image", "video", "document"])
        set_busy(True)
        status_var.set(f"正在下载 {len(ids)} 个 Telegram 项目…")

        def worker() -> None:
            try:
                if context.get("kind") == "public":
                    result = download_public_telegram(
                        engine_module,
                        context.get("source", ""),
                        message_ids=ids,
                        limit=len(ids),
                        media_kinds=kinds,
                    )
                elif context.get("kind") == "chat":
                    result = download_telegram_chat(
                        engine_module,
                        context.get("chatKey", ""),
                        message_ids=ids,
                        limit=len(ids),
                        media_kinds=kinds,
                    )
                else:
                    raise TelegramTransferError("请先加载一个 Telegram 来源")
                rows = list(result.get("items") or [])
                names = [str(row.get("fileName") or "") for row in rows if row.get("fileName")]
                preview = "、".join(names[:3])
                suffix = f" · {preview}" if preview else ""
                detail = f"下载完成 · {len(rows)} 个文件{suffix}"

                def finish() -> None:
                    set_busy(False)
                    status_var.set(detail[:260])

                dialog.after(0, finish)
            except Exception as exc:  # noqa: BLE001
                try:
                    dialog.after(0, lambda error=exc: finish_error("Telegram 下载失败", error))
                except tk.TclError:
                    return

        threading.Thread(target=worker, name="GalaxyTelegramDownload", daemon=True).start()

    public_button.configure(command=browse_public)
    search_chats_button.configure(command=search_chats)
    browse_chat_button.configure(command=browse_chat)
    download_selected_button.configure(command=lambda: start_download(selected_only=True))
    download_loaded_button.configure(command=lambda: start_download(selected_only=False))
    source_entry.bind("<Return>", lambda _event: browse_public())
    chat_query_entry.bind("<Return>", lambda _event: search_chats())

    return tab


def run_desktop_telegram_download_self_test() -> None:
    assert _human_size(0) == "0 B"
    assert _human_size(1024) == "1.0 KB"
    assert _kind_label("image") == "图片"
    assert _kind_label("video") == "视频"
    assert _kind_label("document") == "文档"
