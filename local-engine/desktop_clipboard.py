from __future__ import annotations

import json
import re
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
    # Reading the clipboard is privacy-sensitive. Keep the feature disabled
    # until the user explicitly opts in; the choice is then persisted locally.
    "clipboardMonitorEnabled": False,
}


def _preferences_path(engine_module) -> Path:
    target = runtime_state_dir(engine_module)
    target.mkdir(parents=True, exist_ok=True)
    return target / PREFERENCES_FILENAME


def clean_desktop_feature_preferences(value: object) -> dict[str, bool]:
    raw = value if isinstance(value, dict) else {}
    return {
        "clipboardMonitorEnabled": bool(raw.get("clipboardMonitorEnabled", False)),
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


def extract_clipboard_http_url(value: object) -> str | None:
    """Return the first syntactically valid HTTP(S) URL without network access.

    Clipboard monitoring must never perform DNS lookups or media parsing on its
    own. The normal Galaxy public-URL validator remains the final boundary when
    the user explicitly requests a preview.
    """
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


def _persist_enabled(window, engine_module, enabled: bool) -> None:
    window._clipboard_monitor_enabled = bool(enabled)
    try:
        save_desktop_feature_preferences(
            engine_module,
            {"clipboardMonitorEnabled": bool(enabled)},
        )
    except OSError:
        # Monitoring can still work for this session even if persistence fails.
        pass


def _next_poll_generation(window) -> int:
    generation = int(getattr(window, "_clipboard_poll_generation", 0)) + 1
    window._clipboard_poll_generation = generation
    return generation


def _toggle_monitor(window, engine_module) -> None:
    enabled = bool(window._clipboard_monitor_var.get())
    _persist_enabled(window, engine_module, enabled)
    window._clipboard_last_text = None
    generation = _next_poll_generation(window)
    if enabled:
        _set_detection_state(
            window,
            "剪贴板监听已开启：只识别 HTTP(S) 链接，不会自动联网解析。",
        )
        _poll_clipboard(window, engine_module, generation)
    else:
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
                f"检测到 {_host_label(candidate)} 链接。点击“预览剪贴板链接”后才会联网。",
                candidate=candidate,
            )
        elif candidate and candidate == current:
            _set_detection_state(window, "剪贴板中的链接已经在下载工作台中。")
        else:
            _set_detection_state(window, "正在监听剪贴板，尚未发现 HTTP(S) 媒体链接。")
    try:
        window.after(
            POLL_INTERVAL_MS,
            lambda: _poll_clipboard(window, engine_module, generation),
        )
    except Exception:
        pass


def _preview_clipboard_candidate(window, engine_module) -> None:
    candidate = str(getattr(window, "_clipboard_candidate", "") or "").strip()
    if not candidate:
        return
    url_var = getattr(window, "_quick_url_var", None)
    if url_var is None:
        return
    url_var.set(candidate)
    _set_detection_state(window, "已送入下载工作台，正在解析预览…")
    # Import lazily to avoid a module-cycle during workbench registration.
    import desktop_download_workbench as workbench

    workbench._parse_quick_url_async(window, engine_module)


def _install_clipboard_controls(window, engine_module) -> None:
    panel = getattr(window, "_quick_download_panel", None)
    if panel is None:
        return

    preferences = load_desktop_feature_preferences(engine_module)
    enabled = bool(preferences["clipboardMonitorEnabled"])
    window._clipboard_monitor_enabled = enabled
    window._clipboard_last_text = None
    window._clipboard_candidate = None
    window._clipboard_poll_generation = 0
    window._clipboard_monitor_var = ui.tk.BooleanVar(value=enabled)
    window._clipboard_status_var = ui.tk.StringVar(
        value=(
            "剪贴板监听已开启：只识别链接，不会自动联网解析。"
            if enabled
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
        wraplength=440,
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

    if enabled:
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
        payload["clipboardMonitorEnabled"] = bool(
            getattr(window, "_clipboard_monitor_enabled", False)
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
    assert clean_desktop_feature_preferences({"clipboardMonitorEnabled": 1}) == {
        "clipboardMonitorEnabled": True,
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
        saved = save_desktop_feature_preferences(Engine, {"clipboardMonitorEnabled": True})
        assert saved["clipboardMonitorEnabled"] is True
        assert load_desktop_feature_preferences(Engine)["clipboardMonitorEnabled"] is True

    class Window:
        @staticmethod
        def bridge_status(_window=None):
            return {}

    engine = SimpleNamespace(EngineWindow=Window)
    install_desktop_clipboard_monitor(engine)
    assert "desktop-clipboard-monitor" in registered_after_build_ui_hooks(Window)
    assert Window._galaxy_desktop_clipboard_monitor_installed is True
