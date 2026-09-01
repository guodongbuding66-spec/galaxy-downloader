from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

HISTORY_FILENAME = "download-history.json"
MAX_HISTORY_ITEMS = 80
_HISTORY_LOCK = threading.Lock()
_TERMINAL_STATES = {"completed", "failed", "cancelled"}


def _history_path(engine_module) -> Path:
    state_dir = engine_module.app_dir() / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / HISTORY_FILENAME


def _safe_text(value: object, limit: int = 240) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _redacted_source_url(value: object) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname or ""
        if parsed.scheme not in {"http", "https"} or not hostname:
            return "", ""
        host = hostname
        try:
            if parsed.port:
                host = f"{host}:{parsed.port}"
        except ValueError:
            pass
        display = urlunsplit((parsed.scheme, host, parsed.path or "/", "", ""))
        return display[:600], hostname[:160]
    except ValueError:
        return "", ""


def _safe_download_path(engine_module, value: object) -> str:
    if not value:
        return ""
    try:
        candidate = Path(str(value)).expanduser().resolve(strict=False)
        root = engine_module.default_download_dir().resolve(strict=False)
        candidate.relative_to(root)
        return str(candidate)
    except (OSError, RuntimeError, ValueError):
        return ""


def _clean_item(engine_module, value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    state = str(value.get("state") or "").strip().lower()
    if state not in _TERMINAL_STATES:
        return None
    source_url, source_host = _redacted_source_url(value.get("sourceUrl"))
    file_path = _safe_download_path(engine_module, value.get("filePath"))
    file_name = _safe_text(value.get("fileName"), 220)
    if file_path and not file_name:
        file_name = Path(file_path).name[:220]
    try:
        duration = max(0.0, min(float(value.get("durationSeconds") or 0), 14 * 24 * 3600))
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "id": _safe_text(value.get("id"), 64) or uuid.uuid4().hex,
        "finishedAt": _safe_text(value.get("finishedAt"), 40),
        "state": state,
        "label": _safe_text(value.get("label"), 220) or file_name or source_host or "Download",
        "sourceHost": source_host,
        "sourceUrl": source_url,
        "detail": _safe_text(value.get("detail"), 280),
        "fileName": file_name,
        "filePath": file_path,
        "videoQuality": _safe_text(value.get("videoQuality"), 40),
        "audioQuality": _safe_text(value.get("audioQuality"), 40),
        "collectionMode": _safe_text(value.get("collectionMode"), 24),
        "durationSeconds": round(duration, 1),
    }


def load_history(engine_module) -> list[dict[str, Any]]:
    path = _history_path(engine_module)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    values = raw if isinstance(raw, list) else []
    result: list[dict[str, Any]] = []
    for value in values[:MAX_HISTORY_ITEMS]:
        cleaned = _clean_item(engine_module, value)
        if cleaned is not None:
            result.append(cleaned)
    return result


def _write_history(engine_module, items: list[dict[str, Any]]) -> None:
    path = _history_path(engine_module)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(items[:MAX_HISTORY_ITEMS], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def append_history(engine_module, item: dict[str, Any]) -> dict[str, Any] | None:
    cleaned = _clean_item(engine_module, item)
    if cleaned is None:
        return None
    with _HISTORY_LOCK:
        history = load_history(engine_module)
        history.insert(0, cleaned)
        _write_history(engine_module, history)
    return cleaned


def clear_history(engine_module) -> int:
    with _HISTORY_LOCK:
        history = load_history(engine_module)
        path = _history_path(engine_module)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            _write_history(engine_module, [])
        return len(history)


def _history_record(engine_module, job: Any, snapshot: dict[str, Any], last_path: object, duration: float) -> dict[str, Any]:
    source_url, source_host = _redacted_source_url(getattr(job, "source_url", ""))
    file_path = _safe_download_path(engine_module, last_path)
    file_name = Path(file_path).name if file_path else ""
    state = str(snapshot.get("state") or "failed").lower()
    detail = _safe_text(snapshot.get("detail"), 280)
    label = file_name or source_host or "Download"
    return {
        "id": uuid.uuid4().hex,
        "finishedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "state": state if state in _TERMINAL_STATES else "failed",
        "label": label,
        "sourceHost": source_host,
        "sourceUrl": source_url,
        "detail": detail,
        "fileName": file_name,
        "filePath": file_path,
        "videoQuality": str(getattr(job, "video_quality", "") or ""),
        "audioQuality": str(getattr(job, "audio_quality", "") or ""),
        "collectionMode": str(getattr(job, "collection_mode", "single") or "single"),
        "durationSeconds": round(max(0.0, duration), 1),
    }


def install_history_policy(engine_module):
    """Record terminal media jobs in a local, privacy-safe history file."""
    window_cls = engine_module.EngineWindow
    if getattr(window_cls, "_galaxy_history_installed", False):
        return window_cls

    original_run_job = window_cls._run_job

    def run_job_with_history(window) -> None:
        job = getattr(window, "job", None)
        started = time.monotonic()
        original_run_job(window)
        if job is None:
            return
        try:
            snapshot = window.bridge_status()
            state = str(snapshot.get("state") or "").lower()
            if state not in _TERMINAL_STATES:
                return
            last_path = getattr(window, "last_path", None) if state == "completed" else None
            append_history(
                engine_module,
                _history_record(engine_module, job, snapshot, last_path, time.monotonic() - started),
            )
        except Exception:
            # History must never change the success/failure semantics of a download.
            return

    window_cls._run_job = run_job_with_history
    window_cls._galaxy_history_installed = True
    return window_cls


def run_history_self_test() -> None:
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

        media = downloads / "demo.mp4"
        media.write_bytes(b"demo")
        item = append_history(
            FakeEngine,
            {
                "state": "completed",
                "sourceUrl": "https://user:secret@example.com/watch/123?token=hidden#fragment",
                "filePath": str(media),
                "fileName": media.name,
                "videoQuality": "1080",
                "audioQuality": "best",
                "collectionMode": "single",
            },
        )
        assert item is not None
        assert item["sourceUrl"] == "https://example.com/watch/123"
        assert "hidden" not in json.dumps(item)
        assert load_history(FakeEngine)[0]["fileName"] == "demo.mp4"
        assert clear_history(FakeEngine) == 1
        assert load_history(FakeEngine) == []
