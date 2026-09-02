from __future__ import annotations

import json
import re
import shutil
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import external_ytdlp

PREFERENCES_FILENAME = "media-options.json"
SUBTITLE_MODES = {"manual", "auto", "both"}
SPONSORBLOCK_CATEGORIES = {
    "sponsor",
    "selfpromo",
    "interaction",
    "intro",
    "outro",
    "preview",
    "music_offtopic",
    "filler",
}
LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_MEDIA_CONTEXT = threading.local()

DEFAULT_PREFERENCES: dict[str, Any] = {
    "segmentStart": "",
    "segmentEnd": "",
    "splitChapters": False,
    "includeSubtitle": False,
    "subtitleMode": "both",
    "subtitleLanguages": [],
    "audioLanguages": [],
    "sponsorBlockCategories": [],
    "useAria2c": False,
}


def _state_path(engine_module) -> Path:
    target = engine_module.app_dir() / "state"
    target.mkdir(parents=True, exist_ok=True)
    return target / PREFERENCES_FILENAME


def _clean_preferences(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    subtitle_mode = str(raw.get("subtitleMode") or "both").strip().lower()
    if subtitle_mode not in SUBTITLE_MODES:
        subtitle_mode = "both"
    return {
        "segmentStart": str(raw.get("segmentStart") or "").strip()[:16],
        "segmentEnd": str(raw.get("segmentEnd") or "").strip()[:16],
        "splitChapters": bool(raw.get("splitChapters", False)),
        "includeSubtitle": bool(raw.get("includeSubtitle", False)),
        "subtitleMode": subtitle_mode,
        "subtitleLanguages": list(_validated_languages(raw.get("subtitleLanguages"))),
        "audioLanguages": list(_validated_languages(raw.get("audioLanguages"))),
        "sponsorBlockCategories": list(_validated_sponsor_categories(raw.get("sponsorBlockCategories"))),
        "useAria2c": bool(raw.get("useAria2c", False)),
    }


def load_preferences(engine_module) -> dict[str, Any]:
    path = _state_path(engine_module)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return dict(DEFAULT_PREFERENCES)
    return _clean_preferences(raw)


def save_preferences(engine_module, preferences: dict[str, Any]) -> dict[str, Any]:
    cleaned = _clean_preferences(preferences)
    path = _state_path(engine_module)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return cleaned


def _parse_time(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if ":" not in text:
            seconds = float(text)
        else:
            parts = text.split(":")
            if len(parts) not in {2, 3}:
                return None
            numbers = [float(part) for part in parts]
            if any(number < 0 for number in numbers):
                return None
            if len(numbers) == 2:
                seconds = numbers[0] * 60 + numbers[1]
            else:
                seconds = numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
        if seconds < 0 or seconds > 7 * 24 * 60 * 60:
            return None
        return round(seconds, 3)
    except (TypeError, ValueError):
        return None


def _time_text(seconds: float | None) -> str:
    if seconds is None:
        return ""
    whole = int(seconds)
    millis = seconds - whole
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    suffix = f"{millis:.3f}"[1:].rstrip("0") if millis else ""
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}{suffix}"
    return f"{minutes:02d}:{secs:02d}{suffix}"


def _validated_languages(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values = re.split(r"[,\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = []
    result: list[str] = []
    for raw in raw_values:
        language = str(raw or "").strip()
        if LANGUAGE_RE.fullmatch(language) and language not in result:
            result.append(language)
        if len(result) >= 12:
            break
    return tuple(result)


def _validated_sponsor_categories(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values = re.split(r"[,\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = []
    result: list[str] = []
    for raw in raw_values:
        category = str(raw or "").strip().lower()
        if category in SPONSORBLOCK_CATEGORIES and category not in result:
            result.append(category)
    return tuple(result)


def _valid_segment(start: float | None, end: float | None) -> tuple[float | None, float | None]:
    if start is None and end is None:
        return None, None
    if start is None or end is None or end <= start:
        return None, None
    return start, end


def _aria2c_path(app_dir: Path) -> Path | None:
    for candidate in (
        app_dir / "aria2c.exe",
        app_dir / "bin" / "aria2c.exe",
        app_dir / "aria2c",
        app_dir / "bin" / "aria2c",
    ):
        if candidate.exists() and candidate.is_file():
            return candidate
    resolved = shutil.which("aria2c")
    return Path(resolved) if resolved else None


def aria2c_available(engine_module) -> bool:
    return _aria2c_path(engine_module.app_dir()) is not None


def _merge_payload_defaults(engine_module, payload: dict[str, Any]) -> dict[str, Any]:
    preferences = load_preferences(engine_module)
    merged = dict(payload)
    for key, value in preferences.items():
        merged.setdefault(key, value)
    return merged


def _replace_flag_value(command: list[str], flag: str, value: str) -> None:
    try:
        index = command.index(flag)
    except ValueError:
        return
    if index + 1 < len(command):
        command[index + 1] = value


def _insert_before_source(command: list[str], values: list[str]) -> None:
    try:
        index = command.index("--")
    except ValueError:
        index = len(command)
    command[index:index] = values


def _apply_external_command(job: Any, command: list[str], executable: Path) -> list[str]:
    if job is None:
        return command

    start, end = _valid_segment(
        getattr(job, "segment_start", None),
        getattr(job, "segment_end", None),
    )
    additions: list[str] = []
    if start is not None and end is not None:
        additions.extend([
            "--download-sections",
            f"*{_time_text(start)}-{_time_text(end)}",
            "--force-keyframes-at-cuts",
        ])

    if bool(getattr(job, "split_chapters", False)):
        additions.append("--split-chapters")

    if bool(getattr(job, "include_subtitle", False)):
        mode = str(getattr(job, "subtitle_mode", "both") or "both")
        if mode == "manual":
            command = [value for value in command if value != "--write-auto-subs"]
        elif mode == "auto":
            command = [value for value in command if value != "--write-subs"]
        languages = tuple(getattr(job, "subtitle_languages", ()) or ())
        if languages:
            _replace_flag_value(command, "--sub-langs", ",".join(languages))

    audio_languages = tuple(getattr(job, "audio_languages", ()) or ())
    if len(audio_languages) > 1:
        additions.append("--audio-multistreams")

    sponsor_categories = tuple(getattr(job, "sponsorblock_categories", ()) or ())
    if sponsor_categories:
        additions.extend(["--sponsorblock-remove", ",".join(sponsor_categories)])

    if bool(getattr(job, "use_aria2c", False)):
        aria2 = _aria2c_path(executable.resolve().parent)
        if aria2 is not None:
            additions.extend([
                "--downloader",
                str(aria2),
                "--downloader-args",
                "aria2c:-x16 -s16 -k1M --file-allocation=none",
            ])

    if additions:
        _insert_before_source(command, additions)
    return command


def install_media_policy(engine_module):
    """Add opt-in segment/chapter/subtitle/audio/SponsorBlock/aria2 settings.

    The website can send these fields per job. When it does not, the desktop UI
    preferences are used. Every advanced behavior is disabled by default. The
    bundled yt-dlp remains the orchestrator; aria2c is only an optional external
    downloader selected by yt-dlp when the user explicitly enables it.
    """
    if getattr(engine_module, "_galaxy_media_policy_installed", False):
        return engine_module.Job

    base_job = engine_module.Job

    @dataclass(frozen=True)
    class MediaJob(base_job):
        segment_start: float | None = None
        segment_end: float | None = None
        split_chapters: bool = False
        subtitle_mode: str = "both"
        subtitle_languages: tuple[str, ...] = ()
        audio_languages: tuple[str, ...] = ()
        sponsorblock_categories: tuple[str, ...] = ()
        use_aria2c: bool = False

    MediaJob.__name__ = "Job"
    MediaJob.__qualname__ = "Job"
    engine_module.Job = MediaJob

    original_parse_job = engine_module.parse_job
    original_job_from_payload = engine_module.job_from_payload
    original_job_to_payload = engine_module.job_to_payload

    def parse_job(raw: str):
        job = original_parse_job(raw)
        query = parse_qs(urlparse(raw).query)
        preferences = load_preferences(engine_module)
        start = _parse_time(query.get("section_start", [preferences["segmentStart"]])[0])
        end = _parse_time(query.get("section_end", [preferences["segmentEnd"]])[0])
        start, end = _valid_segment(start, end)
        subtitle_mode = str(query.get("subtitle_mode", [preferences["subtitleMode"]])[0]).strip().lower()
        if subtitle_mode not in SUBTITLE_MODES:
            subtitle_mode = "both"
        return replace(
            job,
            include_subtitle=engine_module._bool(
                query.get("subtitle", ["1" if preferences["includeSubtitle"] else "0"])[0]
            ),
            segment_start=start,
            segment_end=end,
            split_chapters=engine_module._bool(
                query.get("split_chapters", ["1" if preferences["splitChapters"] else "0"])[0]
            ),
            subtitle_mode=subtitle_mode,
            subtitle_languages=_validated_languages(
                query.get("subtitle_langs", [",".join(preferences["subtitleLanguages"])])[0]
            ),
            audio_languages=_validated_languages(
                query.get("audio_langs", [",".join(preferences["audioLanguages"])])[0]
            ),
            sponsorblock_categories=_validated_sponsor_categories(
                query.get("sponsorblock", [",".join(preferences["sponsorBlockCategories"])])[0]
            ),
            use_aria2c=engine_module._bool(
                query.get("aria2", ["1" if preferences["useAria2c"] else "0"])[0]
            ),
        )

    def job_from_payload(payload: dict[str, Any]):
        merged = _merge_payload_defaults(engine_module, payload)
        job = original_job_from_payload(merged)
        start = _parse_time(merged.get("segmentStart"))
        end = _parse_time(merged.get("segmentEnd"))
        start, end = _valid_segment(start, end)
        subtitle_mode = str(merged.get("subtitleMode") or "both").strip().lower()
        if subtitle_mode not in SUBTITLE_MODES:
            subtitle_mode = "both"
        return replace(
            job,
            segment_start=start,
            segment_end=end,
            split_chapters=bool(merged.get("splitChapters", False)),
            subtitle_mode=subtitle_mode,
            subtitle_languages=_validated_languages(merged.get("subtitleLanguages")),
            audio_languages=_validated_languages(merged.get("audioLanguages")),
            sponsorblock_categories=_validated_sponsor_categories(merged.get("sponsorBlockCategories")),
            use_aria2c=bool(merged.get("useAria2c", False)),
        )

    def job_to_payload(job) -> dict[str, Any]:
        payload = original_job_to_payload(job)
        payload.update(
            segmentStart=_time_text(getattr(job, "segment_start", None)),
            segmentEnd=_time_text(getattr(job, "segment_end", None)),
            splitChapters=bool(getattr(job, "split_chapters", False)),
            subtitleMode=str(getattr(job, "subtitle_mode", "both") or "both"),
            subtitleLanguages=list(getattr(job, "subtitle_languages", ()) or ()),
            audioLanguages=list(getattr(job, "audio_languages", ()) or ()),
            sponsorBlockCategories=list(getattr(job, "sponsorblock_categories", ()) or ()),
            useAria2c=bool(getattr(job, "use_aria2c", False)),
        )
        return payload

    engine_module.parse_job = parse_job
    engine_module.job_from_payload = job_from_payload
    engine_module.job_to_payload = job_to_payload

    original_format_selector = engine_module.format_selector

    def format_selector(job) -> str:
        base = original_format_selector(job)
        languages = tuple(getattr(job, "audio_languages", ()) or ())
        if not bool(getattr(job, "include_audio", True)) or not languages:
            return base
        raw_height = re.search(r"(\d{3,4})", str(getattr(job, "video_quality", "")))
        height = int(raw_height.group(1)) if raw_height else None
        video = f"bv[height<={height}]" if height else "bv"
        audio_parts = [f"ba[language^={language}]" for language in languages]
        return f"{video}+{'+'.join(audio_parts)}/{base}"

    engine_module.format_selector = format_selector

    original_build_options = engine_module.EngineWindow.build_options

    def build_options(window) -> dict[str, Any]:
        options = original_build_options(window)
        job = window.job
        if job is None:
            return options
        mode = str(getattr(job, "subtitle_mode", "both") or "both")
        if bool(getattr(job, "include_subtitle", False)):
            options["writesubtitles"] = mode in {"manual", "both"}
            options["writeautomaticsub"] = mode in {"auto", "both"}
            languages = tuple(getattr(job, "subtitle_languages", ()) or ())
            if languages:
                options["subtitleslangs"] = list(languages)
        if len(tuple(getattr(job, "audio_languages", ()) or ())) > 1:
            options["allow_multiple_audio_streams"] = True
        sponsor_categories = tuple(getattr(job, "sponsorblock_categories", ()) or ())
        if sponsor_categories:
            options["sponsorblock_remove"] = set(sponsor_categories)
        return options

    engine_module.EngineWindow.build_options = build_options

    original_external_command = external_ytdlp.build_external_command

    def build_external_command(*args, **kwargs):
        command = original_external_command(*args, **kwargs)
        executable = Path(args[0] if args else kwargs.get("executable"))
        return _apply_external_command(getattr(_MEDIA_CONTEXT, "job", None), command, executable)

    external_ytdlp.build_external_command = build_external_command

    original_run_external_job = engine_module.EngineWindow._run_external_job

    def run_external_job(window, executable):
        _MEDIA_CONTEXT.job = window.job
        try:
            return original_run_external_job(window, executable)
        finally:
            _MEDIA_CONTEXT.job = None

    engine_module.EngineWindow._run_external_job = run_external_job

    original_bridge_status = engine_module.EngineWindow.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        payload["aria2Ready"] = aria2c_available(engine_module)
        payload["advancedMedia"] = True
        return payload

    engine_module.EngineWindow.bridge_status = bridge_status
    engine_module._galaxy_media_policy_installed = True
    return MediaJob
