from __future__ import annotations

import threading
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

import external_ytdlp
from download_profiles import DownloadProfileError, resolve_profile

_PROFILE_CONTEXT = threading.local()
_SPONSORBLOCK_DEFAULT = ("sponsor",)


class DownloadProfileApplicationError(RuntimeError):
    pass


def _split_subtitles(value: object) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    result: list[str] = []
    for raw in text.replace(";", ",").split(","):
        language = raw.strip()
        if language and language not in result:
            result.append(language)
        if len(result) >= 12:
            break
    return tuple(result)


def _profile_for(engine_module, url: object, manual_profile_id: object | None = None) -> dict[str, Any] | None:
    try:
        return resolve_profile(engine_module, url, manual_profile_id=manual_profile_id)
    except DownloadProfileError as exc:
        raise DownloadProfileApplicationError(str(exc)) from exc


def _replace_supported(job: Any, **values: Any):
    supported = {field.name for field in fields(job)}
    filtered = {key: value for key, value in values.items() if key in supported}
    return replace(job, **filtered) if filtered else job


def apply_profile_to_job(job: Any, profile: Mapping[str, Any] | None):
    if not profile:
        return job
    settings = dict(profile.get("settings") or {})
    subtitle = str(settings.get("subtitle") or "").strip()
    audio = str(settings.get("audio") or "best").strip() or "best"
    sponsor = bool(settings.get("sponsorBlock", False))
    values: dict[str, Any] = {
        "video_quality": str(settings.get("video") or "best").strip() or "best",
        "audio_quality": audio,
        "include_audio": audio.lower() not in {"none", "off", "false", "0"},
        "include_subtitle": bool(subtitle),
        "subtitle_lang": subtitle or None,
        "browser": str(settings.get("browser") or "none").strip().lower() or "none",
        "skip_previously_downloaded": bool(settings.get("archive", False)),
        "split_chapters": bool(settings.get("chapters", False)),
        "sponsorblock_categories": _SPONSORBLOCK_DEFAULT if sponsor else (),
        "download_profile_id": str(profile.get("id") or ""),
        "download_profile_name": str(profile.get("name") or ""),
        "profile_container": str(settings.get("container") or "").strip().lower(),
        "profile_directory": str(settings.get("directory") or "").strip(),
        "profile_filename": str(settings.get("filename") or "").strip(),
        "profile_rate_limit_mib": settings.get("rateLimitMiB"),
        "profile_post_process": str(settings.get("postProcess") or "").strip().lower(),
    }
    subtitle_languages = _split_subtitles(subtitle)
    if subtitle_languages:
        values["subtitle_languages"] = subtitle_languages
    return _replace_supported(job, **values)


def _safe_filename_template(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "/" in text or "\\" in text or text in {".", ".."}:
        raise DownloadProfileApplicationError("profile filename cannot contain a path separator")
    if "%(ext)" not in text:
        text += ".%(ext)s"
    return text


def profile_output_template(engine_module, job: Any, current: object = "") -> str:
    directory = str(getattr(job, "profile_directory", "") or "").strip()
    filename = _safe_filename_template(getattr(job, "profile_filename", ""))
    if not directory and not filename:
        return str(current or "")
    current_path = Path(str(current or "")) if current else None
    if directory:
        root = Path(engine_module.default_download_dir()).joinpath(
            *directory.replace("\\", "/").split("/")
        )
    elif current_path is not None:
        root = current_path.parent
    else:
        root = Path(engine_module.default_download_dir())
    if not filename:
        current_name = current_path.name if current_path is not None else ""
        filename = current_name or "%(title).180B [%(id)s].%(ext)s"
    return str(root / filename)


def _rate_limit_bytes(job: Any) -> int | None:
    value = getattr(job, "profile_rate_limit_mib", None)
    if value in {None, ""}:
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if rate <= 0:
        return None
    return max(1, int(rate * 1024 * 1024))


def _replace_flag_value(command: list[str], flag: str, value: str) -> None:
    try:
        index = command.index(flag)
    except ValueError:
        return
    if index + 1 < len(command):
        command[index + 1] = value


def _remove_flag_value(command: list[str], flag: str) -> None:
    while flag in command:
        index = command.index(flag)
        del command[index : min(index + 2, len(command))]


def _insert_before_source(command: list[str], values: list[str]) -> None:
    try:
        index = command.index("--")
    except ValueError:
        index = len(command)
    command[index:index] = values


def apply_profile_to_external_command(engine_module, job: Any, command: list[str]) -> list[str]:
    if job is None or not getattr(job, "download_profile_id", ""):
        return command
    container = str(getattr(job, "profile_container", "") or "").strip().lower()
    if container:
        _replace_flag_value(command, "--merge-output-format", container)
    current_output = ""
    try:
        output_index = command.index("-o")
    except ValueError:
        output_index = -1
    if output_index >= 0 and output_index + 1 < len(command):
        current_output = command[output_index + 1]
    output = profile_output_template(engine_module, job, current_output)
    if output:
        _replace_flag_value(command, "-o", output)
    raw_limit = getattr(job, "profile_rate_limit_mib", None)
    if raw_limit not in {None, ""}:
        _remove_flag_value(command, "--limit-rate")
        limit = _rate_limit_bytes(job)
        if limit is not None:
            _insert_before_source(command, ["--limit-rate", str(limit)])

    _remove_flag_value(command, "--remux-video")
    _remove_flag_value(command, "--recode-video")
    post_process = str(getattr(job, "profile_post_process", "") or "").strip().lower()
    target = container or "mp4"
    if post_process == "remux":
        _insert_before_source(command, ["--remux-video", target])
    elif post_process == "convert":
        _insert_before_source(command, ["--recode-video", target])
    return command


def _profile_query_id(raw: str) -> str | None:
    query = parse_qs(urlparse(raw).query)
    value = str(query.get("profile", query.get("profile_id", [""]))[0] or "").strip()
    return value or None


def install_download_profile_policy(engine_module):
    """Resolve Download Profiles for every local download submission.

    A manual ``downloadProfileId`` / protocol ``profile`` selection has priority.
    Without one, URL Pattern matching is automatic. The resolved profile is
    materialized onto the immutable Job so queue/retry/history flows keep one
    deterministic configuration snapshot even if the profile is edited later.
    """
    if getattr(engine_module, "_galaxy_download_profile_policy_installed", False):
        return engine_module.Job

    base_job = engine_module.Job

    @dataclass(frozen=True)
    class ProfileJob(base_job):
        download_profile_id: str = ""
        download_profile_name: str = ""
        profile_container: str = ""
        profile_directory: str = ""
        profile_filename: str = ""
        profile_rate_limit_mib: float | None = None
        profile_post_process: str = ""

    ProfileJob.__name__ = "Job"
    ProfileJob.__qualname__ = "Job"
    engine_module.Job = ProfileJob

    original_parse_job = engine_module.parse_job
    original_job_from_payload = engine_module.job_from_payload
    original_job_to_payload = engine_module.job_to_payload

    def parse_job(raw: str):
        job = original_parse_job(raw)
        profile = _profile_for(engine_module, getattr(job, "source_url", ""), _profile_query_id(raw))
        return apply_profile_to_job(job, profile)

    def job_from_payload(payload: dict[str, Any]):
        job = original_job_from_payload(payload)
        manual = str(payload.get("downloadProfileId") or "").strip() or None
        profile = _profile_for(engine_module, getattr(job, "source_url", ""), manual)
        return apply_profile_to_job(job, profile)

    def job_to_payload(job) -> dict[str, Any]:
        payload = original_job_to_payload(job)
        payload.update(
            downloadProfileId=str(getattr(job, "download_profile_id", "") or ""),
            downloadProfileName=str(getattr(job, "download_profile_name", "") or ""),
        )
        return payload

    engine_module.parse_job = parse_job
    engine_module.job_from_payload = job_from_payload
    engine_module.job_to_payload = job_to_payload

    original_build_options = engine_module.EngineWindow.build_options

    def build_options(window) -> dict[str, Any]:
        options = original_build_options(window)
        job = getattr(window, "job", None)
        if job is None or not getattr(job, "download_profile_id", ""):
            return options
        container = str(getattr(job, "profile_container", "") or "").strip().lower()
        if container:
            options["merge_output_format"] = container
        output = profile_output_template(engine_module, job, options.get("outtmpl", ""))
        if output:
            options["outtmpl"] = output
        limit = _rate_limit_bytes(job)
        if limit is not None:
            options["ratelimit"] = limit
        post_process = str(getattr(job, "profile_post_process", "") or "").strip().lower()
        target = container or "mp4"
        if post_process in {"remux", "convert"}:
            processors = list(options.get("postprocessors") or [])
            processors.append(
                {
                    "key": "FFmpegVideoRemuxer" if post_process == "remux" else "FFmpegVideoConvertor",
                    "preferedformat": target,
                }
            )
            options["postprocessors"] = processors
        return options

    engine_module.EngineWindow.build_options = build_options

    original_external_builder = external_ytdlp.build_external_command

    def build_external_command(*args, **kwargs):
        command = original_external_builder(*args, **kwargs)
        return apply_profile_to_external_command(engine_module, getattr(_PROFILE_CONTEXT, "job", None), command)

    external_ytdlp.build_external_command = build_external_command

    original_run_external_job = engine_module.EngineWindow._run_external_job

    def run_external_job(window, executable):
        _PROFILE_CONTEXT.job = getattr(window, "job", None)
        try:
            return original_run_external_job(window, executable)
        finally:
            _PROFILE_CONTEXT.job = None

    engine_module.EngineWindow._run_external_job = run_external_job

    original_bridge_status = engine_module.EngineWindow.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        payload["downloadProfiles"] = True
        payload["downloadProfileAutoMatch"] = True
        payload["downloadProfileManualOverride"] = True
        return payload

    engine_module.EngineWindow.bridge_status = bridge_status
    engine_module.resolve_download_profile = lambda url, manual_profile_id=None: _profile_for(
        engine_module, url, manual_profile_id
    )
    engine_module._galaxy_download_profile_policy_installed = True
    return ProfileJob


def run_download_profile_policy_self_test() -> None:
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class FakeJob:
        source_url: str
        video_quality: str = "best"
        audio_quality: str = "best"
        include_audio: bool = True
        include_subtitle: bool = False
        subtitle_lang: str | None = None
        browser: str = "none"
        skip_previously_downloaded: bool = False
        split_chapters: bool = False
        subtitle_languages: tuple[str, ...] = ()
        sponsorblock_categories: tuple[str, ...] = ()
        download_profile_id: str = ""
        download_profile_name: str = ""
        profile_container: str = ""
        profile_directory: str = ""
        profile_filename: str = ""
        profile_rate_limit_mib: float | None = None
        profile_post_process: str = ""

    profile = {
        "id": "a" * 32,
        "name": "YouTube 4K",
        "settings": {
            "video": "2160p",
            "audio": "best",
            "container": "mkv",
            "subtitle": "en,zh-Hans",
            "archive": True,
            "browser": "chrome",
            "directory": "Video/YouTube",
            "filename": "%(title)s [%(id)s]",
            "rateLimitMiB": 12.5,
            "chapters": True,
            "sponsorBlock": True,
            "postProcess": "remux",
        },
    }
    job = apply_profile_to_job(FakeJob("https://youtube.com/watch?v=demo"), profile)
    assert job.video_quality == "2160p"
    assert job.browser == "chrome"
    assert job.skip_previously_downloaded is True
    assert job.split_chapters is True
    assert job.subtitle_languages == ("en", "zh-Hans")
    assert job.sponsorblock_categories == ("sponsor",)
    assert job.download_profile_id == "a" * 32
    assert job.profile_container == "mkv"
    assert job.profile_rate_limit_mib == 12.5
    assert _safe_filename_template("%(title)s") == "%(title)s.%(ext)s"
    assert _rate_limit_bytes(job) == 13107200
