from __future__ import annotations

import re
from typing import Any, Mapping

from asr_preferences import load_asr_preferences, save_asr_preferences
from asr_provider_router import (
    PARAKEET,
    recommend_asr_route,
    transcribe_with_provider,
)
from headless_asr_api import (
    HeadlessAsrApiError,
    _bounded_int,
    _clean_media_id,
    _clean_profile,
    _public_hardware,
    _public_operation,
)
from headless_sensevoice_asr_api import SenseVoiceHeadlessAsrApi
from parakeet_provider import (
    LANGUAGES as PARAKEET_LANGUAGES,
    MODELS as PARAKEET_MODELS,
    SUPPORTED_LANGUAGES as PARAKEET_SUPPORTED_LANGUAGES,
    install_model as install_parakeet_model,
    provider_status as parakeet_status,
    remove_model as remove_parakeet_model,
)

_DEVICE_RE = re.compile(r"^(?:|auto|cpu|cuda(?::[0-9]{1,2})?)$")


def _parakeet_provider(value: object) -> str:
    provider = str(value or "").strip().lower()
    if provider != PARAKEET:
        raise HeadlessAsrApiError("invalid ASR provider", code="ASR_PROVIDER_INVALID")
    return provider


def _parakeet_model(value: object, *, allow_empty: bool = False) -> str:
    model = str(value or "").strip().lower()
    if not model and allow_empty:
        return ""
    if model not in set(PARAKEET_MODELS):
        raise HeadlessAsrApiError("invalid ASR model", code="ASR_MODEL_INVALID")
    return model


def _parakeet_language(value: object) -> str:
    language = str(value or "").strip().lower() or "auto"
    if language not in set(PARAKEET_LANGUAGES):
        raise HeadlessAsrApiError(
            "Parakeet only supports automatic language detection",
            code="ASR_LANGUAGE_INVALID",
        )
    return language


def _parakeet_device(value: object) -> str:
    device = str(value or "").strip().lower()
    if not _DEVICE_RE.fullmatch(device):
        raise HeadlessAsrApiError("invalid Parakeet device", code="ASR_DEVICE_INVALID")
    return device


def _parakeet_compute_type(value: object) -> str:
    compute = str(value or "").strip().lower()
    if compute in {"", "default"}:
        return ""
    raise HeadlessAsrApiError(
        "Parakeet does not support compute type",
        code="ASR_COMPUTE_TYPE_INVALID",
    )


def _parakeet_model_rows(status) -> list[dict[str, Any]]:
    installed = set(status.installed_models)
    return [
        {
            "provider": PARAKEET,
            "model": model,
            "installed": model in installed,
            "managed": model in installed,
            "languages": list(PARAKEET_LANGUAGES),
            "supportedLanguages": list(PARAKEET_SUPPORTED_LANGUAGES),
            "automaticLanguageDetection": True,
            "cpu": True,
            "gpu": True,
            "mps": False,
        }
        for model in PARAKEET_MODELS
    ]


class ParakeetHeadlessAsrApi(SenseVoiceHeadlessAsrApi):
    """Headless ASR extension that adds Parakeet on top of SenseVoice support."""

    def recommend(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        raw = payload if isinstance(payload, Mapping) else {}
        provider = str(raw.get("provider", "auto") or "auto").strip().lower()
        if provider != PARAKEET:
            return super().recommend(raw)
        try:
            recommendation = recommend_asr_route(
                self.context,
                _public_hardware(raw.get("hardware")),
                profile=_clean_profile(raw.get("profile", "balanced")),
                preferred_provider=_parakeet_provider(provider),
            )
        except Exception as exc:
            raise self._error(exc) from exc
        return {"recommendation": recommendation.public_payload()}

    def save_preferences(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider", "auto") or "auto").strip().lower()
        if provider != PARAKEET:
            return super().save_preferences(payload)
        try:
            settings = save_asr_preferences(
                self.context,
                provider=_parakeet_provider(provider),
                profile=_clean_profile(payload.get("profile", "balanced")),
                model=_parakeet_model(payload.get("model", ""), allow_empty=True),
                language=_parakeet_language(payload.get("language", "")),
                device=_parakeet_device(payload.get("device", "")),
                compute_type=_parakeet_compute_type(payload.get("computeType", "")),
            )
            recommendation = recommend_asr_route(
                self.context,
                _public_hardware(payload.get("hardware")),
                profile=settings.profile,
                preferred_provider=settings.provider,
            )
        except Exception as exc:
            raise self._error(exc) from exc
        return {
            "settings": settings.public_payload(),
            "recommendation": recommendation.public_payload(),
            "modelDownloadAutomatic": False,
        }

    def models(self, provider_id: object = "") -> dict[str, Any]:
        requested = str(provider_id or "").strip().lower()
        if requested and requested != PARAKEET:
            return super().models(requested)
        try:
            rows = _parakeet_model_rows(parakeet_status(self.context))
        except Exception as exc:
            raise self._error(exc) from exc
        if requested == PARAKEET:
            return {"models": rows, "count": len(rows)}
        inherited = super().models("")
        combined = [*inherited.get("models", []), *rows]
        return {"models": combined, "count": len(combined)}

    def install_model(
        self,
        provider_id: object,
        model_id: object,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider = str(provider_id or "").strip().lower()
        if provider != PARAKEET:
            return super().install_model(provider_id, model_id, payload)
        model = _parakeet_model(model_id)
        raw = payload if isinstance(payload, Mapping) else {}
        timeout = _bounded_int(raw.get("timeoutSeconds"), 14400, 60, 21600)
        try:
            success, detail = install_parakeet_model(
                self.context,
                model,
                timeout_seconds=timeout,
            )
            rendered = _public_operation(
                success=success,
                provider=PARAKEET,
                model=model,
                detail=detail,
                roots=self._roots,
            )
        except Exception as exc:
            raise self._error(exc) from exc
        return {"operation": rendered}

    def remove_model(self, provider_id: object, model_id: object) -> dict[str, Any]:
        provider = str(provider_id or "").strip().lower()
        if provider != PARAKEET:
            return super().remove_model(provider_id, model_id)
        model = _parakeet_model(model_id)
        try:
            success, detail = remove_parakeet_model(self.context, model)
            rendered = _public_operation(
                success=success,
                provider=PARAKEET,
                model=model,
                detail=detail,
                roots=self._roots,
            )
        except Exception as exc:
            raise self._error(exc) from exc
        return {"operation": rendered}

    def transcribe(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        media_id = _clean_media_id(payload.get("mediaId"))
        try:
            stored = load_asr_preferences(self.context)
        except Exception as exc:
            raise self._error(exc) from exc
        provider = str(payload.get("provider", stored.provider) or stored.provider).strip().lower()
        if provider != PARAKEET:
            return super().transcribe(payload)

        same_provider = stored.provider == PARAKEET
        stored_model = stored.model if same_provider else ""
        stored_language = stored.language if same_provider else ""
        stored_device = stored.device if same_provider else ""
        stored_compute_type = stored.compute_type if same_provider else ""
        hardware = _public_hardware(payload.get("hardware"))
        try:
            profile = _clean_profile(payload.get("profile", stored.profile))
            model = _parakeet_model(payload.get("model", stored_model), allow_empty=True)
            language = _parakeet_language(payload.get("language", stored_language))
            device = _parakeet_device(payload.get("device", stored_device))
            _parakeet_compute_type(payload.get("computeType", stored_compute_type))
            timeout = _bounded_int(payload.get("timeoutSeconds"), 10800, 60, 21600)
            recommendation = recommend_asr_route(
                self.context,
                hardware,
                profile=profile,
                preferred_provider=PARAKEET,
            )
            effective_model = model or recommendation.model
            artifact = transcribe_with_provider(
                self.context,
                media_id,
                provider=PARAKEET,
                model=model,
                language=language,
                hardware=hardware,
                profile=profile,
                device=device,
                compute_type="",
                timeout_seconds=timeout,
            )
        except Exception as exc:
            raise self._error(exc) from exc

        return {
            "transcript": {
                "kind": str(artifact.kind or "transcript"),
                "mediaId": str(artifact.media_id or media_id),
                "provider": PARAKEET,
                "model": effective_model,
                "ready": True,
            }
        }
