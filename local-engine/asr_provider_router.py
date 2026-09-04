from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_models import WHISPER_MODELS, whisper_executable
from ai_workspace import AiArtifactResult, transcribe_media as transcribe_whisper
from asr_model_manager import AsrModelError, list_whisper_models, recommend_whisper_model
from faster_whisper_provider import (
    FasterWhisperError,
    provider_status as faster_provider_status,
    recommend as recommend_faster,
    transcribe as transcribe_faster,
)
from sensevoice_provider import (
    LANGUAGES as SENSEVOICE_LANGUAGES,
    MODELS as SENSEVOICE_MODELS,
    SenseVoiceError,
    provider_status as sensevoice_provider_status,
    recommend as recommend_sensevoice,
    transcribe as transcribe_sensevoice,
)

WHISPER = "whisper"
FASTER_WHISPER = "faster-whisper"
SENSEVOICE = "sensevoice"
AUTO = "auto"
# Compatibility boundary: Headless/model-management consumers currently import
# ASR_PROVIDERS and only implement Whisper/faster-whisper install/delete flows.
# Keep that public set stable until the dedicated SenseVoice Headless PR lands.
ASR_PROVIDERS = (WHISPER, FASTER_WHISPER)
ROUTABLE_ASR_PROVIDERS = (*ASR_PROVIDERS, SENSEVOICE)
PROFILES = ("fast", "balanced", "accurate")


class AsrProviderRouterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code or "ASR_ERROR")[:64]

    def public_payload(self) -> dict[str, str]:
        return {"code": self.code, "error": str(self)}


@dataclass(frozen=True)
class AsrRouteRecommendation:
    provider: str
    model: str
    profile: str
    runtime_available: bool
    model_installed: bool
    device: str = ""
    compute_type: str = ""

    def public_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "profile": self.profile,
            "runtimeAvailable": self.runtime_available,
            "modelInstalled": self.model_installed,
            "device": self.device or None,
            "computeType": self.compute_type or None,
        }


def _clean_profile(value: object) -> str:
    profile = str(value or "balanced").strip().lower()
    return profile if profile in PROFILES else "balanced"


def _clean_provider(value: object, *, allow_auto: bool = True) -> str:
    provider = str(value or AUTO).strip().lower()
    allowed = {AUTO, *ROUTABLE_ASR_PROVIDERS} if allow_auto else set(ROUTABLE_ASR_PROVIDERS)
    if provider not in allowed:
        raise AsrProviderRouterError("ASR_PROVIDER_INVALID", "ASR Provider 无效")
    return provider


def _models_for_provider(provider: str) -> tuple[str, ...]:
    if provider == SENSEVOICE:
        return tuple(SENSEVOICE_MODELS)
    return tuple(WHISPER_MODELS)


def _clean_model(value: object, *, provider: str | None = None) -> str:
    model = str(value or "").strip().lower()
    if not model:
        return ""
    if provider is None:
        allowed = {*WHISPER_MODELS, *SENSEVOICE_MODELS}
    else:
        allowed = set(_models_for_provider(provider))
    if model not in allowed:
        raise AsrProviderRouterError("ASR_MODEL_INVALID", "ASR 模型名称无效")
    return model


def _whisper_status(engine_module) -> dict[str, Any]:
    rows = list_whisper_models(engine_module)
    installed = [
        str(row.get("model") or "")
        for row in rows
        if isinstance(row, dict) and bool(row.get("installed"))
    ]
    return {
        "id": WHISPER,
        "name": "OpenAI Whisper",
        "runtimeAvailable": whisper_executable(engine_module) is not None,
        "installedModels": installed,
        "models": list(WHISPER_MODELS),
        "explicitInstallRequired": True,
        "localFilesOnly": True,
        "supportsCpu": True,
        "supportsGpu": True,
    }


def _faster_status(engine_module) -> dict[str, Any]:
    status = faster_provider_status(engine_module)
    return {
        "id": FASTER_WHISPER,
        "name": "faster-whisper",
        "runtimeAvailable": bool(status.available),
        "version": status.version,
        "installedModels": list(status.installed_models),
        "models": list(WHISPER_MODELS),
        "explicitInstallRequired": True,
        "localFilesOnly": True,
        "supportsCpu": True,
        "supportsGpu": True,
    }


def _sensevoice_status(engine_module) -> dict[str, Any]:
    status = sensevoice_provider_status(engine_module)
    return {
        "id": SENSEVOICE,
        "name": "SenseVoice",
        "runtimeAvailable": bool(status.available),
        "installerAvailable": bool(status.installer_available),
        "version": status.version,
        "installedModels": list(status.installed_models),
        "models": list(SENSEVOICE_MODELS),
        "languages": list(SENSEVOICE_LANGUAGES),
        "explicitInstallRequired": True,
        "localFilesOnly": True,
        "supportsCpu": True,
        "supportsGpu": True,
    }


def list_asr_providers(engine_module) -> list[dict[str, Any]]:
    """Return providers supported by current external management consumers."""
    return [_whisper_status(engine_module), _faster_status(engine_module)]


def list_routable_asr_providers(engine_module) -> list[dict[str, Any]]:
    """Return every provider the unified router can explicitly dispatch."""
    return [
        _whisper_status(engine_module),
        _faster_status(engine_module),
        _sensevoice_status(engine_module),
    ]


def _status_map(engine_module) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in list_routable_asr_providers(engine_module)}


def recommend_asr_route(
    engine_module,
    hardware: dict[str, Any] | None = None,
    *,
    profile: object = "balanced",
    preferred_provider: object = AUTO,
) -> AsrRouteRecommendation:
    mode = _clean_profile(profile)
    preferred = _clean_provider(preferred_provider)
    statuses = _status_map(engine_module)

    if preferred == AUTO:
        # Preserve the existing automatic policy for compatibility. SenseVoice
        # becomes an explicit selectable provider without silently changing old
        # users from their Whisper/faster-whisper route.
        selected = (
            FASTER_WHISPER
            if bool(statuses[FASTER_WHISPER]["runtimeAvailable"])
            else WHISPER
        )
    else:
        selected = preferred

    if selected == FASTER_WHISPER:
        route = recommend_faster(hardware, profile=mode)
        model = _clean_model(route.get("model"), provider=FASTER_WHISPER) or "base"
        device = str(route.get("device") or "cpu")
        compute_type = str(route.get("computeType") or "int8")
    elif selected == SENSEVOICE:
        route = recommend_sensevoice(hardware, profile=mode)
        model = _clean_model(route.get("model"), provider=SENSEVOICE) or "small"
        device = str(route.get("device") or "cpu")
        compute_type = ""
    else:
        model = _clean_model(
            recommend_whisper_model(hardware, profile=mode),
            provider=WHISPER,
        ) or "base"
        device = ""
        compute_type = ""

    status = statuses[selected]
    return AsrRouteRecommendation(
        provider=selected,
        model=model,
        profile=mode,
        runtime_available=bool(status["runtimeAvailable"]),
        model_installed=model in set(status["installedModels"]),
        device=device,
        compute_type=compute_type,
    )


def transcribe_with_provider(
    engine_module,
    media_id: object,
    *,
    provider: object = AUTO,
    model: object = "",
    language: object = "",
    hardware: dict[str, Any] | None = None,
    profile: object = "balanced",
    device: object = "",
    compute_type: object = "",
    timeout_seconds: int = 7200,
) -> AiArtifactResult:
    selected = _clean_provider(provider)
    recommendation = recommend_asr_route(
        engine_module,
        hardware,
        profile=profile,
        preferred_provider=selected,
    )
    if selected == AUTO:
        selected = recommendation.provider

    requested_model = _clean_model(model, provider=selected) or recommendation.model
    statuses = _status_map(engine_module)
    status = statuses[selected]
    if not bool(status["runtimeAvailable"]):
        raise AsrProviderRouterError(
            "ASR_PROVIDER_UNAVAILABLE",
            f"ASR Provider {selected} 当前不可用",
        )
    if requested_model not in set(status["installedModels"]):
        raise AsrProviderRouterError(
            "ASR_MODEL_NOT_INSTALLED",
            f"{selected} 模型 {requested_model} 尚未显式安装",
        )

    try:
        if selected == FASTER_WHISPER:
            selected_device = str(device or recommendation.device or "cpu").strip().lower()
            selected_compute = str(
                compute_type or recommendation.compute_type or "int8"
            ).strip().lower()
            return transcribe_faster(
                engine_module,
                media_id,
                model=requested_model,
                language=language,
                device=selected_device,
                compute_type=selected_compute,
                timeout_seconds=timeout_seconds,
            )
        if selected == SENSEVOICE:
            requested_device = str(device or "").strip().lower()
            selected_device = (
                recommendation.device
                if requested_device in {"", "auto"}
                else requested_device
            ) or "cpu"
            return transcribe_sensevoice(
                engine_module,
                media_id,
                model=requested_model,
                language=language or "auto",
                device=selected_device,
                timeout_seconds=timeout_seconds,
            )
        return transcribe_whisper(
            engine_module,
            media_id,
            model=requested_model,
            language=language,
            timeout_seconds=timeout_seconds,
        )
    except (AsrModelError, FasterWhisperError, SenseVoiceError) as exc:
        raise AsrProviderRouterError("ASR_TRANSCRIBE_FAILED", str(exc)[-1600:]) from exc
    except Exception as exc:
        # ai_workspace owns its own error type; keep the router independent from
        # that implementation detail while still presenting one stable boundary.
        raise AsrProviderRouterError("ASR_TRANSCRIBE_FAILED", str(exc)[-1600:]) from exc


def run_asr_provider_router_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    from faster_whisper_provider import FasterWhisperStatus
    from sensevoice_provider import SenseVoiceStatus

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def data_dir() -> Path:
                target = root / "data"
                target.mkdir(exist_ok=True)
                return target

        whisper_rows = [
            {"model": model, "installed": model in {"base", "small"}}
            for model in WHISPER_MODELS
        ]
        with patch(
            "asr_provider_router.whisper_executable",
            return_value=root / "whisper",
        ), patch(
            "asr_provider_router.list_whisper_models",
            return_value=whisper_rows,
        ), patch(
            "asr_provider_router.faster_provider_status",
            return_value=FasterWhisperStatus(True, "1.2.3", ("base", "small")),
        ), patch(
            "asr_provider_router.sensevoice_provider_status",
            return_value=SenseVoiceStatus(True, True, "1.3.29", ("small",)),
        ), patch(
            "asr_provider_router.recommend_faster",
            return_value={"model": "small", "device": "cpu", "computeType": "int8"},
        ), patch(
            "asr_provider_router.recommend_sensevoice",
            return_value={"model": "small", "device": "cpu", "profile": "balanced"},
        ), patch(
            "asr_provider_router.recommend_whisper_model",
            return_value="small",
        ):
            managed = list_asr_providers(Engine)
            assert [item["id"] for item in managed] == [WHISPER, FASTER_WHISPER]
            routable = list_routable_asr_providers(Engine)
            assert [item["id"] for item in routable] == [
                WHISPER,
                FASTER_WHISPER,
                SENSEVOICE,
            ]
            assert all(item["runtimeAvailable"] for item in routable)

            automatic = recommend_asr_route(Engine, {"ramGb": 16}, profile="balanced")
            assert automatic.provider == FASTER_WHISPER
            assert automatic.model == "small" and automatic.model_installed
            classic = recommend_asr_route(
                Engine,
                {"ramGb": 16},
                profile="balanced",
                preferred_provider=WHISPER,
            )
            assert classic.provider == WHISPER and classic.model == "small"
            sense = recommend_asr_route(
                Engine,
                {"ramGb": 16},
                profile="balanced",
                preferred_provider=SENSEVOICE,
            )
            assert sense.provider == SENSEVOICE
            assert sense.model == "small" and sense.model_installed
            assert sense.device == "cpu"

            artifact = AiArtifactResult(
                "transcript",
                "a" * 32,
                root / "out.srt",
                "faster-whisper:small",
            )
            with patch(
                "asr_provider_router.transcribe_faster",
                return_value=artifact,
            ) as faster_call:
                result = transcribe_with_provider(
                    Engine,
                    "a" * 32,
                    provider=AUTO,
                    profile="balanced",
                )
                assert result == artifact
                assert faster_call.call_args.kwargs["model"] == "small"
                assert faster_call.call_args.kwargs["compute_type"] == "int8"

            whisper_artifact = AiArtifactResult(
                "transcript",
                "b" * 32,
                root / "classic.srt",
                "small",
            )
            with patch(
                "asr_provider_router.transcribe_whisper",
                return_value=whisper_artifact,
            ) as whisper_call:
                result = transcribe_with_provider(
                    Engine,
                    "b" * 32,
                    provider=WHISPER,
                    model="small",
                )
                assert result == whisper_artifact
                assert whisper_call.call_args.kwargs["model"] == "small"

            sense_artifact = AiArtifactResult(
                "transcript",
                "c" * 32,
                root / "sense.srt",
                "sensevoice:small",
            )
            with patch(
                "asr_provider_router.transcribe_sensevoice",
                return_value=sense_artifact,
            ) as sense_call:
                result = transcribe_with_provider(
                    Engine,
                    "c" * 32,
                    provider=SENSEVOICE,
                    model="small",
                    language="zh",
                    device="auto",
                )
                assert result == sense_artifact
                assert sense_call.call_args.kwargs["model"] == "small"
                assert sense_call.call_args.kwargs["language"] == "zh"
                assert sense_call.call_args.kwargs["device"] == "cpu"

            try:
                transcribe_with_provider(
                    Engine,
                    "d" * 32,
                    provider=SENSEVOICE,
                    model="large-v3",
                )
            except AsrProviderRouterError as exc:
                assert exc.code == "ASR_MODEL_INVALID"
            else:
                raise AssertionError("SenseVoice accepted a Whisper-only model")

        with patch(
            "asr_provider_router.whisper_executable",
            return_value=None,
        ), patch(
            "asr_provider_router.list_whisper_models",
            return_value=[],
        ), patch(
            "asr_provider_router.faster_provider_status",
            return_value=FasterWhisperStatus(False, "", ()),
        ), patch(
            "asr_provider_router.sensevoice_provider_status",
            return_value=SenseVoiceStatus(False, False, "", ()),
        ):
            try:
                transcribe_with_provider(
                    Engine,
                    "e" * 32,
                    provider=SENSEVOICE,
                    model="small",
                )
            except AsrProviderRouterError as exc:
                assert exc.code == "ASR_PROVIDER_UNAVAILABLE"
            else:
                raise AssertionError("unavailable provider was accepted")

        try:
            recommend_asr_route(Engine, preferred_provider="../bad")
        except AsrProviderRouterError:
            pass
        else:
            raise AssertionError("unsafe ASR provider id was accepted")
