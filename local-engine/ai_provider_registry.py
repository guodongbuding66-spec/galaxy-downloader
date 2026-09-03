from __future__ import annotations

import json
import os
import re
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from runtime_storage import state_dir as runtime_state_dir
from url_policy import validated_public_http_url

PROVIDERS_FILENAME = "ai-providers.json"
SCHEMA_VERSION = 1
MAX_PROVIDERS = 100
PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
ENV_REFERENCE_RE = re.compile(r"^env:([A-Z_][A-Z0-9_]*)$")
_PROTOCOLS = {"openai", "anthropic", "google", "azure-openai", "ollama"}
_SECRET_QUERY_RE = re.compile(r"(?:key|token|secret|password|credential|signature|sig)", re.I)

_DEFAULT_ROWS = (
    ("openai", "OpenAI", "openai", "https://api.openai.com/v1/chat/completions", True, "env:OPENAI_API_KEY"),
    ("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com/v1/messages", True, "env:ANTHROPIC_API_KEY"),
    ("gemini", "Google Gemini", "google", "https://generativelanguage.googleapis.com/v1beta", True, "env:GEMINI_API_KEY"),
    ("deepseek", "DeepSeek", "openai", "https://api.deepseek.com/chat/completions", True, "env:DEEPSEEK_API_KEY"),
    ("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1/chat/completions", True, "env:OPENROUTER_API_KEY"),
    ("groq", "Groq", "openai", "https://api.groq.com/openai/v1/chat/completions", True, "env:GROQ_API_KEY"),
    ("xai", "xAI", "openai", "https://api.x.ai/v1/chat/completions", True, "env:XAI_API_KEY"),
    ("ollama", "Ollama", "ollama", "http://127.0.0.1:11434/api/chat", True, ""),
    ("lmstudio", "LM Studio", "openai", "http://127.0.0.1:1234/v1/chat/completions", True, ""),
    ("azure-openai", "Azure OpenAI", "azure-openai", "", False, "env:AZURE_OPENAI_API_KEY"),
)


class AiProviderConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class AiProviderConfig:
    id: str
    name: str
    protocol: str
    base_url: str
    model: str = ""
    enabled: bool = True
    custom: bool = False
    allow_local: bool = False
    timeout_seconds: int = 180
    credential_reference: str = ""

    @property
    def capabilities(self) -> tuple[str, ...]:
        values = ["chat"]
        if self.allow_local:
            values.append("local")
        return tuple(values)

    def public_payload(self, *, has_credential: bool = False) -> dict[str, Any]:
        data = asdict(self)
        data["baseUrl"] = data.pop("base_url")
        data["allowLocal"] = data.pop("allow_local")
        data["timeoutSeconds"] = data.pop("timeout_seconds")
        data["credentialReference"] = data.pop("credential_reference")
        data["hasApiKey"] = bool(has_credential)
        data["capabilities"] = list(self.capabilities)
        return data


def _state_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / PROVIDERS_FILENAME


def _bounded_timeout(value: object, *, default: int = 180) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(5, min(parsed, 600))


def _clean_id(value: object) -> str:
    provider_id = str(value or "").strip().lower()
    if not PROVIDER_ID_RE.fullmatch(provider_id):
        raise AiProviderConfigError("Provider ID 无效")
    return provider_id


def _clean_protocol(value: object) -> str:
    protocol = str(value or "").strip().lower()
    if protocol not in _PROTOCOLS:
        raise AiProviderConfigError("Provider 协议无效")
    return protocol


def _clean_model(value: object) -> str:
    model = str(value or "").strip()
    if not model:
        return ""
    if not MODEL_RE.fullmatch(model):
        raise AiProviderConfigError("Provider 模型名称无效")
    return model


def _clean_credential_reference(value: object) -> str:
    reference = str(value or "").strip()
    if not reference:
        return ""
    match = ENV_REFERENCE_RE.fullmatch(reference)
    if match is None:
        raise AiProviderConfigError("API Key Reference 仅支持 env:VARIABLE_NAME")
    return "env:" + match.group(1)


def _clean_name(value: object, fallback: str) -> str:
    name = " ".join(str(value or fallback).split()).strip()[:80]
    return name or fallback


def _is_loopback_endpoint(value: str) -> bool:
    try:
        host = (urlparse(value).hostname or "").lower()
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def validate_provider_endpoint(value: object, *, allow_local: bool = False, allow_empty: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        if allow_empty:
            return ""
        raise AiProviderConfigError("AI Provider URL 不能为空")
    try:
        parsed = urlparse(raw)
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    except ValueError as exc:
        raise AiProviderConfigError("AI Provider URL 无效") from exc
    if parsed.username is not None or parsed.password is not None:
        raise AiProviderConfigError("AI Provider URL 不能包含用户名或密码")
    if parsed.fragment:
        raise AiProviderConfigError("AI Provider URL 不能包含 fragment")
    if any(_SECRET_QUERY_RE.search(key or "") for key, _value in query_pairs):
        raise AiProviderConfigError("AI Provider URL 不能包含凭据参数")
    if allow_local and parsed.scheme == "http" and _is_loopback_endpoint(raw):
        return raw.rstrip("/")
    if parsed.scheme != "https":
        raise AiProviderConfigError("远程 AI Provider 必须使用 HTTPS")
    try:
        return str(validated_public_http_url(raw)).rstrip("/")
    except Exception as exc:
        raise AiProviderConfigError("AI Provider 必须是公网 HTTPS 地址") from exc


def _defaults() -> dict[str, AiProviderConfig]:
    result: dict[str, AiProviderConfig] = {}
    for provider_id, name, protocol, url, enabled, reference in _DEFAULT_ROWS:
        result[provider_id] = AiProviderConfig(
            id=provider_id,
            name=name,
            protocol=protocol,
            base_url=url,
            enabled=enabled,
            allow_local=provider_id in {"ollama", "lmstudio"},
            credential_reference=reference,
        )
    return result


def _atomic_store(engine_module, providers: list[AiProviderConfig]) -> None:
    path = _state_path(engine_module)
    temporary = path.with_suffix(path.suffix + ".tmp")
    rows = [
        {
            "id": item.id,
            "name": item.name,
            "protocol": item.protocol,
            "baseUrl": item.base_url,
            "model": item.model,
            "enabled": item.enabled,
            "allowLocal": item.allow_local,
            "timeoutSeconds": item.timeout_seconds,
            "credentialReference": item.credential_reference,
        }
        for item in providers[:MAX_PROVIDERS]
    ]
    try:
        temporary.write_text(
            json.dumps({"version": SCHEMA_VERSION, "providers": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        with suppress(OSError):
            temporary.unlink()
        raise


def _stored_rows(engine_module) -> list[dict[str, Any]]:
    try:
        payload = json.loads(_state_path(engine_module).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get("version") != SCHEMA_VERSION:
        return []
    rows = payload.get("providers")
    return [row for row in rows[:MAX_PROVIDERS] if isinstance(row, dict)] if isinstance(rows, list) else []


def _normalized_row(row: dict[str, Any], defaults: dict[str, AiProviderConfig]) -> AiProviderConfig | None:
    try:
        provider_id = _clean_id(row.get("id"))
        base = defaults.get(provider_id)
        protocol = _clean_protocol(row.get("protocol") or (base.protocol if base else "openai"))
        allow_local = bool(row.get("allowLocal", base.allow_local if base else False))
        endpoint = row.get("baseUrl")
        if endpoint in (None, "") and base is not None:
            endpoint = base.base_url
        base_url = validate_provider_endpoint(
            endpoint,
            allow_local=allow_local,
            allow_empty=provider_id == "azure-openai",
        )
        reference = _clean_credential_reference(
            row.get("credentialReference", base.credential_reference if base else "")
        )
        model = _clean_model(row.get("model"))
    except AiProviderConfigError:
        return None
    return AiProviderConfig(
        id=provider_id,
        name=_clean_name(row.get("name"), base.name if base else provider_id),
        protocol=protocol,
        base_url=base_url,
        model=model,
        enabled=bool(row.get("enabled", base.enabled if base else True)),
        custom=provider_id not in defaults,
        allow_local=allow_local,
        timeout_seconds=_bounded_timeout(row.get("timeoutSeconds"), default=base.timeout_seconds if base else 180),
        credential_reference=reference,
    )


def load_ai_providers(engine_module) -> list[AiProviderConfig]:
    defaults = _defaults()
    result = dict(defaults)
    custom_order: list[str] = []
    for row in _stored_rows(engine_module):
        provider = _normalized_row(row, defaults)
        if provider is None:
            continue
        result[provider.id] = provider
        if provider.custom and provider.id not in custom_order:
            custom_order.append(provider.id)
    return [result[row[0]] for row in _DEFAULT_ROWS] + [result[item] for item in custom_order if item in result]


def _configured_overrides(engine_module) -> list[AiProviderConfig]:
    defaults = _defaults()
    result: list[AiProviderConfig] = []
    for row in _stored_rows(engine_module):
        provider = _normalized_row(row, defaults)
        if provider is not None:
            result.append(provider)
    return result


def save_ai_provider(
    engine_module,
    *,
    provider_id: object,
    name: object,
    protocol: object,
    base_url: object,
    model: object = "",
    enabled: bool = True,
    allow_local: bool = False,
    timeout_seconds: object = 180,
    credential_reference: object = "",
) -> AiProviderConfig:
    clean_id = _clean_id(provider_id)
    defaults = _defaults()
    base = defaults.get(clean_id)
    local = bool(allow_local or (base.allow_local if base else False))
    reference_input = credential_reference if str(credential_reference or "").strip() else (base.credential_reference if base else "")
    provider = AiProviderConfig(
        id=clean_id,
        name=_clean_name(name, base.name if base else clean_id),
        protocol=_clean_protocol(protocol or (base.protocol if base else "openai")),
        base_url=validate_provider_endpoint(
            base_url,
            allow_local=local,
            allow_empty=clean_id == "azure-openai" and not enabled,
        ),
        model=_clean_model(model),
        enabled=bool(enabled),
        custom=clean_id not in defaults,
        allow_local=local,
        timeout_seconds=_bounded_timeout(timeout_seconds),
        credential_reference=_clean_credential_reference(reference_input),
    )
    overrides = [item for item in _configured_overrides(engine_module) if item.id != clean_id]
    overrides.append(provider)
    _atomic_store(engine_module, overrides)
    return provider


def delete_ai_provider(engine_module, provider_id: object) -> bool:
    clean_id = _clean_id(provider_id)
    if clean_id in _defaults():
        raise AiProviderConfigError("内置 Provider 不能删除；请使用 Reset 恢复默认配置")
    overrides = _configured_overrides(engine_module)
    kept = [item for item in overrides if item.id != clean_id]
    if len(kept) == len(overrides):
        return False
    _atomic_store(engine_module, kept)
    return True


def reset_ai_provider(engine_module, provider_id: object) -> AiProviderConfig:
    clean_id = _clean_id(provider_id)
    default = _defaults().get(clean_id)
    if default is None:
        raise AiProviderConfigError("只有内置 Provider 支持 Reset")
    _atomic_store(engine_module, [item for item in _configured_overrides(engine_module) if item.id != clean_id])
    return default


def provider_api_key(engine_module, provider_id: object) -> str:
    clean_id = _clean_id(provider_id)
    provider = next((item for item in load_ai_providers(engine_module) if item.id == clean_id), None)
    if provider is None or not provider.credential_reference:
        return ""
    match = ENV_REFERENCE_RE.fullmatch(provider.credential_reference)
    return os.environ.get(match.group(1), "") if match is not None else ""


def provider_has_api_key(engine_module, provider_id: object) -> bool:
    try:
        return bool(provider_api_key(engine_module, provider_id))
    except AiProviderConfigError:
        return False


def provider_public_status(engine_module) -> list[dict[str, Any]]:
    return [item.public_payload(has_credential=provider_has_api_key(engine_module, item.id)) for item in load_ai_providers(engine_module)]


def run_ai_provider_registry_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                target = root / "state"
                target.mkdir(parents=True, exist_ok=True)
                return target

        with patch("ai_provider_registry.validated_public_http_url", side_effect=lambda value: value):
            defaults = load_ai_providers(Engine)
            ids = {item.id for item in defaults}
            assert {"openai", "anthropic", "gemini", "deepseek", "openrouter", "groq", "azure-openai", "xai", "ollama", "lmstudio"}.issubset(ids)
            assert next(item for item in defaults if item.id == "azure-openai").enabled is False

            saved = save_ai_provider(
                Engine,
                provider_id="custom",
                name="Custom Provider",
                protocol="openai",
                base_url="https://example.com/v1/chat/completions",
                model="model-1",
                timeout_seconds=42,
                credential_reference="env:CUSTOM_AI_KEY",
            )
            assert saved.custom and saved.credential_reference == "env:CUSTOM_AI_KEY"
            stored_text = _state_path(Engine).read_text(encoding="utf-8")
            assert "secret-value" not in stored_text
            with patch.dict(os.environ, {"CUSTOM_AI_KEY": "secret-value"}, clear=False):
                assert provider_has_api_key(Engine, "custom")
                assert provider_api_key(Engine, "custom") == "secret-value"
                rendered = json.dumps(provider_public_status(Engine), ensure_ascii=False)
                assert "secret-value" not in rendered
                assert "env:CUSTOM_AI_KEY" in rendered

            changed = save_ai_provider(
                Engine,
                provider_id="openai",
                name="OpenAI Custom",
                protocol="openai",
                base_url="https://api.openai.com/v1/chat/completions",
                model="gpt-test",
                enabled=False,
            )
            assert changed.enabled is False
            assert reset_ai_provider(Engine, "openai").enabled is True
            assert delete_ai_provider(Engine, "custom")

            for bad_url in (
                "https://user:password@example.com/v1",
                "https://example.com/v1?api_key=secret",
                "https://example.com/v1#token",
            ):
                try:
                    validate_provider_endpoint(bad_url)
                except AiProviderConfigError:
                    pass
                else:
                    raise AssertionError("credential-bearing Provider URL was accepted")

            try:
                save_ai_provider(Engine, provider_id="../bad", name="Bad", protocol="openai", base_url="https://example.com")
            except AiProviderConfigError:
                pass
            else:
                raise AssertionError("unsafe Provider id was accepted")

            local = save_ai_provider(
                Engine,
                provider_id="local-custom",
                name="Local",
                protocol="openai",
                base_url="http://127.0.0.1:9999/v1/chat/completions",
                model="local-model",
                allow_local=True,
            )
            assert local.allow_local and local.base_url.startswith("http://127.0.0.1:")
