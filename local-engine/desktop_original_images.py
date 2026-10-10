from __future__ import annotations

import threading
import tkinter as tk
from typing import Any

import bridge
import desktop_quick_download as quick
import desktop_ui as ui
from desktop_dpi import install_native_dpi_policy
from desktop_hooks import register_after_build_ui_hook, show_desktop_presenter
from image_download import start_image_download_job


def _image_urls(result: object) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(result, dict) or not result.get("success"):
        message = str(result.get("error") or result.get("message") or "无法解析网页图片") if isinstance(result, dict) else "无法解析网页图片"
        raise ValueError(message)
    data = result.get("data")
    if not isinstance(data, dict):
        raise ValueError("解析结果没有网页媒体数据")
    raw_images = data.get("images") if isinstance(data.get("images"), list) else []
    urls: list[str] = []
    for item in raw_images:
        if isinstance(item, dict):
            value = str(item.get("downloadUrl") or item.get("url") or "").strip()
        else:
            value = str(item or "").strip()
        if value and value not in urls:
            urls.append(value)
    if not urls:
        cover = str(data.get("cover") or "").strip()
        if cover:
            urls.append(cover)
    if not urls:
        raise ValueError("这个页面没有找到可下载的图片资源")
    return data, urls


def _download_original_images(window, engine_module) -> None:
    source_url = quick._text(getattr(window, "_quick_url_var", tk.StringVar()).get())
    if not source_url:
        window._quick_state_var.set("请先粘贴商品页或图片页面链接。")
        return
    try:
        source_url = engine_module._validated_source_url(source_url)
    except ValueError as exc:
        window._quick_state_var.set(str(exc))
        return

    browser = quick._browser_key(window._quick_browser_var.get())
    button = window._original_images_button
    button.state(["disabled"])
    window._quick_parse_button.state(["disabled"])
    window._quick_state_var.set("正在解析网页图片，并探测最大公开分辨率…")

    def worker() -> None:
        accepted = False
        message = ""
        count = 0
        try:
            result = bridge.parse_with_bundled_ytdlp(source_url, browser)
            data, images = _image_urls(result)
            count = len(images)
            payload = {
                "images": images,
                "title": str(data.get("title") or "Web images")[:120],
                "description": str(data.get("desc") or data.get("textContent") or "")[:4000],
                "author": data.get("author"),
                "publishedAt": data.get("publishedAt"),
                "sourceUrl": source_url,
                "platform": str(data.get("platform") or "web"),
                "package": count > 1,
                "archiveFormat": "zip",
            }
            accepted, message = start_image_download_job(payload)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)

        def finish() -> None:
            try:
                button.state(["!disabled"])
                window._quick_parse_button.state(["!disabled"])
                if accepted:
                    suffix = "；会优先尝试原尺寸/高分辨率 CDN 变体" if "homedepot.com" in source_url.lower() else ""
                    window._quick_state_var.set(f"已提交 {count} 张图片到本机原图下载{suffix}。")
                else:
                    window._quick_state_var.set(f"原图下载未启动：{message or '未知错误'}"[:280])
            except tk.TclError:
                pass

        try:
            window.after(0, finish)
        except tk.TclError:
            pass

    threading.Thread(target=worker, name="GalaxyOriginalImages", daemon=True).start()


def _build_original_images_strip(window, engine_module) -> None:
    panel = getattr(window, "_quick_download_panel", None)
    if panel is None or not panel.winfo_exists():
        return
    strip = tk.Frame(panel, bg=ui.PANEL_2)
    strip.pack(fill="x", pady=(12, 0))

    head = tk.Frame(strip, bg=ui.PANEL_2)
    head.pack(fill="x")
    ui._label(head, "网页原图 / 商品图集", size="body_sm", weight="bold", bg=ui.PANEL_2).pack(side="left", anchor="w")
    actions = tk.Frame(head, bg=ui.PANEL_2)
    actions.pack(side="right", anchor="e")

    window._original_images_button = ui.ActionButton(
        actions,
        text="下载页面原图",
        command=lambda: _download_original_images(window, engine_module),
        kind="secondary",
    )
    window._original_images_button.pack(side="right")

    ui._label(
        strip,
        "Home Depot 等商品页会自动去重缩略图，并按实际像素验证最大公开 CDN 尺寸后向下回退。",
        size="caption",
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
        wraplength=720,
        justify="left",
    ).pack(anchor="w", pady=(4, 0))

    window._original_images_strip = strip
    window._original_images_actions = actions


def _gallery_option_rows(window) -> list[tk.Misc]:
    rows: list[tk.Misc] = []
    archive = getattr(window, "_gallery_dl_archive_check", None)
    resume = getattr(window, "_gallery_dl_resume_check", None)
    output = getattr(window, "_gallery_dl_output_entry", None)
    rate = getattr(window, "_gallery_dl_rate_entry", None)
    after = getattr(window, "_gallery_dl_date_after_entry", None)

    for widget in (archive, resume):
        if widget is not None:
            rows.append(widget.master)
    for widget in (output, rate, after):
        if widget is None:
            continue
        parent = widget.master
        if getattr(parent, "master", None) is not None:
            parent = parent.master
        if getattr(parent, "master", None) is not None:
            parent = parent.master
        rows.append(parent)

    unique: list[tk.Misc] = []
    seen: set[int] = set()
    for row in rows:
        identity = id(row)
        if identity not in seen:
            seen.add(identity)
            unique.append(row)
    return unique


def _compact_gallery_fallback(window) -> None:
    """Move secondary gallery-dl controls behind progressive disclosure."""
    button = getattr(window, "_gallery_dl_fallback_button", None)
    strip = getattr(window, "_original_images_strip", None)
    actions = getattr(window, "_original_images_actions", None)
    if button is None or strip is None or actions is None or getattr(window, "_galaxy_gallery_compact_installed", False):
        return

    rows = _gallery_option_rows(window)
    for row in rows:
        try:
            row.pack_forget()
        except tk.TclError:
            pass

    row = button.master
    card = row.master
    button.configure(text="开始 gallery-dl")
    options_state = tk.BooleanVar(master=window, value=False)

    def toggle_options() -> None:
        expanded = not bool(options_state.get())
        options_state.set(expanded)
        if expanded:
            for index, item in enumerate(rows):
                try:
                    item.pack(fill="x", pady=((7 if index < 2 else 8), 0))
                except tk.TclError:
                    pass
            options_toggle.configure(text="收起高级选项")
        else:
            for item in rows:
                try:
                    item.pack_forget()
                except tk.TclError:
                    pass
            options_toggle.configure(text="高级选项")
        try:
            window.update_idletasks()
        except tk.TclError:
            pass

    options_toggle = ui.ActionButton(
        row,
        text="高级选项",
        command=toggle_options,
        kind="ghost",
        compact=True,
    )
    options_toggle.pack(side="right", padx=(8, 0), before=button)

    fallback_state = tk.BooleanVar(master=window, value=False)
    card.pack_forget()

    def toggle_fallback() -> None:
        visible = not bool(fallback_state.get())
        fallback_state.set(visible)
        if visible:
            card.pack(fill="x", pady=(10, 0))
            fallback_toggle.configure(text="收起图库备用")
        else:
            card.pack_forget()
            fallback_toggle.configure(text="图库备用")
        try:
            window.update_idletasks()
        except tk.TclError:
            pass

    fallback_toggle = ui.ActionButton(
        actions,
        text="图库备用",
        command=toggle_fallback,
        kind="ghost",
        compact=True,
    )
    fallback_toggle.pack(side="right", padx=(0, 8), before=window._original_images_button)

    window._gallery_dl_options_expanded = options_state
    window._gallery_dl_options_toggle = options_toggle
    window._gallery_dl_compact_rows = rows
    window._gallery_dl_fallback_expanded = fallback_state
    window._gallery_dl_fallback_toggle = fallback_toggle
    window._gallery_dl_fallback_card = card
    window._galaxy_gallery_compact_installed = True


def _stabilize_queue_header_controls(window) -> None:
    """Move queue actions below the title so late presenter buttons cannot squeeze them.

    The V1.7 rail is intentionally compact. Packing every action into the title
    row made buttons collapse to 20-30px at a 1020px viewport. The toolbar now
    lives as a sibling *below* the header, so the title row and toolbar no longer
    compete for width. Every visible action keeps its 44px target and readable
    label even if later modules add header controls.
    """
    pause = getattr(window, "_queue_pause_button", None)
    history = getattr(window, "_history_button", None)
    clear = getattr(window, "_queue_clear_button", None)
    transcript = getattr(window, "_transcript_button", None)
    if pause is None or history is None or clear is None or getattr(window, "_galaxy_queue_header_stable", False):
        return
    head = clear.master
    rail = head.master

    frames = [child for child in head.winfo_children() if isinstance(child, tk.Frame)]
    copy = frames[0] if frames else None
    if copy is None:
        return

    for widget in (pause, history, clear, transcript):
        if widget is None:
            continue
        try:
            widget.destroy()
        except tk.TclError:
            pass
    try:
        copy.pack_forget()
    except tk.TclError:
        pass
    copy.pack(fill="x", anchor="w")

    toolbar = tk.Frame(rail, bg=ui.PANEL)
    toolbar.pack(fill="x", pady=(10, 0), after=head)

    def toggle_pause() -> None:
        toggle = getattr(window, "toggle_queue_paused", None)
        if callable(toggle):
            toggle()

    window._queue_pause_button = ui.ActionButton(
        toolbar,
        text="继续队列" if bool(getattr(window, "queue_paused", False)) else "暂停队列",
        command=toggle_pause,
        kind="secondary",
        compact=True,
    )
    window._queue_pause_button.pack(fill="x")

    secondary = tk.Frame(toolbar, bg=ui.PANEL)
    secondary.pack(fill="x", pady=(7, 0))
    window._history_button = ui.ActionButton(
        secondary,
        text="历史",
        command=lambda: show_desktop_presenter(window, "history"),
        kind="ghost",
        compact=True,
    )
    window._history_button.pack(side="left")

    if transcript is not None:
        window._transcript_button = ui.ActionButton(
            secondary,
            text="Transcript",
            command=lambda: show_desktop_presenter(window, "transcript"),
            kind="ghost",
            compact=True,
        )
        window._transcript_button.pack(side="left", padx=(6, 0))

    def clear_queue() -> None:
        clear_fn = getattr(window, "clear_queued_jobs", None)
        if callable(clear_fn):
            clear_fn()

    window._queue_clear_button = ui.ActionButton(
        secondary,
        text="清空",
        command=clear_queue,
        kind="ghost",
        compact=True,
    )
    window._queue_clear_button.pack(side="right")
    if not getattr(window, "pending_jobs", []):
        window._queue_clear_button.state(["disabled"])

    window._queue_header_toolbar = toolbar
    window._galaxy_queue_header_stable = True


def install_desktop_original_images(engine_module):
    window_cls = engine_module.EngineWindow
    install_native_dpi_policy(engine_module)
    if getattr(window_cls, "_galaxy_desktop_original_images_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-original-images",
        lambda window: _build_original_images_strip(window, engine_module),
        order=45,
    )
    register_after_build_ui_hook(
        window_cls,
        "desktop-gallery-compact",
        _compact_gallery_fallback,
        order=48,
    )
    register_after_build_ui_hook(
        window_cls,
        "desktop-queue-header-stability",
        _stabilize_queue_header_controls,
        order=220,
    )
    window_cls._galaxy_desktop_original_images_installed = True
    return window_cls


def run_self_test() -> None:
    result = {
        "success": True,
        "data": {
            "title": "Product",
            "images": [
                {"url": "https://images.thdstatic.com/productImages/a/item_100.jpg"},
                {"downloadUrl": "https://images.thdstatic.com/productImages/a/item_600.jpg"},
            ],
        },
    }
    data, urls = _image_urls(result)
    assert data["title"] == "Product"
    assert len(urls) == 2
    assert urls[0].endswith("_100.jpg")
    assert callable(_compact_gallery_fallback)
    assert callable(_stabilize_queue_header_controls)


if __name__ == "__main__":
    run_self_test()
    print("Desktop original-images self-test passed")
