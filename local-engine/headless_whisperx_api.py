from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from headless_asr_api import HeadlessAsrApiError, HeadlessAsrContext, build_headless_asr_context
from whisperx_provider import (
    WhisperXError,
    diarize_media,
    prepare_diarization,
    provider_status,
    remove_diarization_models,
)


class HeadlessWhisperXApi:
    """Path-safe Headless boundary for optional WhisperX diarization."""

    def __init__(
        self,
        download_root: Path,
        *,
        context: HeadlessAsrContext | None = None,
        program_dir: Path | None = None,
        data_dir: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.context = context or build_headless_asr_context(
            download_root,
            program_dir=program_dir,
            data_dir=data_dir,
            state_dir=state_dir,
        )

    @staticmethod
    def _bounded_int(value: object, default: int, low: int, high: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(low, min(parsed, high))

    @staticmethod
    def _translate(exc: Exception) -> HeadlessAsrApiError:
        text = " ".join(str(exc or "").split()).strip()[:1200] or "WhisperX operation failed"
        code = "ASR_WHISPERX_FAILED"
        status = 400
        if "未安装" in text or "尚未显式准备" in text:
            status = 409
            code = "ASR_WHISPERX_UNAVAILABLE"
        elif "媒体文件不可用" in text:
            status = 404
            code = "ASR_MEDIA_NOT_FOUND"
        error = HeadlessAsrApiError(text, code=code)
        error.status = status
        return error

    def status(self) -> dict[str, Any]:
        try:
            return {"whisperx": provider_status(self.context).public_payload()}
        except Exception as exc:
            raise self._translate(exc) from exc

    def prepare(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        raw = payload if isinstance(payload, Mapping) else {}
        try:
            success, detail = prepare_diarization(
                self.context,
                model=raw.get("model"),
                timeout_seconds=self._bounded_int(raw.get("timeoutSeconds"), 3600, 60, 7200),
            )
            return {"operation": {"success": success, "detail": str(detail)[:1200]}, **self.status()}
        except Exception as exc:
            raise self._translate(exc) from exc

    def remove(self) -> dict[str, Any]:
        try:
            success, detail = remove_diarization_models(self.context)
            return {"operation": {"success": success, "detail": str(detail)[:1200]}, **self.status()}
        except Exception as exc:
            raise self._translate(exc) from exc

    def diarize(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            result = diarize_media(
                self.context,
                payload.get("mediaId"),
                min_speakers=payload.get("minSpeakers"),
                max_speakers=payload.get("maxSpeakers"),
                device=payload.get("device", "cpu"),
                minimum_overlap_seconds=payload.get("minimumOverlapSeconds", 0.05),
                clear_unmatched=bool(payload.get("clearUnmatched", False)),
                timeout_seconds=self._bounded_int(payload.get("timeoutSeconds"), 7200, 60, 14400),
            )
            return {"diarization": result.public_payload()}
        except Exception as exc:
            raise self._translate(exc) from exc
