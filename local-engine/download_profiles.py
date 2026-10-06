from __future__ import annotations

import fnmatch
import json
import math
import re
import threading
import uuid
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import urlsplit

from runtime_storage import state_dir as runtime_state_dir

STATE_FILENAME = "download-profiles.json"
STATE_VERSION = 1
MAX_PROFILES = 200
MAX_PATTERNS_PER_PROFILE = 100
MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_TEXT = 4096
_CONTAINER_VALUES = frozenset({"", "mp4", "mkv", "webm"})
_BROWSER_VALUES = frozenset({"none", "edge", "chrome", "firefox", "brave"})
_POST_PROCESS_VALUES = frozenset({"", "none", "remux", "convert"})
_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_NAME_RE = re.compile(r"[^\x00-\x1f\x7f]+")
_HOST_PATTERN_RE = re.compile(r"^[a-z0-9*.-]+$")
_LOCK = threading.RLock()


class DownloadProfileError(RuntimeError):
    pass


def profile_state_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / STATE_FILENAME


def _clean_text(value: object, *, limit: int = MAX_TEXT) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise DownloadProfileError(f"text exceeds {limit} characters")
    if text and not _NAME_RE.fullmatch(text):
        raise DownloadProfileError("text contains control characters")
    return text


def _clean_name(value: object) -> str:
    text = _clean_text(value, limit=120)
    if not text:
        raise DownloadProfileError("profile name is required")
    return text


def _clean_id(value: object) -> str:
    candidate = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(candidate):
        raise DownloadProfileError("invalid profile id")
    return candidate


def _clean_relative_directory(value: object) -> str:
    text = _clean_text(value, limit=240).replace("\\", "/")
    if not text:
        return ""
    if text.startswith("/") or re.match(r"^[a-zA-Z]:", text):
        raise DownloadProfileError("profile directory must be relative")
    path = PurePosixPath(text)
    parts = path.parts
    if not parts or len(parts) > 8:
        raise DownloadProfileError("profile directory is invalid")
    for part in parts:
        if part in {"", ".", ".."} or part.endswith((" ", ".")) or ":" in part:
            raise DownloadProfileError("profile directory contains an unsafe segment")
        if len(part) > 120:
            raise DownloadProfileError("profile directory segment is too long")
    return "/".join(parts)


def _clean_rate(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise DownloadProfileError("rateLimitMiB must be numeric")
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise DownloadProfileError("rateLimitMiB must be numeric") from exc
    if not math.isfinite(rate) or not 0.1 <= rate <= 1024.0:
        raise DownloadProfileError("rateLimitMiB must be between 0.1 and 1024")
    return round(rate, 4)


def _clean_script(value: object) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, Mapping) else {}
    allowed = {"enabled", "preDownload", "postDownload", "postPlaylist"}
    unknown = set(raw) - allowed
    if unknown:
        raise DownloadProfileError(f"unsupported script fields: {', '.join(sorted(unknown))}")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise DownloadProfileError("script.enabled must be boolean")
    return {
        "enabled": enabled,
        "preDownload": _clean_text(raw.get("preDownload", "")),
        "postDownload": _clean_text(raw.get("postDownload", "")),
        "postPlaylist": _clean_text(raw.get("postPlaylist", "")),
    }


def normalize_settings(value: object) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, Mapping) else {}
    allowed = {
        "video",
        "audio",
        "container",
        "subtitle",
        "archive",
        "browser",
        "directory",
        "filename",
        "rateLimitMiB",
        "chapters",
        "sponsorBlock",
        "postProcess",
        "script",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise DownloadProfileError(f"unsupported profile settings: {', '.join(sorted(unknown))}")

    container = _clean_text(raw.get("container", ""), limit=16).lower()
    if container not in _CONTAINER_VALUES:
        raise DownloadProfileError("unsupported container")
    browser = _clean_text(raw.get("browser", "none"), limit=16).lower() or "none"
    if browser not in _BROWSER_VALUES:
        raise DownloadProfileError("unsupported browser")
    post_process = _clean_text(raw.get("postProcess", ""), limit=16).lower()
    if post_process not in _POST_PROCESS_VALUES:
        raise DownloadProfileError("unsupported postProcess")

    archive = raw.get("archive", False)
    chapters = raw.get("chapters", False)
    sponsor_block = raw.get("sponsorBlock", False)
    for field, flag in (("archive", archive), ("chapters", chapters), ("sponsorBlock", sponsor_block)):
        if not isinstance(flag, bool):
            raise DownloadProfileError(f"{field} must be boolean")

    return {
        "video": _clean_text(raw.get("video", "best"), limit=128) or "best",
        "audio": _clean_text(raw.get("audio", "best"), limit=128) or "best",
        "container": container,
        "subtitle": _clean_text(raw.get("subtitle", ""), limit=128),
        "archive": archive,
        "browser": browser,
        "directory": _clean_relative_directory(raw.get("directory", "")),
        "filename": _clean_text(raw.get("filename", ""), limit=240),
        "rateLimitMiB": _clean_rate(raw.get("rateLimitMiB")),
        "chapters": chapters,
        "sponsorBlock": sponsor_block,
        "postProcess": post_process,
        "script": _clean_script(raw.get("script")),
    }


def normalize_pattern(value: object) -> str:
    text = _clean_text(value, limit=300).strip().lower()
    if not text:
        raise DownloadProfileError("URL pattern is empty")
    candidate = text if "://" in text else f"https://{text}"
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DownloadProfileError("URL pattern must target HTTP(S)")
    if parsed.username or parsed.password or parsed.port is not None:
        raise DownloadProfileError("URL pattern cannot contain credentials or a port")
    if parsed.query or parsed.fragment:
        raise DownloadProfileError("URL pattern cannot contain query or fragment")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or not _HOST_PATTERN_RE.fullmatch(host) or ".." in host:
        raise DownloadProfileError("URL pattern host is invalid")
    path = parsed.path or "/"
    if not path.startswith("/") or "\x00" in path:
        raise DownloadProfileError("URL pattern path is invalid")
    normalized = f"{host}{path}"
    if len(normalized) > 300:
        raise DownloadProfileError("URL pattern is too long")
    return normalized


def pattern_matches(pattern: object, url: object) -> bool:
    try:
        normalized = normalize_pattern(pattern)
    except DownloadProfileError:
        return False
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return False
    target = f"{parsed.hostname.lower().rstrip('.')}{parsed.path or '/'}"
    return fnmatch.fnmatchcase(target, normalized)


def _normalize_patterns(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DownloadProfileError("patterns must be a list")
    if len(value) > MAX_PATTERNS_PER_PROFILE:
        raise DownloadProfileError("too many URL patterns")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        pattern = normalize_pattern(item)
        if pattern not in seen:
            seen.add(pattern)
            result.append(pattern)
    return result


def _normalize_profile(value: object, *, preserve_id: bool = True) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DownloadProfileError("profile must be an object")
    raw = dict(value)
    allowed = {"id", "name", "patterns", "settings"}
    unknown = set(raw) - allowed
    if unknown:
        raise DownloadProfileError(f"unsupported profile fields: {', '.join(sorted(unknown))}")
    profile_id = _clean_id(raw.get("id")) if preserve_id and raw.get("id") else uuid.uuid4().hex
    return {
        "id": profile_id,
        "name": _clean_name(raw.get("name")),
        "patterns": _normalize_patterns(raw.get("patterns", [])),
        "settings": normalize_settings(raw.get("settings")),
    }


def _empty_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "profiles": []}


def _load_state(engine_module) -> dict[str, Any]:
    path = profile_state_path(engine_module)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return _empty_state()
    except OSError as exc:
        raise DownloadProfileError("download profile state is unavailable") from exc
    if len(raw) > MAX_IMPORT_BYTES:
        raise DownloadProfileError("download profile state is too large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise DownloadProfileError("download profile state is invalid") from exc
    if not isinstance(payload, Mapping) or payload.get("version") != STATE_VERSION:
        raise DownloadProfileError("unsupported download profile state version")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or len(profiles) > MAX_PROFILES:
        raise DownloadProfileError("download profile state is invalid")
    normalized = [_normalize_profile(item) for item in profiles]
    ids = [item["id"] for item in normalized]
    if len(ids) != len(set(ids)):
        raise DownloadProfileError("duplicate download profile id")
    return {"version": STATE_VERSION, "profiles": normalized}


def _write_state(engine_module, state: Mapping[str, Any]) -> None:
    path = profile_state_path(engine_module)
    temporary = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(data.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise DownloadProfileError("download profile state is too large")
    try:
        temporary.write_text(data, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise DownloadProfileError("failed to save download profiles") from exc


def list_profiles(engine_module) -> list[dict[str, Any]]:
    with _LOCK:
        return deepcopy(_load_state(engine_module)["profiles"])


def create_profile(engine_module, name: object, *, settings: object = None, patterns: object = None) -> dict[str, Any]:
    with _LOCK:
        state = _load_state(engine_module)
        if len(state["profiles"]) >= MAX_PROFILES:
            raise DownloadProfileError("too many download profiles")
        profile = _normalize_profile({"name": name, "settings": settings or {}, "patterns": patterns or []}, preserve_id=False)
        state["profiles"].append(profile)
        _write_state(engine_module, state)
        return deepcopy(profile)


def duplicate_profile(engine_module, profile_id: object, *, name: object | None = None) -> dict[str, Any]:
    source = get_profile(engine_module, profile_id)
    return create_profile(
        engine_module,
        name if name is not None else f"{source['name']} Copy",
        settings=source["settings"],
        patterns=source["patterns"],
    )


def get_profile(engine_module, profile_id: object) -> dict[str, Any]:
    clean = _clean_id(profile_id)
    with _LOCK:
        for profile in _load_state(engine_module)["profiles"]:
            if profile["id"] == clean:
                return deepcopy(profile)
    raise DownloadProfileError("download profile not found")


def update_profile(
    engine_module,
    profile_id: object,
    *,
    name: object | None = None,
    settings: object | None = None,
    patterns: object | None = None,
) -> dict[str, Any]:
    clean = _clean_id(profile_id)
    with _LOCK:
        state = _load_state(engine_module)
        for index, current in enumerate(state["profiles"]):
            if current["id"] != clean:
                continue
            updated = {
                "id": clean,
                "name": current["name"] if name is None else name,
                "settings": current["settings"] if settings is None else settings,
                "patterns": current["patterns"] if patterns is None else patterns,
            }
            normalized = _normalize_profile(updated)
            state["profiles"][index] = normalized
            _write_state(engine_module, state)
            return deepcopy(normalized)
    raise DownloadProfileError("download profile not found")


def delete_profile(engine_module, profile_id: object) -> bool:
    clean = _clean_id(profile_id)
    with _LOCK:
        state = _load_state(engine_module)
        filtered = [profile for profile in state["profiles"] if profile["id"] != clean]
        if len(filtered) == len(state["profiles"]):
            return False
        state["profiles"] = filtered
        _write_state(engine_module, state)
        return True


def resolve_profile(engine_module, url: object, *, manual_profile_id: object | None = None) -> dict[str, Any] | None:
    if manual_profile_id not in {None, ""}:
        return get_profile(engine_module, manual_profile_id)
    profiles = list_profiles(engine_module)
    for profile in profiles:
        if any(pattern_matches(pattern, url) for pattern in profile["patterns"]):
            return profile
    return None


def export_profiles(engine_module) -> str:
    with _LOCK:
        state = _load_state(engine_module)
    return json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def import_profiles(engine_module, content: object, *, replace: bool = False) -> list[dict[str, Any]]:
    if isinstance(content, bytes):
        raw = bytes(content)
    else:
        raw = str(content or "").encode("utf-8")
    if not raw or len(raw) > MAX_IMPORT_BYTES:
        raise DownloadProfileError("profile import payload size is invalid")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise DownloadProfileError("profile import payload is invalid") from exc
    if not isinstance(payload, Mapping) or payload.get("version") != STATE_VERSION:
        raise DownloadProfileError("unsupported profile import version")
    imported = payload.get("profiles")
    if not isinstance(imported, list) or len(imported) > MAX_PROFILES:
        raise DownloadProfileError("profile import payload is invalid")
    normalized = [_normalize_profile(item) for item in imported]
    imported_ids = [item["id"] for item in normalized]
    if len(imported_ids) != len(set(imported_ids)):
        raise DownloadProfileError("duplicate profile id in import")

    with _LOCK:
        if replace:
            final = normalized
        else:
            state = _load_state(engine_module)
            existing = {profile["id"] for profile in state["profiles"]}
            final = list(state["profiles"])
            for profile in normalized:
                candidate = deepcopy(profile)
                if candidate["id"] in existing:
                    candidate["id"] = uuid.uuid4().hex
                existing.add(candidate["id"])
                final.append(candidate)
            if len(final) > MAX_PROFILES:
                raise DownloadProfileError("too many download profiles after import")
        _write_state(engine_module, {"version": STATE_VERSION, "profiles": final})
        return deepcopy(final)
