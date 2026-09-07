from __future__ import annotations

import io
import math
import tkinter as tk
import zipfile
from contextlib import suppress
from typing import Any, Callable

from PIL import Image, ImageOps, ImageTk, UnidentifiedImageError
from tkinter import ttk

import desktop_ui as ui
from reader_workspace import (
    ReaderWorkspaceError,
    book_file_path,
    cbz_pages,
    update_reader_settings,
    update_reading_position,
)

MAX_CBZ_PAGE_BYTES = 256 * 1024 * 1024
MAX_CBZ_PAGE_PIXELS = 100_000_000
VERTICAL_WINDOW_PAGES = 6
_SUPPORTED_MODES = ("vertical", "single", "double", "fit-width")
_SUPPORTED_DIRECTIONS = ("ltr", "rtl")


class DesktopCbzReaderError(RuntimeError):
    pass


def _clamp_page_index(total: int, index: object) -> int:
    safe_total = max(0, int(total))
    if safe_total <= 0:
        return 0
    try:
        value = int(index)
    except (TypeError, ValueError):
        value = 0
    return max(0, min(value, safe_total - 1))


def _normalize_mode(value: object) -> str:
    clean = str(value or "vertical").strip().lower()
    return clean if clean in _SUPPORTED_MODES else "vertical"


def _normalize_direction(value: object) -> str:
    clean = str(value or "ltr").strip().lower()
    return clean if clean in _SUPPORTED_DIRECTIONS else "ltr"


def _visible_page_indices(
    total: int,
    index: object,
    mode: object,
    direction: object,
    *,
    vertical_window: int = VERTICAL_WINDOW_PAGES,
) -> list[int]:
    safe_total = max(0, int(total))
    if safe_total <= 0:
        return []
    start = _clamp_page_index(safe_total, index)
    clean_mode = _normalize_mode(mode)
    clean_direction = _normalize_direction(direction)
    if clean_mode == "double":
        start = (start // 2) * 2
        values = list(range(start, min(safe_total, start + 2)))
        if clean_direction == "rtl":
            values.reverse()
        return values
    if clean_mode == "vertical":
        count = max(1, min(int(vertical_window), 12))
        return list(range(start, min(safe_total, start + count)))
    return [start]


def _navigation_step(mode: object) -> int:
    return 2 if _normalize_mode(mode) == "double" else (VERTICAL_WINDOW_PAGES if _normalize_mode(mode) == "vertical" else 1)


def _fit_dimensions(
    image_width: int,
    image_height: int,
    viewport_width: int,
    viewport_height: int,
    mode: object,
) -> tuple[int, int]:
    width = max(1, int(image_width))
    height = max(1, int(image_height))
    view_width = max(120, int(viewport_width))
    view_height = max(120, int(viewport_height))
    clean_mode = _normalize_mode(mode)

    if clean_mode == "double":
        max_width = max(80, (view_width - 54) // 2)
        max_height = max(80, view_height - 50)
        scale = min(max_width / width, max_height / height, 1.0)
    elif clean_mode == "single":
        max_width = max(100, view_width - 40)
        max_height = max(100, view_height - 40)
        scale = min(max_width / width, max_height / height, 1.0)
    else:
        max_width = max(100, view_width - 46)
        scale = min(max_width / width, 1.0)

    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _opaque_locator(page_index: object) -> str:
    try:
        index = max(0, int(page_index))
    except (TypeError, ValueError):
        index = 0
    return f"cbz-page:{index + 1}"


def _locator_page_index(locator: object, total: int, progress_percent: object = 0) -> int:
    text = str(locator or "").strip().lower()
    if text.startswith("cbz-page:"):
        with suppress(ValueError):
            return _clamp_page_index(total, int(text.split(":", 1)[1]) - 1)
    try:
        progress = float(progress_percent)
    except (TypeError, ValueError):
        progress = 0.0
    if not math.isfinite(progress):
        progress = 0.0
    if total <= 1:
        return 0
    return _clamp_page_index(total, round(max(0.0, min(progress, 100.0)) / 100.0 * (total - 1)))


def _read_cbz_page_bytes(engine_module, book_id: object, page_name: object) -> bytes:
    requested = str(page_name or "").replace("\\", "/").strip()
    if not requested:
        raise DesktopCbzReaderError("CBZ page is empty")
    allowed = set(cbz_pages(engine_module, book_id, limit=5000))
    if requested not in allowed:
        raise DesktopCbzReaderError("CBZ page is outside the managed page list")

    archive_path = book_file_path(engine_module, book_id)
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            matches = [info for info in archive.infolist() if info.filename.replace("\\", "/") == requested]
            if len(matches) != 1:
                raise DesktopCbzReaderError("CBZ page member is missing or ambiguous")
            info = matches[0]
            if info.is_dir() or info.flag_bits & 0x1:
                raise DesktopCbzReaderError("CBZ page member is unavailable")
            if info.file_size <= 0 or info.file_size > MAX_CBZ_PAGE_BYTES:
                raise DesktopCbzReaderError("CBZ page exceeds the safe size limit")
            with archive.open(info, "r") as source:
                payload = source.read(MAX_CBZ_PAGE_BYTES + 1)
    except (OSError, zipfile.BadZipFile) as exc:
        raise DesktopCbzReaderError("CBZ archive is unavailable") from exc
    if not payload or len(payload) > MAX_CBZ_PAGE_BYTES:
        raise DesktopCbzReaderError("CBZ page exceeds the safe size limit")
    return payload


def _decode_page(payload: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(payload)) as source:
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_CBZ_PAGE_PIXELS:
                raise DesktopCbzReaderError("CBZ page dimensions exceed the safe limit")
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.load()
            return image
    except DesktopCbzReaderError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DesktopCbzReaderError("CBZ page image cannot be decoded") from exc


def _settings_from_book(book: dict[str, Any]) -> tuple[str, str, bool]:
    raw = book.get("settings") if isinstance(book, dict) else None
    settings = raw if isinstance(raw, dict) else {}
    return (
        _normalize_mode(settings.get("readingMode") or "vertical"),
        _normalize_direction(settings.get("mangaDirection") or "ltr"),
        bool(settings.get("focusMode", False)),
    )


def show_cbz_reader(
    parent: tk.Misc,
    engine_module,
    book: dict[str, Any],
    *,
    on_change: Callable[[], None] | None = None,
) -> None:
    if str(book.get("format") or "").strip().lower() != "cbz":
        raise DesktopCbzReaderError("请选择 CBZ 书籍")
    book_id = str(book.get("id") or "")
    pages = cbz_pages(engine_module, book_id, limit=5000)
    if not pages:
        raise DesktopCbzReaderError("CBZ 没有可显示的图片页面")

    mode, direction, focus = _settings_from_book(book)
    state: dict[str, Any] = {
        "index": _locator_page_index(book.get("locator"), len(pages), book.get("progressPercent")),
        "photos": [],
        "render_after": None,
    }

    dialog = tk.Toplevel(parent)
    dialog.title(f"{str(book.get('title') or 'CBZ')} · CBZ Reader")
    dialog.geometry("1120x800")
    dialog.minsize(760, 560)
    dialog.configure(bg=ui.BG)
    dialog.transient(parent)

    shell = tk.Frame(dialog, bg=ui.BG, padx=14, pady=12)
    shell.pack(fill="both", expand=True)
    toolbar = tk.Frame(shell, bg=ui.BG)
    toolbar.pack(fill="x", pady=(0, 10))
    title_var = tk.StringVar(value=str(book.get("title") or "CBZ"))
    status_var = tk.StringVar(value="正在加载…")
    page_var = tk.StringVar(value="")
    mode_var = tk.StringVar(value=mode)
    direction_var = tk.StringVar(value=direction)
    focus_var = tk.BooleanVar(value=focus)

    ui._label(toolbar, variable=title_var, size=11, weight="bold", bg=ui.BG).pack(side="left", padx=(0, 12))
    previous_button = ui.ActionButton(toolbar, text="上一页", command=lambda: navigate(-1), kind="ghost")
    previous_button.pack(side="left", padx=(0, 6))
    next_button = ui.ActionButton(toolbar, text="下一页", command=lambda: navigate(1), kind="secondary")
    next_button.pack(side="left", padx=(0, 12))

    ttk.Label(toolbar, text="模式").pack(side="left", padx=(0, 5))
    mode_combo = ttk.Combobox(toolbar, textvariable=mode_var, values=_SUPPORTED_MODES, state="readonly", width=11)
    mode_combo.pack(side="left", padx=(0, 10))
    ttk.Label(toolbar, text="方向").pack(side="left", padx=(0, 5))
    direction_combo = ttk.Combobox(toolbar, textvariable=direction_var, values=_SUPPORTED_DIRECTIONS, state="readonly", width=6)
    direction_combo.pack(side="left", padx=(0, 10))
    focus_check = tk.Checkbutton(
        toolbar,
        text="Focus",
        variable=focus_var,
        bg=ui.BG,
        fg=ui.TEXT,
        selectcolor=ui.PANEL,
        activebackground=ui.BG,
        activeforeground=ui.TEXT,
        command=lambda: apply_focus(True),
    )
    focus_check.pack(side="left")
    ui._label(toolbar, variable=page_var, size=8, color=ui.MUTED, bg=ui.BG).pack(side="right")

    viewport = tk.Frame(shell, bg=ui.PANEL, highlightthickness=1, highlightbackground=ui.BORDER)
    viewport.pack(fill="both", expand=True)
    canvas = tk.Canvas(viewport, bg=ui.BG, bd=0, highlightthickness=0)
    scrollbar = tk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    status_bar = tk.Frame(shell, bg=ui.BG)
    status_bar.pack(fill="x", pady=(8, 0))
    ui._label(status_bar, variable=status_var, size=8, color=ui.MUTED, bg=ui.BG).pack(side="left")
    ui._label(
        status_bar,
        "←/→ 翻页 · PgUp/PgDn · Home/End · F Focus · Esc 退出 Focus/关闭",
        size=7,
        color=ui.SUBTLE,
        bg=ui.BG,
    ).pack(side="right")

    def persist_position() -> None:
        index = _clamp_page_index(len(pages), state["index"])
        visible = _visible_page_indices(len(pages), index, mode_var.get(), direction_var.get())
        logical_last = max(visible) if visible else index
        progress = round(((logical_last + 1) / len(pages)) * 100.0, 3)
        locator = _opaque_locator(index)
        update_reading_position(engine_module, book_id, progress, locator)
        book["progressPercent"] = progress
        book["locator"] = locator

    def persist_settings() -> None:
        saved = update_reader_settings(
            engine_module,
            book_id,
            {
                "readingMode": _normalize_mode(mode_var.get()),
                "mangaDirection": _normalize_direction(direction_var.get()),
                "focusMode": bool(focus_var.get()),
            },
        )
        book["settings"] = saved

    def load_photo(page_index: int, view_width: int, view_height: int, clean_mode: str) -> ImageTk.PhotoImage:
        payload = _read_cbz_page_bytes(engine_module, book_id, pages[page_index])
        image = _decode_page(payload)
        target = _fit_dimensions(image.width, image.height, view_width, view_height, clean_mode)
        if target != image.size:
            image = image.resize(target, Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image, master=canvas)

    def render() -> None:
        pending = state.get("render_after")
        if pending is not None:
            with suppress(tk.TclError):
                dialog.after_cancel(pending)
            state["render_after"] = None
        canvas.delete("all")
        state["photos"] = []
        canvas.configure(scrollregion=(0, 0, 1, 1))
        status_var.set("正在加载页面…")
        dialog.update_idletasks()

        total = len(pages)
        state["index"] = _clamp_page_index(total, state["index"])
        clean_mode = _normalize_mode(mode_var.get())
        clean_direction = _normalize_direction(direction_var.get())
        mode_var.set(clean_mode)
        direction_var.set(clean_direction)
        if clean_mode == "double":
            state["index"] = (state["index"] // 2) * 2
        indices = _visible_page_indices(total, state["index"], clean_mode, clean_direction)
        view_width = max(360, canvas.winfo_width())
        view_height = max(320, canvas.winfo_height())

        try:
            photos = [load_photo(page_index, view_width, view_height, clean_mode) for page_index in indices]
        except (DesktopCbzReaderError, ReaderWorkspaceError) as exc:
            status_var.set(f"页面加载失败：{exc}")
            page_var.set(f"{state['index'] + 1} / {total}")
            return
        state["photos"] = photos

        gap = 14
        if clean_mode == "double":
            widths = [photo.width() for photo in photos]
            total_width = sum(widths) + gap * max(0, len(photos) - 1)
            x = max(18, (view_width - total_width) // 2)
            max_height = 1
            for photo in photos:
                canvas.create_image(x, 18, anchor="nw", image=photo)
                x += photo.width() + gap
                max_height = max(max_height, photo.height())
            content_width = max(view_width, total_width + 36)
            content_height = max(view_height, max_height + 36)
        else:
            y = 18
            max_width = 1
            for photo in photos:
                x = max(18, (view_width - photo.width()) // 2)
                canvas.create_image(x, y, anchor="nw", image=photo)
                y += photo.height() + gap
                max_width = max(max_width, photo.width())
            content_width = max(view_width, max_width + 36)
            content_height = max(view_height, y + 4)
        canvas.configure(scrollregion=(0, 0, content_width, content_height))
        canvas.yview_moveto(0)

        shown = sorted(indices)
        if shown:
            page_var.set(f"{shown[0] + 1}–{shown[-1] + 1} / {total}" if len(shown) > 1 else f"{shown[0] + 1} / {total}")
        else:
            page_var.set(f"0 / {total}")
        previous_button.configure(state="normal" if state["index"] > 0 else "disabled")
        last_start = max(0, total - (2 if clean_mode == "double" else 1))
        next_button.configure(state="normal" if state["index"] < last_start else "disabled")
        status_var.set(f"{clean_mode} · {clean_direction} · {len(shown)} 页已显示")
        try:
            persist_position()
        except Exception:
            status_var.set("页面已显示 · 阅读进度暂未保存")

    def schedule_render(_event=None) -> None:
        pending = state.get("render_after")
        if pending is not None:
            with suppress(tk.TclError):
                dialog.after_cancel(pending)
        state["render_after"] = dialog.after(120, render)

    def navigate(direction_delta: int) -> None:
        clean_mode = _normalize_mode(mode_var.get())
        step = _navigation_step(clean_mode)
        target = state["index"] + (step * (1 if direction_delta > 0 else -1))
        if clean_mode == "double":
            target = (target // 2) * 2
        state["index"] = _clamp_page_index(len(pages), target)
        render()

    def go_home() -> None:
        state["index"] = 0
        render()

    def go_end() -> None:
        if _normalize_mode(mode_var.get()) == "double":
            state["index"] = ((len(pages) - 1) // 2) * 2
        elif _normalize_mode(mode_var.get()) == "vertical":
            state["index"] = max(0, len(pages) - VERTICAL_WINDOW_PAGES)
        else:
            state["index"] = len(pages) - 1
        render()

    def mode_changed(_event=None) -> None:
        state["index"] = _clamp_page_index(len(pages), state["index"])
        try:
            persist_settings()
        except Exception:
            status_var.set("阅读模式已切换 · 设置暂未保存")
        render()

    def direction_changed(_event=None) -> None:
        try:
            persist_settings()
        except Exception:
            status_var.set("漫画方向已切换 · 设置暂未保存")
        render()

    def apply_focus(persist: bool) -> None:
        enabled = bool(focus_var.get())
        if enabled:
            toolbar.pack_forget()
            status_bar.pack_forget()
            viewport.pack_forget()
            viewport.pack(fill="both", expand=True)
        else:
            viewport.pack_forget()
            toolbar.pack(fill="x", pady=(0, 10), before=viewport)
            viewport.pack(fill="both", expand=True)
            status_bar.pack(fill="x", pady=(8, 0))
        if persist:
            try:
                persist_settings()
            except Exception:
                pass
        schedule_render()

    def toggle_focus() -> None:
        focus_var.set(not focus_var.get())
        apply_focus(True)

    def key_press(event) -> str | None:
        key = str(getattr(event, "keysym", ""))
        clean_direction = _normalize_direction(direction_var.get())
        if key == "Page_Up":
            navigate(-1)
        elif key == "Page_Down":
            navigate(1)
        elif key == "Home":
            go_home()
        elif key == "End":
            go_end()
        elif key == "Left":
            navigate(1 if clean_direction == "rtl" else -1)
        elif key == "Right":
            navigate(-1 if clean_direction == "rtl" else 1)
        elif key.lower() == "f":
            toggle_focus()
        elif key == "Escape":
            if focus_var.get():
                focus_var.set(False)
                apply_focus(True)
            else:
                close()
        else:
            return None
        return "break"

    def mouse_wheel(event) -> str | None:
        if _normalize_mode(mode_var.get()) != "vertical":
            return None
        delta = 0
        if getattr(event, "num", None) == 4:
            delta = -3
        elif getattr(event, "num", None) == 5:
            delta = 3
        elif getattr(event, "delta", 0):
            delta = -int(event.delta / 120) * 3
        if delta:
            canvas.yview_scroll(delta, "units")
            dialog.update_idletasks()
            top, bottom = canvas.yview()
            if bottom >= 0.995 and state["index"] + VERTICAL_WINDOW_PAGES < len(pages) and delta > 0:
                navigate(1)
            elif top <= 0.005 and state["index"] > 0 and delta < 0:
                navigate(-1)
            return "break"
        return None

    def close() -> None:
        try:
            persist_position()
            persist_settings()
        except Exception:
            pass
        if on_change is not None:
            with suppress(Exception):
                on_change()
        dialog.destroy()

    mode_combo.bind("<<ComboboxSelected>>", mode_changed)
    direction_combo.bind("<<ComboboxSelected>>", direction_changed)
    canvas.bind("<Configure>", schedule_render)
    canvas.bind("<MouseWheel>", mouse_wheel)
    canvas.bind("<Button-4>", mouse_wheel)
    canvas.bind("<Button-5>", mouse_wheel)
    dialog.bind("<KeyPress>", key_press)
    dialog.protocol("WM_DELETE_WINDOW", close)

    if focus_var.get():
        apply_focus(False)
    else:
        render()
    canvas.focus_set()


def run_desktop_cbz_reader_self_test() -> None:
    assert _clamp_page_index(0, 99) == 0
    assert _clamp_page_index(4, 99) == 3
    assert _visible_page_indices(5, 0, "single", "ltr") == [0]
    assert _visible_page_indices(5, 0, "double", "ltr") == [0, 1]
    assert _visible_page_indices(5, 0, "double", "rtl") == [1, 0]
    assert _visible_page_indices(8, 2, "vertical", "ltr", vertical_window=3) == [2, 3, 4]
    assert _navigation_step("double") == 2
    assert _navigation_step("single") == 1
    assert _opaque_locator(2) == "cbz-page:3"
    assert _locator_page_index("cbz-page:3", 10) == 2
    assert _fit_dimensions(2000, 1000, 1000, 800, "fit-width") == (954, 477)
