from __future__ import annotations

import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import headless_service as _service
from course_subtitles import (
    CourseSubtitleError,
    MAX_SUBTITLE_TRACKS_PER_ITEM,
    normalize_subtitle_tracks,
)
from headless_output_tracking import MAX_OUTPUTS_PER_SESSION, MAX_TRACKING_SESSIONS

_TRACKING_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_PROVIDER_ITEM_RE = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_LOCK = threading.RLock()
_METADATA: OrderedDict[str, OrderedDict[str, dict[str, Any]]] = OrderedDict()


class HeadlessCourseMetadataTrackingError(_service.HeadlessServiceError):
    pass


def _clean_tracking_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _TRACKING_ID_RE.fullmatch(clean):
        raise HeadlessCourseMetadataTrackingError("invalid course metadata tracking id")
    return clean


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


def _movefiles_final_path(info: dict[str, Any]) -> object:
    """Mirror yt-dlp MoveFilesAfterDownloadPP's final-path calculation.

    yt-dlp postprocessor hooks receive a copy of info_dict made before the
    postprocessor executes. Therefore the hook's `filepath` is not guaranteed to
    contain MoveFiles' updated value even when status is `finished`.
    """

    raw_filepath = str(info.get("filepath") or "").strip()
    if not raw_filepath:
        return ""
    filepath = Path(raw_filepath)
    finaldir = str(info.get("__finaldir") or "").strip()
    if not finaldir:
        return raw_filepath
    return str(Path(finaldir) / filepath.name)


def _clean_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _bounded_positive_int(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    if parsed < 1 or parsed > 100_000:
        return 0
    return parsed


def _safe_subtitle_tracks(info: dict[str, Any]) -> list[dict[str, str]]:
    tracks: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for field, kind in (("subtitles", "manual"), ("automatic_captions", "automatic")):
        values = info.get(field)
        if not isinstance(values, dict):
            continue
        for raw_language in values:
            candidate = {"language": str(raw_language or "").strip(), "kind": kind}
            try:
                normalized = normalize_subtitle_tracks([candidate])
            except CourseSubtitleError:
                continue
            if not normalized:
                continue
            track = normalized[0]
            key = (track["language"].lower(), track["kind"])
            if key in seen:
                continue
            if len(tracks) >= MAX_SUBTITLE_TRACKS_PER_ITEM:
                return tracks
            seen.add(key)
            tracks.append(track)
    return tracks


def _udemy_metadata(info: dict[str, Any]) -> dict[str, Any] | None:
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").strip().lower()
    if extractor != "udemy":
        return None

    raw_item_id = str(info.get("id") or "").strip()
    provider_item_id = ""
    if _PROVIDER_ITEM_RE.fullmatch(raw_item_id):
        # UdemyIE's final info ID is the downloadable asset ID. Keep that
        # distinction explicit instead of incorrectly calling it a lecture ID.
        provider_item_id = f"udemy:asset:{raw_item_id}"

    title = _clean_text(info.get("title"), 300)
    chapter = _clean_text(info.get("chapter"), 240)
    chapter_number = _bounded_positive_int(info.get("chapter_number"))
    playlist_index = _bounded_positive_int(info.get("playlist_index"))
    subtitle_tracks = _safe_subtitle_tracks(info)

    if not any((provider_item_id, title, chapter, chapter_number, playlist_index, subtitle_tracks)):
        return None
    return {
        "provider": "udemy",
        "providerItemId": provider_item_id,
        "providerTitle": title,
        "providerPosition": playlist_index,
        "sectionTitle": chapter,
        "sectionPosition": chapter_number,
        "subtitleTracks": subtitle_tracks,
    }


def _ensure_session_locked(tracking_id: str) -> OrderedDict[str, dict[str, Any]]:
    values = _METADATA.get(tracking_id)
    if values is None:
        values = OrderedDict()
        _METADATA[tracking_id] = values
    else:
        _METADATA.move_to_end(tracking_id)
    while len(_METADATA) > MAX_TRACKING_SESSIONS:
        _METADATA.popitem(last=False)
    return values


def _record_metadata(tracking_id: str, root: Path, filename: object, info: dict[str, Any]) -> None:
    output = _safe_output_path(root, filename)
    if output is None:
        return
    metadata = _udemy_metadata(info)
    if metadata is None:
        return
    rendered = str(output)
    with _LOCK:
        values = _ensure_session_locked(tracking_id)
        if rendered in values:
            values[rendered] = metadata
            values.move_to_end(rendered)
            return
        if len(values) >= MAX_OUTPUTS_PER_SESSION:
            return
        values[rendered] = metadata


def tracked_course_metadata(
    tracking_id: object,
    *,
    existing_only: bool = True,
) -> dict[Path, dict[str, Any]]:
    clean = _clean_tracking_id(tracking_id)
    with _LOCK:
        values = OrderedDict(_METADATA.get(clean) or {})
        if clean in _METADATA:
            _METADATA.move_to_end(clean)
    result: dict[Path, dict[str, Any]] = {}
    for rendered, metadata in values.items():
        path = Path(rendered)
        if existing_only and not path.is_file():
            continue
        result[path] = dict(metadata)
    return result


def clear_course_metadata_tracking(tracking_id: object) -> int:
    clean = _clean_tracking_id(tracking_id)
    with _LOCK:
        values = _METADATA.pop(clean, OrderedDict())
    return len(values)


def install_headless_course_metadata_tracking() -> None:
    """Capture a bounded safe metadata subset at yt-dlp's final move step."""

    current_download_options = _service._download_options
    if getattr(current_download_options, "_galaxy_course_metadata_tracking", False):
        return

    def download_options_with_course_metadata(payload: dict[str, Any], root: Path, progress_hook) -> dict[str, Any]:
        options = current_download_options(payload, root, progress_hook)
        raw_tracking_id = payload.get("_outputTrackingId")
        if raw_tracking_id in {None, ""}:
            return options
        tracking_id = _clean_tracking_id(raw_tracking_id)

        def capture_postprocessor(event: dict[str, Any]) -> None:
            if not isinstance(event, dict):
                return
            if str(event.get("status") or "").strip().lower() != "finished":
                return
            if str(event.get("postprocessor") or "").strip() != "MoveFiles":
                return
            info = event.get("info_dict")
            if not isinstance(info, dict):
                return
            _record_metadata(tracking_id, root, _movefiles_final_path(info), info)

        hooks = list(options.get("postprocessor_hooks") or [])
        hooks.append(capture_postprocessor)
        options["postprocessor_hooks"] = hooks
        return options

    download_options_with_course_metadata._galaxy_course_metadata_tracking = True  # type: ignore[attr-defined]
    _service._download_options = download_options_with_course_metadata
