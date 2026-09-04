from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ai_models import WHISPER_MODELS
from asr_model_manager import (
    AsrModelError,
    install_whisper_model,
    list_whisper_models,
    remove_whisper_model,
)
from asr_preferences import (
    AsrPreferencesError,
    asr_preferences_status,
    load_asr_preferences,
    reset_asr_preferences,
    save_asr_preferences,
)
from asr_provider_router import (
    ASR_PROVIDERS,
    AUTO,
    FASTER_WHISPER,
    WHISPER,
    AsrProviderRouterError,
    list_asr_providers,
    recommend_asr_route,
    transcribe_with_provider,
)
from faster_whisper_provider import (
    FasterWhisperError,
    install_model as install_faster_whisper_model,
    provider_status as faster_whisper_status,
    remove_model as remove_faster_whisper_model,
)
from platform_paths import resolve_platform_paths

_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_-]{0,32}$")
_WINDOWS_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s\"'<>|]+")
_POSIX_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_:])/(?:home|Users|root|tmp|var|mnt|srv|opt|private)(?:/[^\s\"'<>|,;:]+)+"
)
_ALLOWED_DEVICES = {"", "auto", "cpu", "cuda"}
_ALLOWED_COMPUTE_TYPES = {"", "default", "int8", "int8_float16", "float16", "float32"}
_ALLOWED_PROFILES = {"fast", "balanced", "accurate"}


class HeadlessAsrApiError(RuntimeError):
    status = 400
    code = "ASR_INVALID_REQUEST"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class HeadlessAsrNotFoundError(HeadlessAsrApiError):
    status = 404
    code = "ASR_NOT_FOUND"


class HeadlessAsrConflictError(HeadlessAsrApiError):
    status = 409
    code = "ASR_CONFLICT"


def _safe_directory(value: Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    if raw.exists() and raw.is_symlink():
        raise HeadlessAsrApiError(f"{label} cannot be a symbolic link")
    resolved = raw.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(parsed, high))


def _clean_media_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _MEDIA_ID_RE.fullmatch(clean):
        raise HeadlessAsrApiError("invalid media id", code="ASR_INVALID_MEDIA_ID")
    return clean


def _clean_provider(value: object, *, allow_auto: bool = False) -> str:
    provider = str(value or "").strip().lower()
    allowed = {AUTO, *ASR_PROVIDERS} if allow_auto else set(ASR_PROVIDERS)
    if provider not in allowed:
        raise HeadlessAsrApiError("invalid ASR provider", code="ASR_PROVIDER_INVALID")
    return provider


def _clean_model(value: object, *, allow_empty: bool = False) -> str:
    model = str(value or "").strip().lower()
    if not model and allow_empty:
        return ""
    if model not in WHISPER_MODELS:
        raise HeadlessAsrApiError("invalid ASR model", code="ASR_MODEL_INVALID")
    return model


def _clean_profile(value: object) -> str:
    profile = str(value or "balanced").strip().lower()
    if profile not in _ALLOWED_PROFILES:
        raise HeadlessAsrApiError("invalid ASR profile", code="ASR_PROFILE_INVALID")
    return profile


def _clean_language(value: object) -> str:
    language = str(value or "").strip()
    if not _LANGUAGE_RE.fullmatch(language):
        raise HeadlessAsrApiError("invalid ASR language", code="ASR_LANGUAGE_INVALID")
    return language


def _clean_device(value: object) -> str:
    device = str(value or "").strip().lower()
    if device not in _ALLOWED_DEVICES:
        raise HeadlessAsrApiError("invalid ASR device", code="ASR_DEVICE_INVALID")
    return device


def _clean_compute_type(value: object) -> str:
    compute = str(value or "").strip().lower()
    if compute not in _ALLOWED_COMPUTE_TYPES:
        raise HeadlessAsrApiError("invalid ASR compute type", code="ASR_COMPUTE_TYPE_INVALID")
    return compute


def _public_hardware(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}

    def number(name: str) -> float:
        try:
            return max(0.0, min(float(raw.get(name) or 0), 4096.0))
        except (TypeError, ValueError):
            return 0.0

    return {
        "ramGb": number("ramGb"),
        "vramGb": number("vramGb"),
        "gpuAvailable": bool(raw.get("gpuAvailable", False)),
    }


def _safe_detail(value: object, *, roots: Iterable[Path] = ()) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""

    candidates: set[str] = set()
    for root in (*tuple(roots), Path.home()):
        try:
            resolved = Path(root).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        candidates.add(str(resolved))
        candidates.add(resolved.as_posix())

    for candidate in sorted((item for item in candidates if item), key=len, reverse=True):
        text = text.replace(candidate, "[LOCAL_PATH]")

    text = _WINDOWS_PATH_RE.sub("[LOCAL_PATH]", text)
    text = _POSIX_PATH_RE.sub("[LOCAL_PATH]", text)
    return text[:1200]


def _translate_error(exc: Exception, *, roots: Iterable[Path] = ()) -> HeadlessAsrApiError:
    if isinstance(exc, HeadlessAsrApiError):
        return exc
    detail = _safe_detail(exc, roots=roots)
    if isinstance(exc, AsrProviderRouterError):
        if exc.code == "ASR_PROVIDER_UNAVAILABLE":
            return HeadlessAsrConflictError("ASR provider unavailable", code=exc.code)
        if exc.code == "ASR_MODEL_NOT_INSTALLED":
            return HeadlessAsrConflictError("ASR model not installed", code=exc.code)
        if exc.code in {"ASR_PROVIDER_INVALID", "ASR_MODEL_INVALID"}:
            return HeadlessAsrApiError(detail or "invalid ASR request", code=exc.code)
        if exc.code == "ASR_TRANSCRIBE_FAILED" and any(
            marker in detail
            for marker in ("媒体文件不可用", "媒体文件不存在", "已移出 Galaxy 下载目录")
        ):
            return HeadlessAsrNotFoundError("media file unavailable", code="ASR_MEDIA_NOT_FOUND")
        return HeadlessAsrApiError(detail or "ASR operation failed", code=exc.code)
    if isinstance(exc, (AsrPreferencesError, AsrModelError, FasterWhisperError)):
        return HeadlessAsrApiError(detail or "ASR operation failed")
    return HeadlessAsrApiError(detail or "ASR operation failed")


@dataclass(frozen=True)
class HeadlessAsrContext:
    program_path: Path
    data_path: Path
    state_path: Path
    downloads_path: Path

    def app_dir(self) -> Path:
        return self.program_path

    def data_dir(self) -> Path:
        self.data_path.mkdir(parents=True, exist_ok=True)
        return self.data_path

    def state_dir(self) -> Path:
        self.state_path.mkdir(parents=True, exist_ok=True)
        return self.state_path

    def default_download_dir(self) -> Path:
        self.downloads_path.mkdir(parents=True, exist_ok=True)
        return self.downloads_path


def build_headless_asr_context(
    download_root: Path,
    *,
    program_dir: Path | None = None,
    data_dir: Path | None = None,
    state_dir: Path | None = None,
) -> HeadlessAsrContext:
    program = Path(program_dir or Path(__file__).resolve().parent).expanduser().resolve(strict=False)
    paths = resolve_platform_paths(program_dir=program)
    data = _safe_directory(Path(data_dir or paths.data_dir), label="ASR data directory")
    state = _safe_directory(Path(state_dir or paths.state_dir), label="ASR state directory")
    downloads = _safe_directory(Path(download_root), label="ASR download root")
    return HeadlessAsrContext(program, data, state, downloads)


def _public_whisper_model(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provider": WHISPER,
        "model": str(row.get("model") or ""),
        "installed": bool(row.get("installed", False)),
        "managed": bool(row.get("managed", False)),
        "sizeBytes": max(0, int(row.get("sizeBytes") or 0)),
        "sizeMb": max(0, int(row.get("sizeMb") or 0)),
        "languages": str(row.get("languages") or ""),
        "precision": str(row.get("precision") or ""),
        "cpu": bool(row.get("cpu", True)),
        "gpu": bool(row.get("gpu", True)),
    }


def _public_faster_models(status) -> list[dict[str, Any]]:
    installed = set(status.installed_models)
    return [
        {
            "provider": FASTER_WHISPER,
            "model": model,
            "installed": model in installed,
            "managed": model in installed,
            "cpu": True,
            "gpu": True,
        }
        for model in WHISPER_MODELS
    ]


def _public_operation(
    *,
    success: bool,
    provider: str,
    model: str,
    detail: object,
    roots: Iterable[Path] = (),
) -> dict[str, Any]:
    return {
        "success": bool(success),
        "provider": provider,
        "model": model,
        "detail": _safe_detail(detail, roots=roots),
    }


class HeadlessAsrApi:
    """Stable path-safe Headless boundary for local ASR capabilities."""

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

    @property
    def _roots(self) -> tuple[Path, ...]:
        return (
            self.context.program_path,
            self.context.data_path,
            self.context.state_path,
            self.context.downloads_path,
        )

    def _error(self, exc: Exception) -> HeadlessAsrApiError:
        return _translate_error(exc, roots=self._roots)

    # Provider / recommendation ---------------------------------------
    def providers(self) -> dict[str, Any]:
        try:
            rows = list_asr_providers(self.context)
        except Exception as exc:
            raise self._error(exc) from exc
        return {"providers": rows, "count": len(rows)}

    def recommend(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        raw = payload if isinstance(payload, Mapping) else {}
        try:
            recommendation = recommend_asr_route(
                self.context,
                _public_hardware(raw.get("hardware")),
                profile=_clean_profile(raw.get("profile", "balanced")),
                preferred_provider=_clean_provider(raw.get("provider", AUTO), allow_auto=True),
            )
        except Exception as exc:
            raise self._error(exc) from exc
        return {"recommendation": recommendation.public_payload()}

    # Preferences ------------------------------------------------------
    def preferences(self, hardware: Mapping[str, Any] | None = None) -> dict[str, Any]:
        try:
            return asr_preferences_status(self.context, _public_hardware(hardware))
        except Exception as exc:
            raise self._error(exc) from exc

    def save_preferences(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            settings = save_asr_preferences(
                self.context,
                provider=_clean_provider(payload.get("provider", AUTO), allow_auto=True),
                profile=_clean_profile(payload.get("profile", "balanced")),
                model=_clean_model(payload.get("model", ""), allow_empty=True),
                language=_clean_language(payload.get("language", "")),
                device=_clean_device(payload.get("device", "")),
                compute_type=_clean_compute_type(payload.get("computeType", "")),
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

    def reset_preferences(self) -> dict[str, Any]:
        try:
            settings = reset_asr_preferences(self.context)
        except Exception as exc:
            raise self._error(exc) from exc
        return {
            "settings": settings.public_payload(),
            "modelDownloadAutomatic": False,
        }

    # Models -----------------------------------------------------------
    def models(self, provider_id: object = "") -> dict[str, Any]:
        requested = str(provider_id or "").strip().lower()
        providers = [_clean_provider(requested)] if requested else list(ASR_PROVIDERS)
        rows: list[dict[str, Any]] = []
        try:
            if WHISPER in providers:
                rows.extend(_public_whisper_model(row) for row in list_whisper_models(self.context))
            if FASTER_WHISPER in providers:
                rows.extend(_public_faster_models(faster_whisper_status(self.context)))
        except Exception as exc:
            raise self._error(exc) from exc
        return {"models": rows, "count": len(rows)}

    def install_model(
        self,
        provider_id: object,
        model_id: object,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider = _clean_provider(provider_id)
        model = _clean_model(model_id)
        raw = payload if isinstance(payload, Mapping) else {}
        timeout = _bounded_int(raw.get("timeoutSeconds"), 3600, 60, 7200)
        try:
            if provider == WHISPER:
                operation = install_whisper_model(self.context, model, timeout_seconds=timeout)
                rendered = _public_operation(
                    success=operation.success,
                    provider=provider,
                    model=model,
                    detail=operation.detail,
                    roots=self._roots,
                )
            else:
                success, detail = install_faster_whisper_model(
                    self.context,
                    model,
                    timeout_seconds=timeout,
                )
                rendered = _public_operation(
                    success=success,
                    provider=provider,
                    model=model,
                    detail=detail,
                    roots=self._roots,
                )
        except Exception as exc:
            raise self._error(exc) from exc
        return {"operation": rendered}

    def remove_model(self, provider_id: object, model_id: object) -> dict[str, Any]:
        provider = _clean_provider(provider_id)
        model = _clean_model(model_id)
        try:
            if provider == WHISPER:
                operation = remove_whisper_model(self.context, model)
                rendered = _public_operation(
                    success=operation.success,
                    provider=provider,
                    model=model,
                    detail=operation.detail,
                    roots=self._roots,
                )
            else:
                success, detail = remove_faster_whisper_model(self.context, model)
                rendered = _public_operation(
                    success=success,
                    provider=provider,
                    model=model,
                    detail=detail,
                    roots=self._roots,
                )
        except Exception as exc:
            raise self._error(exc) from exc
        return {"operation": rendered}

    # Transcription ----------------------------------------------------
    def transcribe(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        media_id = _clean_media_id(payload.get("mediaId"))
        hardware = _public_hardware(payload.get("hardware"))
        try:
            stored = load_asr_preferences(self.context)
            provider = _clean_provider(payload.get("provider", stored.provider), allow_auto=True)
            profile = _clean_profile(payload.get("profile", stored.profile))
            model = _clean_model(payload.get("model", stored.model), allow_empty=True)
            language = _clean_language(payload.get("language", stored.language))
            device = _clean_device(payload.get("device", stored.device))
            compute_type = _clean_compute_type(payload.get("computeType", stored.compute_type))
            timeout = _bounded_int(payload.get("timeoutSeconds"), 7200, 60, 14400)

            recommendation = recommend_asr_route(
                self.context,
                hardware,
                profile=profile,
                preferred_provider=provider,
            )
            effective_provider = recommendation.provider if provider == AUTO else provider
            effective_model = model or recommendation.model
            artifact = transcribe_with_provider(
                self.context,
                media_id,
                provider=provider,
                model=model,
                language=language,
                hardware=hardware,
                profile=profile,
                device=device,
                compute_type=compute_type,
                timeout_seconds=timeout,
            )
        except Exception as exc:
            raise self._error(exc) from exc

        # Deliberately omit artifact.path. Consumers retrieve the generated SRT
        # through the existing Headless Transcript API using mediaId.
        return {
            "transcript": {
                "kind": str(artifact.kind or "transcript"),
                "mediaId": str(artifact.media_id or media_id),
                "provider": effective_provider,
                "model": effective_model,
                "ready": True,
            }
        }
