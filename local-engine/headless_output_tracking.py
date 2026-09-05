from __future__ import annotations

import re
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

import headless_service as _service

MAX_TRACKING_SESSIONS = 500
MAX_OUTPUTS_PER_SESSION = 10_000
_TRACKING_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_LOCK = threading.RLock()
_OUTPUTS: OrderedDict[str, list[str]] = OrderedDict()
_INSTALLED = False


class HeadlessOutputTrackingError(_service.HeadlessServiceError):
    pass


def _clean_tracking_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _TRACKING_ID_RE.fullmatch(clean):
        raise HeadlessOutputTrackingError("invalid output tracking id")
    return clean


def _ensure_session_locked(tracking_id: str) -> list[str]:
    outputs = _OUTPUTS.get(tracking_id)
    if outputs is None:
        outputs = []
        _OUTPUTS[tracking_id] = outputs
    else:
        _OUTPUTS.move_to_end(tracking_id)
    while len(_OUTPUTS) > MAX_TRACKING_SESSIONS:
        _OUTPUTS.popitem(last=False)
    return outputs


def new_output_tracking_id() -> str:
    tracking_id = uuid.uuid4().hex
    with _LOCK:
        _ensure_session_locked(tracking_id)
    return tracking_id


def _safe_output_path(root: Path, filename: object) -> Path | None:
    raw = str(filename or "").strip()
    if not raw:
        return None
    try:
        safe_root = Path(root).expanduser().resolve(strict=False)
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = safe_root / candidate
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(safe_root)
        return resolved
    except (OSError, RuntimeError, ValueError):
        return None


def _record_output(tracking_id: str, root: Path, filename: object) -> None:
    output = _safe_output_path(root, filename)
    if output is None:
        return
    rendered = str(output)
    with _LOCK:
        values = _ensure_session_locked(tracking_id)
        if rendered in values:
            return
        if len(values) >= MAX_OUTPUTS_PER_SESSION:
            return
        values.append(rendered)


def tracked_output_paths(tracking_id: object, *, existing_only: bool = True) -> list[Path]:
    clean = _clean_tracking_id(tracking_id)
    with _LOCK:
        values = list(_OUTPUTS.get(clean) or [])
        if clean in _OUTPUTS:
            _OUTPUTS.move_to_end(clean)
    result: list[Path] = []
    for value in values:
        path = Path(value)
        if existing_only and not path.is_file():
            continue
        result.append(path)
    return result


def clear_output_tracking(tracking_id: object) -> int:
    clean = _clean_tracking_id(tracking_id)
    with _LOCK:
        values = _OUTPUTS.pop(clean, [])
    return len(values)


def install_headless_output_tracking() -> None:
    """Compose final-file tracking onto the current Headless download options."""

    global _INSTALLED
    if _INSTALLED:
        return

    original_download_options = _service._download_options

    def download_options_with_tracking(payload: dict[str, Any], root: Path, progress_hook) -> dict[str, Any]:
        options = original_download_options(payload, root, progress_hook)
        raw_tracking_id = payload.get("_outputTrackingId")
        if raw_tracking_id in {None, ""}:
            return options
        tracking_id = _clean_tracking_id(raw_tracking_id)

        def capture_final_output(filename: str) -> None:
            _record_output(tracking_id, root, filename)

        post_hooks = list(options.get("post_hooks") or [])
        post_hooks.append(capture_final_output)
        options["post_hooks"] = post_hooks
        return options

    _service._download_options = download_options_with_tracking
    _INSTALLED = True
