from __future__ import annotations

from runtime_storage import state_dir as runtime_state_dir

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from batch_identity import batch_identity_from_payload
from failure_policy import classify_failure, sanitize_failure_detail
from workspace_policy import load_workspace_preferences

HISTORY_FILENAME = "download-history.json"
DEFAULT_MAX_HISTORY_ITEMS = 80
_HISTORY_LOCK = threading.Lock()
_TERMINAL_STATES = {"completed", "failed", "cancelled"}
_SAFE_YOUTUBE_QUERY_KEYS = {"v", "list", "index"}
_RETRY_PAYLOAD_KEYS = {
    "sourceUrl",
    "videoQuality",
    "audioQuality",
    "includeAudio",
    "includeSubtitle",
    "subtitleLanguage",
    "includeCover",
    "skipPreviouslyDownloaded",
    "browser",
    "collectionMode",
    "selectedItems",
    "playlist",
    "segmentStart",
    "segmentEnd",
    "splitChapters",
    "subtitleMode",
    "subtitleLanguages",
    "audioLanguages",
    "sponsorBlockCategories",
    "useAria2c",
    # v0.14 smart recovery fields are per-job and contain no credentials.
    "networkRetryProfile",
    "rateLimitMbps",
    "concurrentFragments",
    "batchId",
    "batchIndex",
    "batchSize",
}


def _history_path(engine_module) -> Path:
    state_dir = runtime_state_dir(engine_module)
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / HISTORY_FILENAME


def _history_limit(engine_module) -> int:
    try:
        return int(load_workspace_preferences(engine_module).get("historyLimit") or DEFAULT_MAX_HISTORY_ITEMS)
    except Exception:
        return DEFAULT_MAX_HISTORY_ITEMS


def _safe_text(value: object, limit: int = 240) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _safe_url_parts(value: object) -> tuple[object | None, str, str]:
    raw = str(value or "").strip()
    if not raw:
        return None, "", ""
    try:
        parsed = urlsplit(raw)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not hostname:
            return None, "", ""
        host = hostname
        try:
            if parsed.port:
                host = f"{host}:{parsed.port}"
        except ValueError:
            pass
        return parsed, host, hostname
    except ValueError:
        return None, "", ""


def _redacted_source_url(value: object) -> tuple[str, str]:
    parsed, host, hostname = _safe_url_parts(value)
    if parsed is None:
        return "", ""
    display = urlunsplit((parsed.scheme, host, parsed.path or "/", "", ""))
    return display[:600], hostname[:160]


def _retry_source_url(value: object) -> tuple[str, str]:
    """Keep only URL identity fields that are known to be non-secret.

    Most media sites identify a post/video in the path, so all query data is
    dropped. YouTube's watch URL is the important exception: v/list/index are
    stable media identifiers and are preserved, while tracking/session fields
    such as si, feature and tokens are removed.
    """
    parsed, host, hostname = _safe_url_parts(value)
    if parsed is None:
        return "", ""
    query = ""
    if hostname in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        safe_pairs: list[tuple[str, str]] = []
        for key, raw_value in parse_qsl(parsed.query, keep_blank_values=False):
            if key in _SAFE_YOUTUBE_QUERY_KEYS:
                safe_pairs.append((key, raw_value[:200]))
        query = urlencode(safe_pairs)
    retry = urlunsplit((parsed.scheme, host, parsed.path or "/", query, ""))
    return retry[:700], hostname[:160]


def _safe_retry_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in _RETRY_PAYLOAD_KEYS:
        if key not in value:
            continue
        raw = value.get(key)
        if key == "sourceUrl":
            source, _host = _retry_source_url(raw)
            if source:
                result[key] = source
            continue
        if key == "selectedItems":
            items: list[int] = []
            for candidate in raw if isinstance(raw, (list, tuple)) else []:
                try:
                    number = int(candidate)
                except (TypeError, ValueError):
                    continue
                if number > 0 and number not in items:
                    items.append(number)
                if len(items) >= 500:
                    break
            result[key] = items
            continue
        if key in {"subtitleLanguages", "audioLanguages", "sponsorBlockCategories"}:
            values: list[str] = []
            for candidate in raw if isinstance(raw, (list, tuple)) else []:
                text = _safe_text(candidate, 40)
                if text and text not in values:
                    values.append(text)
                if len(values) >= 16:
                    break
            result[key] = values
            continue
        if key in {
            "includeAudio",
            "includeSubtitle",
            "includeCover",
            "skipPreviouslyDownloaded",
            "playlist",
            "splitChapters",
            "useAria2c",
        }:
            result[key] = bool(raw)
            continue
        if key in {"rateLimitMbps", "concurrentFragments"}:
            try:
                result[key] = int(raw)
            except (TypeError, ValueError):
                continue
            continue
        result[key] = None if raw is None else _safe_text(raw, 120)
    batch_id, batch_index, batch_size = batch_identity_from_payload(result)
    result.pop("batchId", None)
    result.pop("batchIndex", None)
    result.pop("batchSize", None)
    if batch_id is not None:
        result["batchId"] = batch_id
        result["batchIndex"] = batch_index
        result["batchSize"] = batch_size
    if not result.get("sourceUrl"):
        return {}
    return result


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


def _failure_fields(detail: str, state: str) -> dict[str, Any]:
    classified = classify_failure(detail, state)
    return {
        "failureCategory": str(classified.get("category") or ""),
        "failureLabel": str(classified.get("label") or "")[:80],
        "failureAdvice": str(classified.get("advice") or "")[:360],
        "smartRetryable": bool(classified.get("smartRetryable", False)),
    }


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
    retry_payload = _safe_retry_payload(value.get("retryPayload"))
    batch_id, batch_index, batch_size = batch_identity_from_payload(retry_payload)
    detail = sanitize_failure_detail(value.get("detail"), 360)
    result = {
        "id": _safe_text(value.get("id"), 64) or uuid.uuid4().hex,
        "finishedAt": _safe_text(value.get("finishedAt"), 40),
        "state": state,
        "label": _safe_text(value.get("label"), 220) or file_name or source_host or "Download",
        "sourceHost": source_host,
        "sourceUrl": source_url,
        "detail": detail,
        "fileName": file_name,
        "filePath": file_path,
        "videoQuality": _safe_text(value.get("videoQuality"), 40),
        "audioQuality": _safe_text(value.get("audioQuality"), 40),
        "collectionMode": _safe_text(value.get("collectionMode"), 24),
        "batchId": batch_id,
        "batchIndex": batch_index,
        "batchSize": batch_size,
        "durationSeconds": round(duration, 1),
        "retryPayload": retry_payload,
        "retryable": bool(retry_payload.get("sourceUrl")),
    }
    result.update(_failure_fields(detail, state))
    return result


def load_history(engine_module) -> list[dict[str, Any]]:
    path = _history_path(engine_module)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    values = raw if isinstance(raw, list) else []
    limit = _history_limit(engine_module)
    result: list[dict[str, Any]] = []
    for value in values[:limit]:
        cleaned = _clean_item(engine_module, value)
        if cleaned is not None:
            result.append(cleaned)
    return result


def _write_history(engine_module, items: list[dict[str, Any]]) -> None:
    limit = _history_limit(engine_module)
    path = _history_path(engine_module)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(items[:limit], ensure_ascii=False, indent=2),
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
    retry_source, _retry_host = _retry_source_url(getattr(job, "source_url", ""))
    file_path = _safe_download_path(engine_module, last_path)
    file_name = Path(file_path).name if file_path else ""
    state = str(snapshot.get("state") or "failed").lower()
    if state not in _TERMINAL_STATES:
        state = "failed"
    detail = sanitize_failure_detail(snapshot.get("detail"), 360)
    label = file_name or source_host or "Download"
    try:
        retry_payload = dict(engine_module.job_to_payload(job))
    except Exception:
        retry_payload = {}
    retry_payload["sourceUrl"] = retry_source
    result = {
        "id": uuid.uuid4().hex,
        "finishedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "state": state,
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
        "retryPayload": retry_payload,
    }
    result.update(_failure_fields(detail, state))
    return result


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
            if not bool(load_workspace_preferences(engine_module).get("historyEnabled", True)):
                return
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
                "retryPayload": {
                    "sourceUrl": "https://www.youtube.com/watch?v=abc123&si=tracking-secret",
                    "videoQuality": "1080",
                    "includeAudio": True,
                },
            },
        )
        assert item is not None
        assert item["sourceUrl"] == "https://example.com/watch/123"
        assert item["retryPayload"]["sourceUrl"] == "https://www.youtube.com/watch?v=abc123"
        assert item["retryable"] is True
        rendered = json.dumps(item)
        assert "hidden" not in rendered
        assert "tracking-secret" not in rendered
        assert "user:secret" not in rendered
        assert load_history(FakeEngine)[0]["fileName"] == "demo.mp4"

        failed = append_history(
            FakeEngine,
            {
                "state": "failed",
                "sourceUrl": "https://example.com/watch/456?session=secret",
                "detail": "HTTP Error 503 https://example.com/watch/456?token=very-secret authorization=raw-secret",
                "retryPayload": {
                    "sourceUrl": "https://example.com/watch/456?token=very-secret",
                    "networkRetryProfile": "standard",
                    "rateLimitMbps": 0,
                    "concurrentFragments": 4,
                },
            },
        )
        assert failed is not None
        assert failed["failureCategory"] == "network"
        assert failed["smartRetryable"] is True
        failed_json = json.dumps(failed)
        assert "very-secret" not in failed_json
        assert "raw-secret" not in failed_json
        assert failed["retryPayload"]["concurrentFragments"] == 4
        assert clear_history(FakeEngine) == 2
        assert load_history(FakeEngine) == []
