from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from download_profiles import DownloadProfileError, resolve_profile

PROFILE_EXPLICIT_FIELDS = frozenset({"video", "audio", "browser", "subtitle", "archive", "chapters"})
PROFILE_APPLIED_JOB_FIELDS = ("video", "audio", "browser", "subtitle", "archive", "chapters")
PROFILE_DEFERRED_FIELDS = (
    "container",
    "directory",
    "filename",
    "rateLimitMiB",
    "sponsorBlock",
    "postProcess",
    "script",
)


def _clean_explicit_fields(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("profileExplicitFields must be a list")
    result: list[str] = []
    for raw in value:
        field = str(raw or "").strip()
        if field not in PROFILE_EXPLICIT_FIELDS:
            raise ValueError(f"unsupported profile explicit field: {field or '<empty>'}")
        if field not in result:
            result.append(field)
        if len(result) > len(PROFILE_EXPLICIT_FIELDS):
            raise ValueError("too many profile explicit fields")
    return tuple(result)


def _protocol_explicit_fields(raw: str) -> tuple[str, ...]:
    query = parse_qs(urlparse(raw).query, keep_blank_values=True)
    result: list[str] = []
    for field, keys in (
        ("video", ("video", "video_format_id")),
        ("audio", ("audio", "audio_format_id")),
        ("browser", ("browser",)),
        ("subtitle", ("subtitle", "subtitle_lang", "subtitle_mode", "subtitle_langs")),
        ("archive", ("archive",)),
        ("chapters", ("split_chapters",)),
    ):
        if any(key in query for key in keys):
            result.append(field)
    return tuple(result)


def _legacy_payload_explicit_fields(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Infer explicit overrides for pre-profile clients without breaking defaults.

    Older website/desktop builds commonly send their whole form state. Treating
    mere key presence as explicit would make automatic Profiles inert because
    values such as ``best``/``none``/``false`` are always present. Non-default
    values remain explicit; new clients can use ``profileExplicitFields`` when a
    user deliberately chooses a default-looking value such as Video=best.
    """
    result: list[str] = []
    video = str(payload.get("videoQuality") or "best").strip() or "best"
    audio = str(payload.get("audioQuality") or "best").strip() or "best"
    browser = str(payload.get("browser") or "none").strip().lower() or "none"
    subtitle_language = str(payload.get("subtitleLanguage") or "").strip()
    if video != "best" or payload.get("videoFormatId"):
        result.append("video")
    if audio != "best" or payload.get("audioFormatId"):
        result.append("audio")
    if browser != "none":
        result.append("browser")
    if bool(payload.get("includeSubtitle", False)) or subtitle_language:
        result.append("subtitle")
    if bool(payload.get("skipPreviouslyDownloaded", False)):
        result.append("archive")
    if bool(payload.get("splitChapters", False)):
        result.append("chapters")
    return tuple(result)


def payload_explicit_fields(payload: Mapping[str, Any]) -> tuple[str, ...]:
    if "profileExplicitFields" in payload:
        return _clean_explicit_fields(payload.get("profileExplicitFields"))
    return _legacy_payload_explicit_fields(payload)


def _profile_snapshot(profile: Mapping[str, Any] | None) -> str:
    if profile is None:
        return ""
    settings = profile.get("settings")
    if not isinstance(settings, Mapping):
        return ""
    return json.dumps(dict(settings), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def profile_settings(job: object) -> dict[str, Any]:
    raw = str(getattr(job, "profile_settings_json", "") or "")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve(engine_module, source_url: str, manual_profile_id: object | None):
    manual = manual_profile_id not in {None, ""}
    try:
        profile = resolve_profile(
            engine_module,
            source_url,
            manual_profile_id=manual_profile_id if manual else None,
        )
    except DownloadProfileError as exc:
        raise ValueError(str(exc)) from exc
    return profile, "manual" if manual and profile is not None else "auto" if profile is not None else "none"


def _apply_job_defaults(job, profile: Mapping[str, Any] | None, explicit_fields: tuple[str, ...], mode: str):
    explicit = set(explicit_fields)
    settings = dict(profile.get("settings") or {}) if profile is not None else {}
    updates: dict[str, Any] = {
        "profile_id": str(profile.get("id") or "") if profile is not None else "",
        "profile_name": str(profile.get("name") or "") if profile is not None else "",
        "profile_mode": mode,
        "profile_explicit_fields": explicit_fields,
        "profile_settings_json": _profile_snapshot(profile),
    }
    if profile is not None:
        if "video" not in explicit:
            updates["video_quality"] = str(settings.get("video") or "best")
        if "audio" not in explicit:
            updates["audio_quality"] = str(settings.get("audio") or "best")
        if "browser" not in explicit:
            updates["browser"] = str(settings.get("browser") or "none")
        if "subtitle" not in explicit:
            subtitle = str(settings.get("subtitle") or "").strip()
            updates["include_subtitle"] = bool(subtitle)
            updates["subtitle_lang"] = subtitle or None
        if "archive" not in explicit and hasattr(job, "skip_previously_downloaded"):
            updates["skip_previously_downloaded"] = bool(settings.get("archive", False))
        if "chapters" not in explicit and hasattr(job, "split_chapters"):
            updates["split_chapters"] = bool(settings.get("chapters", False))
    return replace(job, **updates)


def install_download_profile_policy(engine_module):
    """Resolve Profiles and apply only safe job-level defaults.

    Precedence for fields covered here is:

        explicit request > manual Profile > automatic URL Profile > legacy/global defaults

    Output/container/rate/SponsorBlock/post-process/script settings are carried in
    the immutable Profile snapshot for follow-up policies, but are deliberately
    not executed or applied by this contract.
    """
    if getattr(engine_module, "_galaxy_download_profile_policy_installed", False):
        return engine_module.Job

    base_job = engine_module.Job

    @dataclass(frozen=True)
    class ProfileJob(base_job):
        profile_id: str = ""
        profile_name: str = ""
        profile_mode: str = "none"
        profile_explicit_fields: tuple[str, ...] = ()
        profile_settings_json: str = ""

    ProfileJob.__name__ = "Job"
    ProfileJob.__qualname__ = "Job"
    engine_module.Job = ProfileJob

    original_parse_job = engine_module.parse_job
    original_job_from_payload = engine_module.job_from_payload
    original_job_to_payload = engine_module.job_to_payload

    def parse_job(raw: str):
        job = original_parse_job(raw)
        query = parse_qs(urlparse(raw).query, keep_blank_values=True)
        manual_profile_id = query.get("profile_id", [""])[0].strip() or None
        explicit = _protocol_explicit_fields(raw)
        profile, mode = _resolve(engine_module, job.source_url, manual_profile_id)
        return _apply_job_defaults(job, profile, explicit, mode)

    def job_from_payload(payload: dict[str, Any]):
        job = original_job_from_payload(payload)
        manual_profile_id = str(payload.get("profileId") or "").strip() or None
        explicit = payload_explicit_fields(payload)
        profile, mode = _resolve(engine_module, job.source_url, manual_profile_id)
        return _apply_job_defaults(job, profile, explicit, mode)

    def job_to_payload(job) -> dict[str, Any]:
        payload = original_job_to_payload(job)
        mode = str(getattr(job, "profile_mode", "none") or "none")
        profile_id = str(getattr(job, "profile_id", "") or "")
        payload.update(
            profileId=profile_id if mode == "manual" else "",
            resolvedProfileId=profile_id,
            resolvedProfileName=str(getattr(job, "profile_name", "") or ""),
            profileMode=mode,
            profileExplicitFields=list(getattr(job, "profile_explicit_fields", ()) or ()),
        )
        return payload

    engine_module.parse_job = parse_job
    engine_module.job_from_payload = job_from_payload
    engine_module.job_to_payload = job_to_payload

    original_bridge_status = engine_module.EngineWindow.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        payload["downloadProfilePolicy"] = {
            "autoApply": True,
            "manualOverride": True,
            "explicitFields": sorted(PROFILE_EXPLICIT_FIELDS),
            "appliedJobFields": list(PROFILE_APPLIED_JOB_FIELDS),
            "deferredFields": list(PROFILE_DEFERRED_FIELDS),
            "precedence": ["explicit", "manual-profile", "auto-profile", "global-default"],
        }
        return payload

    engine_module.EngineWindow.bridge_status = bridge_status
    engine_module._galaxy_download_profile_policy_installed = True
    engine_module.EngineWindow._galaxy_download_profile_policy_installed = True
    return ProfileJob


def run_download_profile_policy_self_test() -> None:
    assert _clean_explicit_fields(["video", "video", "browser"]) == ("video", "browser")
    assert _protocol_explicit_fields(
        "galaxy-downloader://download?url=https%3A%2F%2Fexample.com&video=best&archive=0"
    ) == ("video", "archive")
    assert payload_explicit_fields(
        {"videoQuality": "best", "audioQuality": "best", "browser": "none", "includeSubtitle": False}
    ) == ()
    assert payload_explicit_fields({"videoQuality": "1080p", "browser": "chrome"}) == ("video", "browser")
    assert payload_explicit_fields(
        {"videoQuality": "best", "profileExplicitFields": ["video"]}
    ) == ("video",)
