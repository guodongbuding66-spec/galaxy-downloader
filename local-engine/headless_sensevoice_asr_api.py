from __future__ import annotations

import re
from typing import Any, Mapping

from asr_preferences import load_asr_preferences, save_asr_preferences
from asr_provider_router import (
    AUTO,
    SENSEVOICE,
    list_routable_asr_providers,
    recommend_asr_route,
    transcribe_with_provider,
)
from headless_asr_api import (
    HeadlessAsrApi,
    HeadlessAsrApiError,
    _bounded_int,
    _clean_media_id,
    _clean_profile,
    _public_hardware,
    _public_operation,
)
from sensevoice_provider import (
    LANGUAGES as SENSEVOICE_LANGUAGES,
    MODELS as SENSEVOICE_MODELS,
    install_model as install_sensevoice_model,
    provider_status as sensevoice_status,
    remove_model as remove_sensevoice_model,
)

_DEVICE_RE = re.compile(r"^(?:|auto|cpu|mps|cuda(?::[0-9]{1,2})?)$")


def _sensevoice_provider(value: object, *, allow_auto: bool = False) -> str:
    provider = str(value or "").strip().lower()
    allowed = {SENSEVOICE}
    if allow_auto:
        allowed.add(AUTO)
    if provider not in allowed:
        raise HeadlessAsrApiError("invalid ASR provider", code="ASR_PROVIDER_INVALID")
    return provider


def _sensevoice_model(value: object, *, allow_empty: bool = False) -> str:
    model = str(value or "").strip().lower()
    if not model and allow_empty:
        return ""
    if model not in set(SENSEVOICE_MODELS):
        raise HeadlessAsrApiError("invalid ASR model", code="ASR_MODEL_INVALID")
    return model


def _sensevoice_language(value: object) -> str:
    language = str(value or "").strip().lower()
    if language and language not in set(SENSEVOICE_LANGUAGES):
        raise HeadlessAsrApiError("invalid SenseVoice language", code="ASR_LANGUAGE_INVALID")
    return language


def _sensevoice_device(value: object) -> str:
    device = str(value or "").strip().lower()
    if not _DEVICE_RE.fullmatch(device):
        raise HeadlessAsrApiError("invalid SenseVoice device", code="ASR_DEVICE_INVALID")
    return device


def _sensevoice_compute_type(value: object) -> str:
    compute = str(value or "").strip().lower()
    if compute in {"", "default"}:
        return ""
    raise HeadlessAsrApiError(
        "SenseVoice does not support compute type",
        code="ASR_COMPUTE_TYPE_INVALID",
    )


def _sensevoice_model_rows(status) -> list[dict[str, Any]]:
    installed = set(status.installed_models)
    return [
        {
            "provider": SENSEVOICE,
            "model": model,
            "installed": model in installed,
            "managed": model in installed,
            "languages": list(SENSEVOICE_LANGUAGES),
            "cpu": True,
            "gpu": True,
        }
        for model in SENSEVOICE_MODELS
    ]


class SenseVoiceHeadlessAsrApi(HeadlessAsrApi):
    """Headless ASR extension that adds SenseVoice without changing legacy flows."""

    def providers(self) -> dict[str, Any]:
        try:
            rows = list_routable_asr_providers(self.context)
        except Exception as exc:
            raise self._error(exc) from exc
        return {"providers": rows, "count": len(rows)}

    def recommend(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        raw = payload if isinstance(payload, Mapping) else {}
        provider = str(raw.get("provider", AUTO) or AUTO).strip().lower()
        if provider != SENSEVOICE:
            return super().recommend(raw)
        try:
            recommendation = recommend_asr_route(
                self.context,
                _public_hardware(raw.get("hardware")),
                profile=_clean_profile(raw.get("profile", "balanced")),
                preferred_provider=_sensevoice_provider(provider),
            )
        except Exception as exc:
            raise self._error(exc) from exc
        return {"recommendation": recommendation.public_payload()}

    def save_preferences(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider", AUTO) or AUTO).strip().lower()
        if provider != SENSEVOICE:
            return super().save_preferences(payload)
        try:
            settings = save_asr_preferences(
                self.context,
                provider=_sensevoice_provider(provider),
                profile=_clean_profile(payload.get("profile", "balanced")),
                model=_sensevoice_model(payload.get("model", ""), allow_empty=True),
                language=_sensevoice_language(payload.get("language", "")),
                device=_sensevoice_device(payload.get("device", "")),
                compute_type=_sensevoice_compute_type(payload.get("computeType", "")),
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
        if requested and requested != SENSEVOICE:
            return super().models(requested)
        try:
            sense_rows = _sensevoice_model_rows(sensevoice_status(self.context))
        except Exception as exc:
            raise self._error(exc) from exc
        if requested == SENSEVOICE:
            return {"models": sense_rows, "count": len(sense_rows)}
        legacy = super().models("")
        rows = [*legacy.get("models", []), *sense_rows]
        return {"models": rows, "count": len(rows)}

    def install_model(
        self,
        provider_id: object,
        model_id: object,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider = str(provider_id or "").strip().lower()
        if provider != SENSEVOICE:
            return super().install_model(provider_id, model_id, payload)
        model = _sensevoice_model(model_id)
        raw = payload if isinstance(payload, Mapping) else {}
        timeout = _bounded_int(raw.get("timeoutSeconds"), 7200, 60, 14400)
        try:
            success, detail = install_sensevoice_model(
                self.context,
                model,
                timeout_seconds=timeout,
            )
            rendered = _public_operation(
                success=success,
                provider=SENSEVOICE,
                model=model,
                detail=detail,
                roots=self._roots,
            )
        except Exception as exc:
            raise self._error(exc) from exc
        return {"operation": rendered}

    def remove_model(self, provider_id: object, model_id: object) -> dict[str, Any]:
        provider = str(provider_id or "").strip().lower()
        if provider != SENSEVOICE:
            return super().remove_model(provider_id, model_id)
        model = _sensevoice_model(model_id)
        try:
            success, detail = remove_sensevoice_model(self.context, model)
            rendered = _public_operation(
                success=success,
                provider=SENSEVOICE,
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
        if provider != SENSEVOICE:
            return super().transcribe(payload)

        same_provider = stored.provider == SENSEVOICE
        stored_model = stored.model if same_provider else ""
        stored_language = stored.language if same_provider else ""
        stored_device = stored.device if same_provider else ""
        stored_compute_type = stored.compute_type if same_provider else ""
        hardware = _public_hardware(payload.get("hardware"))
        try:
            profile = _clean_profile(payload.get("profile", stored.profile))
            model = _sensevoice_model(payload.get("model", stored_model), allow_empty=True)
            language = _sensevoice_language(payload.get("language", stored_language))
            device = _sensevoice_device(payload.get("device", stored_device))
            _sensevoice_compute_type(payload.get("computeType", stored_compute_type))
            timeout = _bounded_int(payload.get("timeoutSeconds"), 7200, 60, 14400)
            recommendation = recommend_asr_route(
                self.context,
                hardware,
                profile=profile,
                preferred_provider=SENSEVOICE,
            )
            effective_model = model or recommendation.model
            artifact = transcribe_with_provider(
                self.context,
                media_id,
                provider=SENSEVOICE,
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
                "provider": SENSEVOICE,
                "model": effective_model,
                "ready": True,
            }
        }
