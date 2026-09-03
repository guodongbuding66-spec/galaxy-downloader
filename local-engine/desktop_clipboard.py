from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import desktop_ui as ui
from desktop_hooks import register_after_build_ui_hook, registered_after_build_ui_hooks
from runtime_storage import state_dir as runtime_state_dir

PREFERENCES_FILENAME = "desktop-features.json"
POLL_INTERVAL_MS = 900
MAX_CLIPBOARD_CHARS = 16_384
MAX_URL_CHARS = 4_096
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

DEFAULT_DESKTOP_FEATURE_PREFERENCES: dict[str, bool] = {
    # Clipboard polling remains opt-in. Toasts only appear after polling is enabled
    # and hotkey direct-download reads the clipboard only on the explicit keypress.
    "clipboardMonitorEnabled": False,
    "clipboardToastEnabled": True,
    "hotkeyDirectDownloadEnabled": False,
}


def _preferences_path(engine_module) -> Path:
    target = runtime_state_dir(engine_module)
    target.mkdir(parents=True, exist_ok=True)
    return target / PREFERENCES_FILENAME


def clean_desktop_feature_preferences(value: object) -> dict[str, bool]:
    raw = value if isinstance(value, dict) else {}
    return {
        "clipboardMonitorEnabled": bool(raw.get("clipboardMonitorEnabled", False)),
        "clipboardToastEnabled": bool(raw.get("clipboardToastEnabled", True)),
        "hotkeyDirectDownloadEnabled": bool(raw.get("hotkeyDirectDownloadEnabled", False)),
    }


def load_desktop_feature_preferences(engine_module) -> dict[str, bool]:
    try:
        raw = json.loads(_preferences_path(engine_module).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return dict(DEFAULT_DESKTOP_FEATURE_PREFERENCES)
    return clean_desktop_feature_preferences(raw)


def save_desktop_feature_preferences(engine_module, preferences: dict[str, Any]) -> dict[str, bool]:
    cleaned = clean_desktop_feature_preferences(preferences)
    path = _preferences_path(engine_module)
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return cleaned


def update_desktop_feature_preferences(engine_module, **changes: object) -> dict[str, bool]:
    current = load_desktop_feature_preferences(engine_module)
    current.update(changes)
    return save_desktop_feature_preferences(engine_module, current)


def extract_clipboard_http_url(value: object) -> str | None:
    """Return the first syntactically valid HTTP(S) URL without network access."""
    text = str(value or "")
    if not text or len(text) > MAX_CLIPBOARD_CHARS:
        return None
    match = _URL_RE.search(text)
    if match is None:
        return None
    candidate = match.group(0).rstrip(".,;:!?)]}\"")
    if not candidate or len(candidate) > MAX_URL_CHARS:
        return None
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return candidate


def build_quick_download_payload(candidate: object) -> dict[str, Any]:
    url = extract_clipboard_http_url(candidate)
    if not url:
        raise ValueError("clipboard does not contain a valid HTTP(S) URL")
    return {
        "sourceUrl": url,
        "videoQuality": "best",
        "audioQuality": "best",
        "includeAudio": True,
        "includeSubtitle": False,
        "includeCover": False,
        "browser": "none",
        "collectionMode": "single",
        "selectedItems": [],
        "displayTitle": "剪贴板快捷下载",
    }


def _host_label(value: str) -> str:
    try:
        return str(urlsplit(value).hostname or "链接")[:80]
    except ValueError:
        return "链接"


def _set_detection_state(window, text: str, *, candidate: str | None = None) -> None:
    window._clipboard_candidate = candidate
    status = getattr(window, "_clipboard_status_var", None)
    if status is not None:
        status.set(text[:220])
    button = getattr(window, "_clipboard_preview_button", None)
    if button is not None:
        if candidate:
            button.state(["!disabled"])
        else:
            button.state(["disabled"])


def _persist_controls(window, engine_module) -> None:
    monitor = bool(window._clipboard_monitor_var.get())
    toast = bool(window._clipboard_toast_var.get())
    direct = bool(window._hotkey_direct_download_var.get())
    window._clipboard_monitor_enabled = monitor
    window._clipboard_toast_enabled = toast
    window._hotkey_direct_download_enabled = direct
    try:
        save_desktop_feature_preferences(
            engine_module,
            {
                "clipboardMonitorEnabled": monitor,
                "clipboardToastEnabled": toast,
                "hotkeyDirectDownloadEnabled": direct,
            },
        )
    except OSError:
        # Session-level behavior remains usable even when local persistence fails.
        pass


def _next_poll_generation(window) -> int:
    generation = int(getattr(window, "_clipboard_poll_generation", 0)) + 1
    window._clipboard_poll_generation = generation
    return generation


def _dismiss_toast(window) -> None:
    toast = getattr(window, "_clipboard_toast_window", None)
    window._clipboard_toast_window = None
    if toast is not None:
        try:
            toast.destroy()
        except Exception:
            pass


def _show_clipboard_toast(window, engine_module, candidate: str) -> None:
    if not bool(getattr(window, "_clipboard_toast_enabled", False)):
        return
    _dismiss_toast(window)
    try:
        toast = ui.tk.Toplevel(window)
        window._clipboard_toast_window = toast
        toast.title("Galaxy")
        toast.configure(bg=ui.PANEL)
        toast.attributes("-topmost", True)
        toast.resizable(False, False)
        try:
            toast.overrideredirect(True)
        except Exception:
            pass
        shell = ui.tk.Frame(toast, bg=ui.PANEL, padx=12, pady=10, highlightthickness=1, highlightbackground=ui.BORDER)
        shell.pack(fill="both", expand=True)
        ui._label(shell, "检测到可下载链接", size=8, weight="bold", bg=ui.PANEL).pack(anchor="w")
        ui._label(
            shell,
            _host_label(candidate),
            size=7,
            color=ui.MUTED,
            bg=ui.PANEL,
        ).pack(anchor="w", pady=(2, 8))
        actions = ui.tk.Frame(shell, bg=ui.PANEL)
        actions.pack(fill="x")
        ui.ActionButton(
            actions,
            text="忽略",
            command=lambda: _dismiss_toast(window),
            kind="ghost",
            compact=True,
        ).pack(side="left")
        ui.ActionButton(
            actions,
            text="预览",
            command=lambda: (_dismiss_toast(window), _preview_clipboard_candidate(window, engine_module)),
            kind="ghost",
            compact=True,
        ).pack(side="right")
        ui.ActionButton(
            actions,
            text="直接下载",
            command=lambda: (_dismiss_toast(window), submit_clipboard_download(window, engine_module, candidate)),
            kind="secondary",
            compact=True,
        ).pack(side="right", padx=(0, 6))
        toast.update_idletasks()
        width = max(300, toast.winfo_reqwidth())
        height = max(100, toast.winfo_reqheight())
        x = max(12, toast.winfo_screenwidth() - width - 22)
        y = max(12, toast.winfo_screenheight() - height - 64)
        toast.geometry(f"{width}x{height}+{x}+{y}")
        toast.after(9000, lambda: _dismiss_toast(window))
    except Exception:
        _dismiss_toast(window)


def _toggle_monitor(window, engine_module) -> None:
    _persist_controls(window, engine_module)
    window._clipboard_last_text = None
    generation = _next_poll_generation(window)
    if bool(window._clipboard_monitor_enabled):
        _set_detection_state(
            window,
            "剪贴板监听已开启：只识别 HTTP(S) 链接，不会自动联网解析。",
        )
        _poll_clipboard(window, engine_module, generation)
    else:
        _dismiss_toast(window)
        _set_detection_state(window, "剪贴板监听已关闭，不会读取剪贴板。")


def _poll_clipboard(window, engine_module, generation: int) -> None:
    if generation != int(getattr(window, "_clipboard_poll_generation", 0)):
        return
    if not bool(getattr(window, "_clipboard_monitor_enabled", False)):
        return

    try:
        raw = window.clipboard_get()
    except Exception:
        raw = ""
    text = str(raw or "")
    if text != getattr(window, "_clipboard_last_text", None):
        window._clipboard_last_text = text
        candidate = extract_clipboard_http_url(text)
        current = ""
        url_var = getattr(window, "_quick_url_var", None)
        if url_var is not None:
            try:
                current = str(url_var.get() or "").strip()
            except Exception:
                current = ""
        if candidate and candidate != current:
            _set_detection_state(
                window,
                f"检测到 {_host_label(candidate)} 链接。预览或直接下载都需要显式点击。",
                candidate=candidate,
            )
            _show_clipboard_toast(window, engine_module, candidate)
        elif candidate and candidate == current:
            _set_detection_state(window, "剪贴板中的链接已经在下载工作台中。")
        else:
            _dismiss_toast(window)
            _set_detection_state(window, "正在监听剪贴板，尚未发现 HTTP(S) 媒体链接。")
    try:
        window.after(POLL_INTERVAL_MS, lambda: _poll_clipboard(window, engine_module, generation))
    except Exception:
        pass


def _preview_clipboard_candidate(window, engine_module) -> None:
    candidate = str(getattr(window, "_clipboard_candidate", "") or "").strip()
    if not candidate:
        try:
            candidate = extract_clipboard_http_url(window.clipboard_get()) or ""
        except Exception:
            candidate = ""
    if not candidate:
        return
    url_var = getattr(window, "_quick_url_var", None)
    if url_var is None:
        return
    url_var.set(candidate)
    _set_detection_state(window, "已送入下载工作台，正在解析预览…", candidate=candidate)
    import desktop_download_workbench as workbench

    workbench._parse_quick_url_async(window, engine_module)


def submit_clipboard_download(window, engine_module, candidate: object | None = None) -> bool:
    value = candidate
    if not value:
        value = getattr(window, "_clipboard_candidate", None)
    if not value:
        try:
            value = window.clipboard_get()
        except Exception:
            value = ""
    try:
        payload = build_quick_download_payload(value)
    except ValueError:
        _set_detection_state(window, "剪贴板中没有可直接下载的 HTTP(S) 链接。")
        return False
    if not callable(getattr(window, "submit_bridge_job", None)):
        return False

    url_var = getattr(window, "_quick_url_var", None)
    if url_var is not None:
        try:
            url_var.set(payload["sourceUrl"])
        except Exception:
            pass
    _set_detection_state(window, "正在提交剪贴板快捷下载…", candidate=str(payload["sourceUrl"]))

    def worker() -> None:
        try:
            response = window.submit_bridge_job(payload)
            accepted = bool(
                getattr(
                    response,
                    "accepted",
                    response[0] if isinstance(response, tuple) and response else False,
                )
            )
            message = str(
                getattr(
                    response,
                    "message",
                    response[1] if isinstance(response, tuple) and len(response) > 1 else response,
                )
            )
            detail = message or ("已提交下载" if accepted else "下载请求未被接受")
        except Exception as exc:  # noqa: BLE001
            detail = f"快捷下载失败：{exc}"
        try:
            window.after(0, lambda: _set_detection_state(window, detail))
        except Exception:
            pass

    threading.Thread(target=worker, name="GalaxyClipboardDownload", daemon=True).start()
    return True


def handle_global_hotkey(window, engine_module=None) -> bool:
    """Return True when the explicit global hotkey was consumed as a download."""
    module = engine_module or getattr(window, "_galaxy_engine_module", None)
    if module is None:
        return False
    preferences = load_desktop_feature_preferences(module)
    if not bool(preferences.get("hotkeyDirectDownloadEnabled", False)):
        return False
    try:
        raw = window.clipboard_get()
    except Exception:
        raw = ""
    candidate = extract_clipboard_http_url(raw)
    if not candidate:
        return False
    return submit_clipboard_download(window, module, candidate)


def _install_clipboard_controls(window, engine_module) -> None:
    panel = getattr(window, "_quick_download_panel", None)
    if panel is None:
        return

    preferences = load_desktop_feature_preferences(engine_module)
    window._galaxy_engine_module = engine_module
    window._clipboard_monitor_enabled = bool(preferences["clipboardMonitorEnabled"])
    window._clipboard_toast_enabled = bool(preferences["clipboardToastEnabled"])
    window._hotkey_direct_download_enabled = bool(preferences["hotkeyDirectDownloadEnabled"])
    window._clipboard_last_text = None
    window._clipboard_candidate = None
    window._clipboard_poll_generation = 0
    window._clipboard_toast_window = None
    window._clipboard_monitor_var = ui.tk.BooleanVar(value=window._clipboard_monitor_enabled)
    window._clipboard_toast_var = ui.tk.BooleanVar(value=window._clipboard_toast_enabled)
    window._hotkey_direct_download_var = ui.tk.BooleanVar(value=window._hotkey_direct_download_enabled)
    window._clipboard_status_var = ui.tk.StringVar(
        value=(
            "剪贴板监听已开启：只识别链接，不会自动联网解析。"
            if window._clipboard_monitor_enabled
            else "剪贴板监听已关闭，不会读取剪贴板。"
        )
    )

    row = ui.tk.Frame(panel, bg=ui.PANEL_2)
    row.pack(fill="x", pady=(8, 0))
    ui.ttk.Checkbutton(
        row,
        text="监听剪贴板",
        variable=window._clipboard_monitor_var,
        command=lambda: _toggle_monitor(window, engine_module),
    ).pack(side="left")
    ui._label(
        row,
        variable=window._clipboard_status_var,
        size=7,
        color=ui.SUBTLE,
        bg=ui.PANEL_2,
        wraplength=390,
        justify="left",
    ).pack(side="left", padx=(10, 8), fill="x", expand=True)
    window._clipboard_preview_button = ui.ActionButton(
        row,
        text="预览剪贴板链接",
        command=lambda: _preview_clipboard_candidate(window, engine_module),
        kind="ghost",
        compact=True,
    )
    window._clipboard_preview_button.pack(side="right")
    window._clipboard_preview_button.state(["disabled"])

    options = ui.tk.Frame(panel, bg=ui.PANEL_2)
    options.pack(fill="x", pady=(4, 0))
    ui.ttk.Checkbutton(
        options,
        text="检测到链接时显示提示条",
        variable=window._clipboard_toast_var,
        command=lambda: _persist_controls(window, engine_module),
    ).pack(side="left")
    ui.ttk.Checkbutton(
        options,
        text="Ctrl+Shift+G 直接下载剪贴板最佳画质",
        variable=window._hotkey_direct_download_var,
        command=lambda: _persist_controls(window, engine_module),
    ).pack(side="left", padx=(14, 0))

    if window._clipboard_monitor_enabled:
        generation = _next_poll_generation(window)
        try:
            window.after(250, lambda: _poll_clipboard(window, engine_module, generation))
        except Exception:
            pass


def install_desktop_clipboard_monitor(engine_module):
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_desktop_clipboard_monitor_installed", False):
        return window_cls

    register_after_build_ui_hook(
        window_cls,
        "desktop-clipboard-monitor",
        lambda window: _install_clipboard_controls(window, engine_module),
        order=50,
    )

    original_bridge_status = window_cls.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        payload["clipboardMonitorAvailable"] = True
        payload["clipboardMonitorEnabled"] = bool(getattr(window, "_clipboard_monitor_enabled", False))
        payload["clipboardToastEnabled"] = bool(getattr(window, "_clipboard_toast_enabled", False))
        payload["hotkeyDirectDownloadEnabled"] = bool(
            getattr(window, "_hotkey_direct_download_enabled", False)
        )
        return payload

    window_cls.bridge_status = bridge_status
    window_cls._galaxy_desktop_clipboard_monitor_installed = True
    engine_module._galaxy_desktop_clipboard_monitor_installed = True
    return window_cls


def run_desktop_clipboard_monitor_self_test() -> None:
    assert extract_clipboard_http_url("https://example.test/watch") == "https://example.test/watch"
    assert extract_clipboard_http_url("copy https://example.test/v.mp4).") == "https://example.test/v.mp4"
    assert extract_clipboard_http_url("ftp://example.test/file") is None
    assert extract_clipboard_http_url("https://user:pass@example.test/private") is None
    assert extract_clipboard_http_url("not a link") is None
    payload = build_quick_download_payload("https://example.test/watch")
    assert payload["videoQuality"] == "best"
    assert payload["includeAudio"] is True
    assert clean_desktop_feature_preferences({"clipboardMonitorEnabled": 1}) == {
        "clipboardMonitorEnabled": True,
        "clipboardToastEnabled": True,
        "hotkeyDirectDownloadEnabled": False,
    }

    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return root / "state"

        assert load_desktop_feature_preferences(Engine) == DEFAULT_DESKTOP_FEATURE_PREFERENCES
        saved = save_desktop_feature_preferences(
            Engine,
            {
                "clipboardMonitorEnabled": True,
                "clipboardToastEnabled": False,
                "hotkeyDirectDownloadEnabled": True,
            },
        )
        assert saved["clipboardMonitorEnabled"] is True
        assert saved["clipboardToastEnabled"] is False
        assert saved["hotkeyDirectDownloadEnabled"] is True
        loaded = load_desktop_feature_preferences(Engine)
        assert loaded == saved
        updated = update_desktop_feature_preferences(Engine, clipboardToastEnabled=True)
        assert updated["clipboardMonitorEnabled"] is True
        assert updated["clipboardToastEnabled"] is True

    class Window:
        @staticmethod
        def bridge_status(_window=None):
            return {}

    engine = SimpleNamespace(EngineWindow=Window)
    install_desktop_clipboard_monitor(engine)
    assert "desktop-clipboard-monitor" in registered_after_build_ui_hooks(Window)
    assert Window._galaxy_desktop_clipboard_monitor_installed is True
