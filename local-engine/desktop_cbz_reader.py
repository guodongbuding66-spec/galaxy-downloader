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
MAX_CBZ_SOURCE_PIXELS = 50_000_000
MAX_CBZ_RENDER_PIXELS = 12_000_000
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


def _max_start_index(total: int, mode: object) -> int:
    safe_total = max(0, int(total))
    if safe_total <= 1:
        return 0
    clean_mode = _normalize_mode(mode)
    if clean_mode == "double":
        return ((safe_total - 1) // 2) * 2
    if clean_mode == "vertical":
        return max(0, safe_total - VERTICAL_WINDOW_PAGES)
    return safe_total - 1


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
    if clean_mode == "double":
        start = (start // 2) * 2
        result = list(range(start, min(safe_total, start + 2)))
        if _normalize_direction(direction) == "rtl":
            result.reverse()
        return result
    if clean_mode == "vertical":
        count = max(1, min(int(vertical_window), 12))
        return list(range(start, min(safe_total, start + count)))
    return [start]


def _navigation_step(mode: object) -> int:
    clean = _normalize_mode(mode)
    return 2 if clean == "double" else (VERTICAL_WINDOW_PAGES if clean == "vertical" else 1)


def _bounded_render_dimensions(width: int, height: int) -> tuple[int, int]:
    safe_width = max(1, int(width))
    safe_height = max(1, int(height))
    pixels = safe_width * safe_height
    if pixels <= MAX_CBZ_RENDER_PIXELS:
        return safe_width, safe_height
    factor = math.sqrt(MAX_CBZ_RENDER_PIXELS / pixels)
    return max(1, int(safe_width * factor)), max(1, int(safe_height * factor))


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
        scale = min(max(80, (view_width - 54) // 2) / width, max(80, view_height - 50) / height, 1.0)
    elif clean_mode == "single":
        scale = min(max(100, view_width - 40) / width, max(100, view_height - 40) / height, 1.0)
    elif clean_mode == "fit-width":
        scale = max(100, view_width - 46) / width
    else:
        scale = min(max(100, view_width - 46) / width, 1.0)
    return _bounded_render_dimensions(max(1, round(width * scale)), max(1, round(height * scale)))


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


class _CbzArchiveStore:
    def __init__(self, engine_module, book_id: object, pages: list[str]) -> None:
        self._allowed = frozenset(str(page).replace("\\", "/") for page in pages)
        self._archive: zipfile.ZipFile | None = None
        self._members: dict[str, zipfile.ZipInfo] = {}
        archive: zipfile.ZipFile | None = None
        try:
            archive = zipfile.ZipFile(book_file_path(engine_module, book_id), "r")
            members: dict[str, zipfile.ZipInfo] = {}
            for info in archive.infolist():
                name = info.filename.replace("\\", "/")
                if name not in self._allowed:
                    continue
                if name in members:
                    raise DesktopCbzReaderError("CBZ page member is ambiguous")
                if info.is_dir() or info.flag_bits & 0x1:
                    raise DesktopCbzReaderError("CBZ page member is unavailable")
                if info.file_size <= 0 or info.file_size > MAX_CBZ_PAGE_BYTES:
                    raise DesktopCbzReaderError("CBZ page exceeds the safe size limit")
                members[name] = info
            if set(members) != set(self._allowed):
                raise DesktopCbzReaderError("CBZ page member is missing")
            self._archive = archive
            self._members = members
        except Exception:
            if archive is not None:
                with suppress(Exception):
                    archive.close()
            raise

    def read(self, page_name: object) -> bytes:
        requested = str(page_name or "").replace("\\", "/").strip()
        if requested not in self._allowed:
            raise DesktopCbzReaderError("CBZ page is outside the managed page list")
        archive = self._archive
        info = self._members.get(requested)
        if archive is None or info is None:
            raise DesktopCbzReaderError("CBZ archive is unavailable")
        try:
            with archive.open(info, "r") as source:
                payload = source.read(MAX_CBZ_PAGE_BYTES + 1)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise DesktopCbzReaderError("CBZ page cannot be read") from exc
        if not payload or len(payload) > MAX_CBZ_PAGE_BYTES:
            raise DesktopCbzReaderError("CBZ page exceeds the safe size limit")
        return payload

    def close(self) -> None:
        archive = self._archive
        self._archive = None
        self._members.clear()
        if archive is not None:
            with suppress(Exception):
                archive.close()


def _read_cbz_page_bytes(engine_module, book_id: object, page_name: object) -> bytes:
    requested = str(page_name or "").replace("\\", "/").strip()
    pages = cbz_pages(engine_module, book_id, limit=5000)
    if requested not in pages:
        raise DesktopCbzReaderError("CBZ page is outside the managed page list")
    try:
        store = _CbzArchiveStore(engine_module, book_id, pages)
    except (ReaderWorkspaceError, OSError, zipfile.BadZipFile, DesktopCbzReaderError) as exc:
        raise DesktopCbzReaderError("CBZ archive is unavailable") from exc
    try:
        return store.read(requested)
    finally:
        store.close()


def _decode_page(payload: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(payload)) as source:
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_CBZ_SOURCE_PIXELS:
                raise DesktopCbzReaderError("CBZ page dimensions exceed the safe limit")
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.load()
            return image
    except DesktopCbzReaderError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
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
    try:
        page_store = _CbzArchiveStore(engine_module, book_id, pages)
    except (DesktopCbzReaderError, ReaderWorkspaceError, OSError, zipfile.BadZipFile) as exc:
        raise DesktopCbzReaderError("CBZ 托管文件无法打开") from exc

    mode, direction, focus = _settings_from_book(book)
    state: dict[str, Any] = {
        "index": _locator_page_index(book.get("locator"), len(pages), book.get("progressPercent")),
        "photos": [],
        "render_after": None,
    }

    try:
        dialog = tk.Toplevel(parent)
        dialog.title(f"{str(book.get('title') or 'CBZ')} · CBZ Reader")
        dialog.geometry("1120x800")
        dialog.minsize(760, 560)
        dialog.configure(bg=ui.BG)
        dialog.transient(parent)
    except Exception:
        page_store.close()
        raise

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
    ui._label(toolbar, "模式", size=7, color=ui.SUBTLE, bg=ui.BG).pack(side="left", padx=(0, 5))
    mode_combo = ttk.Combobox(toolbar, textvariable=mode_var, values=_SUPPORTED_MODES, state="readonly", width=11)
    mode_combo.pack(side="left", padx=(0, 10))
    ui._label(toolbar, "方向", size=7, color=ui.SUBTLE, bg=ui.BG).pack(side="left", padx=(0, 5))
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
        last = max(visible) if visible else index
        progress = round(((last + 1) / len(pages)) * 100.0, 3)
        locator = _opaque_locator(index)
        update_reading_position(engine_module, book_id, progress, locator)
        book["progressPercent"] = progress
        book["locator"] = locator

    def persist_settings() -> None:
        book["settings"] = update_reader_settings(
            engine_module,
            book_id,
            {
                "readingMode": _normalize_mode(mode_var.get()),
                "mangaDirection": _normalize_direction(direction_var.get()),
                "focusMode": bool(focus_var.get()),
            },
        )

    def load_photo(page_index: int, view_width: int, view_height: int, clean_mode: str) -> ImageTk.PhotoImage:
        image = _decode_page(page_store.read(pages[page_index]))
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
        status_var.set("正在加载页面…")
        dialog.update_idletasks()

        total = len(pages)
        clean_mode = _normalize_mode(mode_var.get())
        clean_direction = _normalize_direction(direction_var.get())
        mode_var.set(clean_mode)
        direction_var.set(clean_direction)
        state["index"] = min(_clamp_page_index(total, state["index"]), _max_start_index(total, clean_mode))
        if clean_mode == "double":
            state["index"] = (state["index"] // 2) * 2
        indices = _visible_page_indices(total, state["index"], clean_mode, clean_direction)
        view_width = max(360, canvas.winfo_width())
        view_height = max(320, canvas.winfo_height())
        try:
            photos = [load_photo(index, view_width, view_height, clean_mode) for index in indices]
        except (DesktopCbzReaderError, ReaderWorkspaceError) as exc:
            canvas.configure(scrollregion=(0, 0, view_width, view_height))
            status_var.set(f"页面加载失败：{exc}")
            page_var.set(f"{state['index'] + 1} / {total}")
            return
        state["photos"] = photos

        gap = 14
        if clean_mode == "double":
            total_width = sum(photo.width() for photo in photos) + gap * max(0, len(photos) - 1)
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
        page_var.set(
            f"{shown[0] + 1}–{shown[-1] + 1} / {total}" if len(shown) > 1 else f"{shown[0] + 1} / {total}"
        )
        previous_button.state(["!disabled"] if state["index"] > 0 else ["disabled"])
        next_button.state(["!disabled"] if state["index"] < _max_start_index(total, clean_mode) else ["disabled"])
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

    def navigate(delta: int) -> None:
        clean_mode = _normalize_mode(mode_var.get())
        target = state["index"] + _navigation_step(clean_mode) * (1 if delta > 0 else -1)
        target = min(_clamp_page_index(len(pages), target), _max_start_index(len(pages), clean_mode))
        state["index"] = (target // 2) * 2 if clean_mode == "double" else target
        render()

    def go_home() -> None:
        state["index"] = 0
        render()

    def go_end() -> None:
        state["index"] = _max_start_index(len(pages), mode_var.get())
        render()

    def mode_changed(_event=None) -> None:
        state["index"] = min(_clamp_page_index(len(pages), state["index"]), _max_start_index(len(pages), mode_var.get()))
        with suppress(Exception):
            persist_settings()
        render()

    def direction_changed(_event=None) -> None:
        with suppress(Exception):
            persist_settings()
        render()

    def apply_focus(persist: bool) -> None:
        enabled = bool(focus_var.get())
        toolbar.pack_forget()
        viewport.pack_forget()
        status_bar.pack_forget()
        if not enabled:
            toolbar.pack(fill="x", pady=(0, 10))
        viewport.pack(fill="both", expand=True)
        if not enabled:
            status_bar.pack(fill="x", pady=(8, 0))
        if persist:
            with suppress(Exception):
                persist_settings()
        schedule_render()

    def toggle_focus() -> None:
        focus_var.set(not focus_var.get())
        apply_focus(True)

    def key_press(event) -> str | None:
        key = str(getattr(event, "keysym", ""))
        direction = _normalize_direction(direction_var.get())
        if key == "Page_Up":
            navigate(-1)
        elif key == "Page_Down":
            navigate(1)
        elif key == "Home":
            go_home()
        elif key == "End":
            go_end()
        elif key == "Left":
            navigate(1 if direction == "rtl" else -1)
        elif key == "Right":
            navigate(-1 if direction == "rtl" else 1)
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
        if getattr(event, "num", None) == 4:
            delta = -3
        elif getattr(event, "num", None) == 5:
            delta = 3
        elif getattr(event, "delta", 0):
            delta = -int(event.delta / 120) * 3
        else:
            delta = 0
        if not delta:
            return None
        canvas.yview_scroll(delta, "units")
        dialog.update_idletasks()
        top, bottom = canvas.yview()
        if bottom >= 0.995 and state["index"] < _max_start_index(len(pages), "vertical") and delta > 0:
            navigate(1)
        elif top <= 0.005 and state["index"] > 0 and delta < 0:
            navigate(-1)
        return "break"

    def close() -> None:
        with suppress(Exception):
            persist_position()
            persist_settings()
        page_store.close()
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
    assert _max_start_index(5, "double") == 4
    assert _max_start_index(10, "vertical") == 4
    assert _visible_page_indices(5, 0, "single", "ltr") == [0]
    assert _visible_page_indices(5, 0, "double", "ltr") == [0, 1]
    assert _visible_page_indices(5, 0, "double", "rtl") == [1, 0]
    assert _visible_page_indices(8, 2, "vertical", "ltr", vertical_window=3) == [2, 3, 4]
    assert _navigation_step("double") == 2 and _navigation_step("single") == 1
    assert _opaque_locator(2) == "cbz-page:3" and _locator_page_index("cbz-page:3", 10) == 2
    assert _fit_dimensions(2000, 1000, 1000, 800, "fit-width") == (954, 477)
    tall = _fit_dimensions(1000, 50000, 1000, 800, "fit-width")
    assert tall[0] * tall[1] <= MAX_CBZ_RENDER_PIXELS
