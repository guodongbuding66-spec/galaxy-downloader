from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ai_models import WHISPER_MODELS
from asr_provider_router import (
    AUTO,
    FASTER_WHISPER,
    PROFILES,
    SENSEVOICE,
    WHISPER,
    AsrProviderRouterError,
    recommend_asr_route,
    transcribe_with_provider,
)
from runtime_storage import state_dir as runtime_state_dir
from sensevoice_provider import LANGUAGES as SENSEVOICE_LANGUAGES, MODELS as SENSEVOICE_MODELS

SETTINGS_FILENAME = "asr-settings.json"
SCHEMA_VERSION = 1
PROVIDERS = (AUTO, WHISPER, FASTER_WHISPER, SENSEVOICE)
LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_-]{0,32}$")
DEVICE_RE = re.compile(r"^(?:|auto|cpu|mps|cuda(?::[0-9]{1,2})?)$")
DEVICES = ("", "auto", "cpu", "cuda", "mps")
COMPUTE_TYPES = ("", "default", "int8", "int8_float16", "float16", "float32")


class AsrPreferencesError(RuntimeError):
    pass


@dataclass(frozen=True)
class AsrPreferences:
    provider: str = AUTO
    profile: str = "balanced"
    model: str = ""
    language: str = ""
    device: str = ""
    compute_type: str = ""

    def public_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["computeType"] = data.pop("compute_type")
        return data


def _state_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / SETTINGS_FILENAME


def _clean_provider(value: object) -> str:
    provider = str(value or AUTO).strip().lower()
    if provider not in PROVIDERS:
        raise AsrPreferencesError("ASR Provider 偏好无效")
    return provider


def _clean_profile(value: object) -> str:
    profile = str(value or "balanced").strip().lower()
    if profile not in PROFILES:
        raise AsrPreferencesError("ASR Profile 偏好无效")
    return profile


def _clean_model(value: object, *, provider: str) -> str:
    model = str(value or "").strip().lower()
    if not model:
        return ""
    if provider == SENSEVOICE:
        allowed = set(SENSEVOICE_MODELS)
    else:
        allowed = set(WHISPER_MODELS)
    if model not in allowed:
        raise AsrPreferencesError("ASR 模型偏好无效")
    return model


def _clean_language(value: object, *, provider: str) -> str:
    language = str(value or "").strip().lower()
    if not LANGUAGE_RE.fullmatch(language):
        raise AsrPreferencesError("ASR 语言偏好无效")
    if provider == SENSEVOICE and language and language not in set(SENSEVOICE_LANGUAGES):
        raise AsrPreferencesError("SenseVoice 语言偏好无效")
    return language


def _clean_device(value: object) -> str:
    device = str(value or "").strip().lower()
    if not DEVICE_RE.fullmatch(device):
        raise AsrPreferencesError("ASR Device 偏好无效")
    return device


def _clean_compute_type(value: object, *, provider: str) -> str:
    compute = str(value or "").strip().lower()
    if compute not in COMPUTE_TYPES:
        raise AsrPreferencesError("ASR Compute Type 偏好无效")
    if provider == SENSEVOICE:
        if compute in {"", "default"}:
            return ""
        raise AsrPreferencesError("SenseVoice 不支持 Compute Type 偏好")
    return compute


def _normalize(payload: dict[str, Any] | None) -> AsrPreferences:
    raw = payload if isinstance(payload, dict) else {}
    provider = _clean_provider(raw.get("provider", AUTO))
    return AsrPreferences(
        provider=provider,
        profile=_clean_profile(raw.get("profile", "balanced")),
        model=_clean_model(raw.get("model", ""), provider=provider),
        language=_clean_language(raw.get("language", ""), provider=provider),
        device=_clean_device(raw.get("device", "")),
        compute_type=_clean_compute_type(
            raw.get("computeType", raw.get("compute_type", "")),
            provider=provider,
        ),
    )


def load_asr_preferences(engine_module) -> AsrPreferences:
    try:
        payload = json.loads(_state_path(engine_module).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return AsrPreferences()
    if not isinstance(payload, dict) or payload.get("version") != SCHEMA_VERSION:
        return AsrPreferences()
    try:
        return _normalize(payload)
    except AsrPreferencesError:
        return AsrPreferences()


def save_asr_preferences(
    engine_module,
    *,
    provider: object = AUTO,
    profile: object = "balanced",
    model: object = "",
    language: object = "",
    device: object = "",
    compute_type: object = "",
) -> AsrPreferences:
    preferences = _normalize(
        {
            "provider": provider,
            "profile": profile,
            "model": model,
            "language": language,
            "device": device,
            "computeType": compute_type,
        }
    )
    path = _state_path(engine_module)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {"version": SCHEMA_VERSION, **preferences.public_payload()}
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        with suppress(OSError):
            temporary.unlink()
        raise
    return preferences


def reset_asr_preferences(engine_module) -> AsrPreferences:
    path = _state_path(engine_module)
    try:
        if path.is_symlink():
            raise AsrPreferencesError("ASR 设置文件不能是符号链接")
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise AsrPreferencesError(str(exc)) from exc
    return AsrPreferences()


def asr_preferences_status(
    engine_module,
    hardware: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preferences = load_asr_preferences(engine_module)
    try:
        recommendation = recommend_asr_route(
            engine_module,
            hardware,
            profile=preferences.profile,
            preferred_provider=preferences.provider,
        ).public_payload()
    except AsrProviderRouterError as exc:
        recommendation = {"error": exc.public_payload()}
    return {
        "settings": preferences.public_payload(),
        "recommendation": recommendation,
        "modelDownloadAutomatic": False,
    }


def transcribe_with_preferences(
    engine_module,
    media_id: object,
    *,
    hardware: dict[str, Any] | None = None,
    timeout_seconds: int = 7200,
):
    preferences = load_asr_preferences(engine_module)
    return transcribe_with_provider(
        engine_module,
        media_id,
        provider=preferences.provider,
        model=preferences.model,
        language=preferences.language,
        hardware=hardware,
        profile=preferences.profile,
        device=preferences.device,
        compute_type=preferences.compute_type,
        timeout_seconds=timeout_seconds,
    )


def run_asr_preferences_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    from asr_provider_router import AsrRouteRecommendation

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        state.mkdir()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return state

        defaults = load_asr_preferences(Engine)
        assert defaults == AsrPreferences()

        saved = save_asr_preferences(
            Engine,
            provider=FASTER_WHISPER,
            profile="accurate",
            model="small",
            language="zh",
            device="cuda",
            compute_type="float16",
        )
        assert load_asr_preferences(Engine) == saved
        stored = json.loads((state / SETTINGS_FILENAME).read_text(encoding="utf-8"))
        assert stored["version"] == 1 and stored["provider"] == FASTER_WHISPER
        assert "apiKey" not in json.dumps(stored)

        recommendation = AsrRouteRecommendation(
            provider=FASTER_WHISPER,
            model="small",
            profile="accurate",
            runtime_available=True,
            model_installed=True,
            device="cuda",
            compute_type="float16",
        )
        with patch("asr_preferences.recommend_asr_route", return_value=recommendation):
            status = asr_preferences_status(Engine, {"vramGb": 12})
            assert status["recommendation"]["provider"] == FASTER_WHISPER
            assert status["modelDownloadAutomatic"] is False

        sentinel = object()
        with patch("asr_preferences.transcribe_with_provider", return_value=sentinel) as transcribe:
            result = transcribe_with_preferences(Engine, "a" * 32, hardware={"vramGb": 12})
            assert result is sentinel
            kwargs = transcribe.call_args.kwargs
            assert kwargs["provider"] == FASTER_WHISPER
            assert kwargs["model"] == "small"
            assert kwargs["language"] == "zh"
            assert kwargs["device"] == "cuda"
            assert kwargs["compute_type"] == "float16"

        sense = save_asr_preferences(
            Engine,
            provider=SENSEVOICE,
            profile="balanced",
            model="small",
            language="zh",
            device="mps",
            compute_type="default",
        )
        assert sense.provider == SENSEVOICE
        assert sense.model == "small"
        assert sense.language == "zh"
        assert sense.device == "mps"
        assert sense.compute_type == ""
        assert load_asr_preferences(Engine) == sense

        sense_recommendation = AsrRouteRecommendation(
            provider=SENSEVOICE,
            model="small",
            profile="balanced",
            runtime_available=True,
            model_installed=True,
            device="mps",
            compute_type="",
        )
        with patch("asr_preferences.recommend_asr_route", return_value=sense_recommendation):
            status = asr_preferences_status(Engine, {"metalAvailable": True})
            assert status["settings"]["provider"] == SENSEVOICE
            assert status["recommendation"]["provider"] == SENSEVOICE

        with patch("asr_preferences.transcribe_with_provider", return_value=sentinel) as transcribe:
            result = transcribe_with_preferences(Engine, "b" * 32, hardware={"metalAvailable": True})
            assert result is sentinel
            kwargs = transcribe.call_args.kwargs
            assert kwargs["provider"] == SENSEVOICE
            assert kwargs["model"] == "small"
            assert kwargs["language"] == "zh"
            assert kwargs["device"] == "mps"
            assert kwargs["compute_type"] == ""

        try:
            save_asr_preferences(Engine, provider=SENSEVOICE, model="large-v3")
        except AsrPreferencesError:
            pass
        else:
            raise AssertionError("SenseVoice accepted a Whisper-only model preference")

        try:
            save_asr_preferences(Engine, provider=SENSEVOICE, model="small", language="fr")
        except AsrPreferencesError:
            pass
        else:
            raise AssertionError("SenseVoice accepted an unsupported language preference")

        try:
            save_asr_preferences(
                Engine,
                provider=SENSEVOICE,
                model="small",
                compute_type="float16",
            )
        except AsrPreferencesError:
            pass
        else:
            raise AssertionError("SenseVoice accepted a faster-whisper compute preference")

        try:
            save_asr_preferences(Engine, provider="../bad")
        except AsrPreferencesError:
            pass
        else:
            raise AssertionError("unsafe ASR provider preference was accepted")

        reset_asr_preferences(Engine)
        assert load_asr_preferences(Engine) == AsrPreferences()
