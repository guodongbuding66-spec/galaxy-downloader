from __future__ import annotations

from runtime_storage import state_dir as runtime_state_dir

import re
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from workspace_policy import load_workspace_preferences

DIAGNOSTIC_LOG_FILENAME = "engine.log"
_LOG_LOCK = threading.Lock()
_URL_RE = re.compile(r"https?://[^\s<>\]\[\)\(\"']+", re.IGNORECASE)


def diagnostic_log_path(engine_module) -> Path:
    state_dir = runtime_state_dir(engine_module)
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / DIAGNOSTIC_LOG_FILENAME


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return "[redacted-url]"
        host = parsed.hostname
        try:
            if parsed.port:
                host = f"{host}:{parsed.port}"
        except ValueError:
            pass
        return urlunsplit((parsed.scheme.lower(), host, parsed.path or "/", "", ""))
    except ValueError:
        return "[redacted-url]"


def redact_log_text(value: object, limit: int = 480) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    if not text:
        return ""
    text = _URL_RE.sub(lambda match: _redact_url(match.group(0)), text)
    # Defensive cleanup for common credential/token labels that might be emitted
    # by a third-party extractor. The logger is diagnostic, not a raw trace.
    text = re.sub(
        r"(?i)\b(token|authorization|cookie|session|password|passwd|secret)\s*[:=]\s*[^\s,;]+",
        lambda match: f"{match.group(1)}=[redacted]",
        text,
    )
    return text[:limit]


def _trim_log(path: Path, max_bytes: int) -> None:
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size <= max_bytes:
        return
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            tail = handle.read()
        newline = tail.find(b"\n")
        if newline >= 0:
            tail = tail[newline + 1 :]
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(tail)
        temporary.replace(path)
    except OSError:
        return


def append_diagnostic_event(engine_module, level: str, title: object, detail: object = "") -> bool:
    preferences = load_workspace_preferences(engine_module)
    if not bool(preferences.get("diagnosticLogEnabled", False)):
        return False
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    safe_level = str(level or "INFO").strip().upper()[:12] or "INFO"
    safe_title = redact_log_text(title, 120)
    safe_detail = redact_log_text(detail, 520)
    line = f"{timestamp}\t{safe_level}\t{safe_title}"
    if safe_detail:
        line += f"\t{safe_detail}"
    line += "\n"
    path = diagnostic_log_path(engine_module)
    max_bytes = max(128 * 1024, int(preferences.get("diagnosticLogLimitKb", 512)) * 1024)
    with _LOG_LOCK:
        try:
            with path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(line)
            _trim_log(path, max_bytes)
            return True
        except OSError:
            return False


def load_diagnostic_log(engine_module, max_lines: int = 500) -> list[str]:
    path = diagnostic_log_path(engine_module)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-max(1, min(int(max_lines), 2000)) :]


def clear_diagnostic_log(engine_module) -> bool:
    path = diagnostic_log_path(engine_module)
    with _LOG_LOCK:
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False


def disk_health(engine_module) -> dict[str, Any]:
    target = engine_module.default_download_dir()
    try:
        usage = shutil.disk_usage(target)
        free = int(usage.free)
        total = int(usage.total)
    except OSError:
        free = 0
        total = 0
    preferences = load_workspace_preferences(engine_module)
    threshold_gb = int(preferences.get("lowDiskWarningGb", 5) or 0)
    threshold_bytes = threshold_gb * 1024 * 1024 * 1024
    warning = bool(threshold_bytes and free and free < threshold_bytes)
    return {
        "path": str(target),
        "freeBytes": free,
        "totalBytes": total,
        "warningGb": threshold_gb,
        "warning": warning,
    }


def _completion_alert(window, *, failed: bool = False) -> None:
    try:
        if sys.platform == "win32":
            try:
                import winsound

                winsound.MessageBeep(winsound.MB_ICONHAND if failed else winsound.MB_OK)
            except Exception:
                pass
            try:
                import ctypes

                ctypes.windll.user32.FlashWindow(int(window.winfo_id()), True)
            except Exception:
                pass
        else:
            window.bell()
    except Exception:
        pass


def install_runtime_health(engine_module):
    """Add opt-in redacted diagnostics, disk telemetry and completion alerts."""
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_runtime_health_installed", False):
        return window_cls

    original_set_status = window_cls.set_status

    def set_status(window, title: str, detail: str | None = None) -> None:
        original_set_status(window, title, detail)
        preferences = load_workspace_preferences(engine_module)
        if not bool(preferences.get("diagnosticLogEnabled", False)):
            return
        safe_title = redact_log_text(title, 120)
        safe_detail = redact_log_text(detail, 520)
        signature = (safe_title, safe_detail)
        now = time.monotonic()
        previous = getattr(window, "_galaxy_last_log_event", None)
        if previous and previous[0] == signature and now - float(previous[1]) < 4.0:
            return
        window._galaxy_last_log_event = (signature, now)
        level = "ERROR" if title in {"Download failed"} else "INFO"
        append_diagnostic_event(engine_module, level, safe_title, safe_detail)

    window_cls.set_status = set_status

    original_bridge_status = window_cls.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        health = disk_health(engine_module)
        preferences = load_workspace_preferences(engine_module)
        payload["storageFreeBytes"] = health["freeBytes"]
        payload["storageTotalBytes"] = health["totalBytes"]
        payload["storageWarning"] = bool(health["warning"])
        payload["storageWarningGb"] = int(health["warningGb"])
        payload["diagnosticLogEnabled"] = bool(preferences.get("diagnosticLogEnabled", False))
        return payload

    window_cls.bridge_status = bridge_status

    original_run_job = window_cls._run_job

    def run_job(window) -> None:
        health_before = disk_health(engine_module)
        if health_before["warning"]:
            append_diagnostic_event(
                engine_module,
                "WARN",
                "Low disk space",
                f"downloads free={health_before['freeBytes']} thresholdGb={health_before['warningGb']}",
            )
        original_run_job(window)
        preferences = load_workspace_preferences(engine_module)
        if not bool(preferences.get("completionAlert", False)):
            return
        try:
            state = str(window.bridge_status().get("state") or "").lower()
        except Exception:
            state = ""
        if state == "completed":
            window.ui(lambda: _completion_alert(window, failed=False))
        elif state == "failed":
            window.ui(lambda: _completion_alert(window, failed=True))

    window_cls._run_job = run_job
    window_cls._galaxy_runtime_health_installed = True
    engine_module._galaxy_runtime_health_installed = True
    return window_cls


def run_runtime_health_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        downloads = root / "downloads"
        downloads.mkdir()

        class FakeEngine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def default_download_dir() -> Path:
                return downloads

        from workspace_policy import save_workspace_preferences

        save_workspace_preferences(
            FakeEngine,
            {
                "diagnosticLogEnabled": True,
                "diagnosticLogLimitKb": 128,
                "lowDiskWarningGb": 5,
            },
        )
        assert append_diagnostic_event(
            FakeEngine,
            "INFO",
            "Starting",
            "https://user:secret@example.com/watch?v=abc&token=hidden authorization=secret",
        )
        lines = load_diagnostic_log(FakeEngine)
        assert len(lines) == 1
        assert "https://example.com/watch" in lines[0]
        assert "hidden" not in lines[0]
        assert "secret" not in lines[0]
        health = disk_health(FakeEngine)
        assert int(health["totalBytes"]) >= int(health["freeBytes"])
        assert clear_diagnostic_log(FakeEngine) is True
        assert load_diagnostic_log(FakeEngine) == []
