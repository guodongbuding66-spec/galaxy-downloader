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

WHISPER = "whisper"
FASTER_WHISPER = "faster-whisper"
AUTO = "auto"
ASR_PROVIDERS = (WHISPER, FASTER_WHISPER)
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
    allowed = {AUTO, *ASR_PROVIDERS} if allow_auto else set(ASR_PROVIDERS)
    if provider not in allowed:
        raise AsrProviderRouterError("ASR_PROVIDER_INVALID", "ASR Provider 无效")
    return provider


def _clean_model(value: object) -> str:
    model = str(value or "").strip().lower()
    if model and model not in WHISPER_MODELS:
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


def list_asr_providers(engine_module) -> list[dict[str, Any]]:
    """Return the stable public status for every supported local ASR runtime."""
    return [_whisper_status(engine_module), _faster_status(engine_module)]


def _status_map(engine_module) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in list_asr_providers(engine_module)}


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

    faster = recommend_faster(hardware, profile=mode)
    whisper_model = recommend_whisper_model(hardware, profile=mode)

    if preferred == AUTO:
        # Prefer faster-whisper when its optional runtime exists. It is normally
        # the better desktop default, while the classic Whisper CLI remains a
        # fully supported fallback. Model installation is still explicit.
        selected = (
            FASTER_WHISPER
            if bool(statuses[FASTER_WHISPER]["runtimeAvailable"])
            else WHISPER
        )
    else:
        selected = preferred

    if selected == FASTER_WHISPER:
        model = _clean_model(faster.get("model")) or "base"
        device = str(faster.get("device") or "cpu")
        compute_type = str(faster.get("computeType") or "int8")
    else:
        model = _clean_model(whisper_model) or "base"
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

    requested_model = _clean_model(model) or recommendation.model
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
        return transcribe_whisper(
            engine_module,
            media_id,
            model=requested_model,
            language=language,
            timeout_seconds=timeout_seconds,
        )
    except (AsrModelError, FasterWhisperError) as exc:
        raise AsrProviderRouterError("ASR_TRANSCRIBE_FAILED", str(exc)[-1600:]) from exc
    except Exception as exc:
        # ai_workspace owns its own error type; keep the router independent from
        # that implementation detail while still presenting one stable boundary.
        raise AsrProviderRouterError("ASR_TRANSCRIBE_FAILED", str(exc)[-1600:]) from exc


def run_asr_provider_router_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    from faster_whisper_provider import FasterWhisperStatus

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
            "asr_provider_router.recommend_faster",
            return_value={"model": "small", "device": "cpu", "computeType": "int8"},
        ), patch(
            "asr_provider_router.recommend_whisper_model",
            return_value="small",
        ):
            providers = list_asr_providers(Engine)
            assert [item["id"] for item in providers] == [WHISPER, FASTER_WHISPER]
            assert all(item["runtimeAvailable"] for item in providers)

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

        with patch(
            "asr_provider_router.whisper_executable",
            return_value=None,
        ), patch(
            "asr_provider_router.list_whisper_models",
            return_value=[],
        ), patch(
            "asr_provider_router.faster_provider_status",
            return_value=FasterWhisperStatus(False, "", ()),
        ):
            try:
                transcribe_with_provider(
                    Engine,
                    "c" * 32,
                    provider=FASTER_WHISPER,
                    model="base",
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
