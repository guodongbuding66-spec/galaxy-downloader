from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import parse_qs, urlparse

from media_format_catalog import MediaFormatError, exact_format_selector, validate_format_id


def _optional_format_id(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return validate_format_id(text)
    except MediaFormatError as exc:
        raise ValueError(str(exc)) from exc


def install_exact_format_policy(engine_module):
    """Add explicit yt-dlp format identities to Galaxy jobs.

    This policy is intentionally installed *after* the generic media policy. An
    explicit format id is a stronger user choice than height/bitrate/language
    preferences; jobs without exact ids still fall through to the existing
    selector unchanged.
    """
    if getattr(engine_module, "_galaxy_exact_format_policy_installed", False):
        return engine_module.Job

    base_job = engine_module.Job

    @dataclass(frozen=True)
    class ExactFormatJob(base_job):
        video_format_id: str | None = None
        audio_format_id: str | None = None
        selected_video_has_audio: bool = False

    ExactFormatJob.__name__ = "Job"
    ExactFormatJob.__qualname__ = "Job"
    engine_module.Job = ExactFormatJob

    original_parse_job = engine_module.parse_job
    original_job_from_payload = engine_module.job_from_payload
    original_job_to_payload = engine_module.job_to_payload
    original_format_selector = engine_module.format_selector

    def parse_job(raw: str):
        job = original_parse_job(raw)
        query = parse_qs(urlparse(raw).query)
        video_format_id = _optional_format_id(query.get("video_format_id", [""])[0])
        audio_format_id = _optional_format_id(query.get("audio_format_id", [""])[0])
        selected_video_has_audio = engine_module._bool(query.get("video_muxed", ["0"])[0])
        return replace(
            job,
            video_format_id=video_format_id,
            audio_format_id=audio_format_id,
            selected_video_has_audio=selected_video_has_audio,
        )

    def job_from_payload(payload: dict[str, Any]):
        job = original_job_from_payload(payload)
        return replace(
            job,
            video_format_id=_optional_format_id(payload.get("videoFormatId")),
            audio_format_id=_optional_format_id(payload.get("audioFormatId")),
            selected_video_has_audio=bool(payload.get("selectedVideoHasAudio", False)),
        )

    def job_to_payload(job) -> dict[str, Any]:
        payload = original_job_to_payload(job)
        payload.update(
            videoFormatId=getattr(job, "video_format_id", None),
            audioFormatId=getattr(job, "audio_format_id", None),
            selectedVideoHasAudio=bool(getattr(job, "selected_video_has_audio", False)),
        )
        return payload

    def format_selector(job) -> str:
        video_format_id = getattr(job, "video_format_id", None)
        audio_format_id = getattr(job, "audio_format_id", None)
        if video_format_id is None and audio_format_id is None:
            return original_format_selector(job)
        try:
            return exact_format_selector(
                video_format_id=video_format_id,
                audio_format_id=audio_format_id,
                include_audio=bool(getattr(job, "include_audio", True)),
                selected_video_has_audio=bool(getattr(job, "selected_video_has_audio", False)),
            )
        except MediaFormatError as exc:
            raise ValueError(str(exc)) from exc

    original_bridge_status = engine_module.EngineWindow.bridge_status

    def bridge_status(window) -> dict[str, Any]:
        payload = original_bridge_status(window)
        payload["exactFormatSelection"] = True
        return payload

    engine_module.parse_job = parse_job
    engine_module.job_from_payload = job_from_payload
    engine_module.job_to_payload = job_to_payload
    engine_module.format_selector = format_selector
    engine_module.EngineWindow.bridge_status = bridge_status
    engine_module._galaxy_exact_format_policy_installed = True
    return ExactFormatJob


def run_exact_format_policy_self_test() -> None:
    assert _optional_format_id("137") == "137"
    assert _optional_format_id("audio-251") == "audio-251"
    assert _optional_format_id("") is None
    try:
        _optional_format_id("137+bestaudio")
    except ValueError:
        pass
    else:
        raise AssertionError("selector syntax was accepted as a format id")
