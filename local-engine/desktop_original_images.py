from __future__ import annotations

import threading
import tkinter as tk
from typing import Any

import bridge
import desktop_quick_download as quick
import desktop_ui as ui
from desktop_dpi import install_native_dpi_policy
from desktop_hooks import register_after_build_ui_hook
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
    copy = tk.Frame(strip, bg=ui.PANEL_2)
    copy.pack(side="left", fill="x", expand=True)
    ui._label(copy, "网页原图 / 商品图集", size="body_sm", weight="bold", bg=ui.PANEL_2).pack(anchor="w")
    ui._label(
        copy,
        "Home Depot 等商品页会自动去重缩略图，并按最大公开 CDN 尺寸向下回退。",
        size="caption",
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
    ).pack(anchor="w", pady=(2, 0))
    window._original_images_button = ui.ActionButton(
        strip,
        text="下载页面原图",
        command=lambda: _download_original_images(window, engine_module),
        kind="secondary",
    )
    window._original_images_button.pack(side="right", padx=(14, 0))


def install_desktop_original_images(engine_module):
    window_cls = engine_module.EngineWindow
    # DPI policy is independent from Home Depot, but this module is installed
    # on every native run through image_archive_policy and is therefore a stable
    # place to restore Windows' real DPI after legacy composition forced 1.0.
    install_native_dpi_policy(engine_module)
    if getattr(window_cls, "_galaxy_desktop_original_images_installed", False):
        return window_cls
    register_after_build_ui_hook(
        window_cls,
        "desktop-original-images",
        lambda window: _build_original_images_strip(window, engine_module),
        order=45,
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


if __name__ == "__main__":
    run_self_test()
    print("Desktop original-images self-test passed")
