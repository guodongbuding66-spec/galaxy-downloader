from __future__ import annotations

import json
import os
import re
import stat
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from runtime_storage import state_dir as runtime_state_dir
from url_policy import validated_public_http_url

PROVIDERS_FILENAME = "ai-providers.json"
SECRETS_FILENAME = "ai-provider-secrets.json"
SCHEMA_VERSION = 1
MAX_PROVIDERS = 100
MAX_API_KEY_CHARS = 4096
PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_PROTOCOLS = {"openai", "anthropic", "google", "azure-openai", "ollama"}
_SECRET_QUERY_RE = re.compile(r"(?:key|token|secret|password|credential|signature|sig)", re.I)

_DEFAULT_ROWS = (
    ("openai", "OpenAI", "openai", "https://api.openai.com/v1/chat/completions", True),
    ("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com/v1/messages", True),
    ("gemini", "Google Gemini", "google", "https://generativelanguage.googleapis.com/v1beta", True),
    ("deepseek", "DeepSeek", "openai", "https://api.deepseek.com/chat/completions", True),
    ("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1/chat/completions", True),
    ("groq", "Groq", "openai", "https://api.groq.com/openai/v1/chat/completions", True),
    ("xai", "xAI", "openai", "https://api.x.ai/v1/chat/completions", True),
    ("ollama", "Ollama", "ollama", "http://127.0.0.1:11434/api/chat", True),
    ("lmstudio", "LM Studio", "openai", "http://127.0.0.1:1234/v1/chat/completions", True),
    ("azure-openai", "Azure OpenAI", "azure-openai", "", False),
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

    @property
    def capabilities(self) -> tuple[str, ...]:
        values = ["chat"]
        if self.allow_local:
            values.append("local")
        return tuple(values)

    def public_payload(self, *, has_api_key: bool = False) -> dict[str, Any]:
        data = asdict(self)
        data["baseUrl"] = data.pop("base_url")
        data["allowLocal"] = data.pop("allow_local")
        data["timeoutSeconds"] = data.pop("timeout_seconds")
        data["hasApiKey"] = bool(has_api_key)
        data["capabilities"] = list(self.capabilities)
        return data


def _state_path(engine_module, filename: str) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / filename


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


def _clean_name(value: object, fallback: str) -> str:
    name = " ".join(str(value or fallback).split()).strip()[:80]
    return name or fallback


def _is_loopback_endpoint(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def _reject_secret_query(value: str) -> None:
    try:
        pairs = parse_qsl(urlparse(value).query, keep_blank_values=True)
    except ValueError as exc:
        raise AiProviderConfigError("AI Provider URL 无效") from exc
    if any(_SECRET_QUERY_RE.search(key or "") for key, _value in pairs):
        raise AiProviderConfigError("AI Provider URL 不能包含 API key/token/secret 等凭据参数")


def validate_provider_endpoint(value: object, *, allow_local: bool = False, allow_empty: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        if allow_empty:
            return ""
        raise AiProviderConfigError("AI Provider URL 不能为空")
    try:
        parsed = urlparse(raw)
    except ValueError as exc:
        raise AiProviderConfigError("AI Provider URL 无效") from exc
    if parsed.username is not None or parsed.password is not None:
        raise AiProviderConfigError("AI Provider URL 不能包含用户名或密码")
    if parsed.fragment:
        raise AiProviderConfigError("AI Provider URL 不能包含 fragment")
    _reject_secret_query(raw)
    if allow_local and parsed.scheme == "http" and _is_loopback_endpoint(raw):
        return raw.rstrip("/")
    if parsed.scheme != "https":
        raise AiProviderConfigError("远程 AI Provider 必须使用 HTTPS")
    try:
        validated = validated_public_http_url(raw)
    except Exception as exc:
        raise AiProviderConfigError("AI Provider 必须是公网 HTTPS 地址") from exc
    return str(validated).rstrip("/")


def _defaults() -> dict[str, AiProviderConfig]:
    result: dict[str, AiProviderConfig] = {}
    for provider_id, name, protocol, url, enabled in _DEFAULT_ROWS:
        local = provider_id in {"ollama", "lmstudio"}
        result[provider_id] = AiProviderConfig(
            id=provider_id,
            name=name,
            protocol=protocol,
            base_url=url,
            enabled=enabled,
            custom=False,
            allow_local=local,
        )
    return result


def _atomic_json(path: Path, payload: object, *, secret: bool = False) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if secret and os.name != "nt":
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        temporary.replace(path)
        if secret and os.name != "nt":
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        with suppress(OSError):
            temporary.unlink()
        raise


def _stored_provider_rows(engine_module) -> list[dict[str, Any]]:
    try:
        payload = json.loads(_state_path(engine_module, PROVIDERS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get("version") != SCHEMA_VERSION:
        return []
    rows = payload.get("providers")
    return [row for row in rows[:MAX_PROVIDERS] if isinstance(row, dict)] if isinstance(rows, list) else []


def _row_to_provider(row: dict[str, Any], defaults: dict[str, AiProviderConfig]) -> AiProviderConfig | None:
    try:
        provider_id = _clean_id(row.get("id"))
        base = defaults.get(provider_id)
        protocol = _clean_protocol(row.get("protocol") or (base.protocol if base else "openai"))
        allow_local = bool(row.get("allowLocal", base.allow_local if base else False))
        raw_url = row.get("baseUrl")
        if raw_url in (None, "") and base is not None:
            raw_url = base.base_url
        base_url = validate_provider_endpoint(
            raw_url,
            allow_local=allow_local,
            allow_empty=provider_id == "azure-openai",
        )
        model = _clean_model(row.get("model"))
    except AiProviderConfigError:
        return None
    name = _clean_name(row.get("name"), base.name if base else provider_id)
    enabled_default = base.enabled if base else True
    return AiProviderConfig(
        id=provider_id,
        name=name,
        protocol=protocol,
        base_url=base_url,
        model=model,
        enabled=bool(row.get("enabled", enabled_default)),
        custom=provider_id not in defaults,
        allow_local=allow_local,
        timeout_seconds=_bounded_timeout(row.get("timeoutSeconds"), default=base.timeout_seconds if base else 180),
    )


def load_ai_providers(engine_module) -> list[AiProviderConfig]:
    defaults = _defaults()
    result = dict(defaults)
    custom_order: list[str] = []
    for row in _stored_provider_rows(engine_module):
        provider = _row_to_provider(row, defaults)
        if provider is None:
            continue
        result[provider.id] = provider
        if provider.custom and provider.id not in custom_order:
            custom_order.append(provider.id)
    builtins = [result[row[0]] for row in _DEFAULT_ROWS]
    customs = [result[provider_id] for provider_id in custom_order if provider_id in result]
    return builtins + customs


def _stored_payload(provider: AiProviderConfig) -> dict[str, Any]:
    return {
        "id": provider.id,
        "name": provider.name,
        "protocol": provider.protocol,
        "baseUrl": provider.base_url,
        "model": provider.model,
        "enabled": provider.enabled,
        "allowLocal": provider.allow_local,
        "timeoutSeconds": provider.timeout_seconds,
    }


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
    api_key: object = "",
) -> AiProviderConfig:
    clean_id = _clean_id(provider_id)
    defaults = _defaults()
    base = defaults.get(clean_id)
    clean_protocol = _clean_protocol(protocol or (base.protocol if base else "openai"))
    local = bool(allow_local or (base.allow_local if base else False))
    clean_url = validate_provider_endpoint(
        base_url,
        allow_local=local,
        allow_empty=clean_id == "azure-openai" and not enabled,
    )
    provider = AiProviderConfig(
        id=clean_id,
        name=_clean_name(name, base.name if base else clean_id),
        protocol=clean_protocol,
        base_url=clean_url,
        model=_clean_model(model),
        enabled=bool(enabled),
        custom=clean_id not in defaults,
        allow_local=local,
        timeout_seconds=_bounded_timeout(timeout_seconds),
    )
    rows = [
        row
        for row in _stored_provider_rows(engine_module)
        if str(row.get("id") or "").strip().lower() != clean_id
    ]
    rows.append(_stored_payload(provider))
    _atomic_json(
        _state_path(engine_module, PROVIDERS_FILENAME),
        {"version": SCHEMA_VERSION, "providers": rows[:MAX_PROVIDERS]},
    )
    if str(api_key or "").strip():
        set_provider_api_key(engine_module, clean_id, api_key)
    return provider


def delete_ai_provider(engine_module, provider_id: object) -> bool:
    clean_id = _clean_id(provider_id)
    if clean_id in _defaults():
        raise AiProviderConfigError("内置 Provider 不能删除；请使用 Reset 恢复默认配置")
    rows = _stored_provider_rows(engine_module)
    kept = [row for row in rows if str(row.get("id") or "").strip().lower() != clean_id]
    if len(kept) == len(rows):
        return False
    _atomic_json(_state_path(engine_module, PROVIDERS_FILENAME), {"version": SCHEMA_VERSION, "providers": kept})
    delete_provider_api_key(engine_module, clean_id)
    return True


def reset_ai_provider(engine_module, provider_id: object) -> AiProviderConfig:
    clean_id = _clean_id(provider_id)
    default = _defaults().get(clean_id)
    if default is None:
        raise AiProviderConfigError("只有内置 Provider 支持 Reset")
    rows = _stored_provider_rows(engine_module)
    kept = [row for row in rows if str(row.get("id") or "").strip().lower() != clean_id]
    _atomic_json(_state_path(engine_module, PROVIDERS_FILENAME), {"version": SCHEMA_VERSION, "providers": kept})
    delete_provider_api_key(engine_module, clean_id)
    return default


def _load_secrets(engine_module) -> dict[str, str]:
    path = _state_path(engine_module, SECRETS_FILENAME)
    if path.is_symlink():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("version") != SCHEMA_VERSION:
        return {}
    values = payload.get("keys")
    if not isinstance(values, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in values.items():
        if isinstance(key, str) and PROVIDER_ID_RE.fullmatch(key) and isinstance(value, str) and value:
            result[key] = value[:MAX_API_KEY_CHARS]
    return result


def set_provider_api_key(engine_module, provider_id: object, api_key: object) -> None:
    clean_id = _clean_id(provider_id)
    value = str(api_key or "").strip()
    if not value:
        raise AiProviderConfigError("API Key 不能为空")
    if len(value) > MAX_API_KEY_CHARS:
        raise AiProviderConfigError("API Key 过长")
    secrets = _load_secrets(engine_module)
    secrets[clean_id] = value
    _atomic_json(
        _state_path(engine_module, SECRETS_FILENAME),
        {"version": SCHEMA_VERSION, "keys": secrets},
        secret=True,
    )


def delete_provider_api_key(engine_module, provider_id: object) -> bool:
    clean_id = _clean_id(provider_id)
    secrets = _load_secrets(engine_module)
    if clean_id not in secrets:
        return False
    secrets.pop(clean_id, None)
    _atomic_json(
        _state_path(engine_module, SECRETS_FILENAME),
        {"version": SCHEMA_VERSION, "keys": secrets},
        secret=True,
    )
    return True


def provider_has_api_key(engine_module, provider_id: object) -> bool:
    clean_id = str(provider_id or "").strip().lower()
    return bool(PROVIDER_ID_RE.fullmatch(clean_id) and _load_secrets(engine_module).get(clean_id))


def provider_api_key(engine_module, provider_id: object) -> str:
    clean_id = _clean_id(provider_id)
    return _load_secrets(engine_module).get(clean_id, "")


def provider_public_status(engine_module) -> list[dict[str, Any]]:
    return [
        item.public_payload(has_api_key=provider_has_api_key(engine_module, item.id))
        for item in load_ai_providers(engine_module)
    ]


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

        def public_url(value: str) -> str:
            if value.startswith("https://"):
                return value
            raise ValueError("not public")

        with patch("ai_provider_registry.validated_public_http_url", side_effect=public_url):
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
                api_key="secret-value",
            )
            assert saved.custom and saved.timeout_seconds == 42
            assert provider_has_api_key(Engine, "custom")
            rendered = json.dumps(provider_public_status(Engine), ensure_ascii=False)
            assert "secret-value" not in rendered
            assert next(item for item in provider_public_status(Engine) if item["id"] == "custom")["hasApiKey"] is True

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
            reset = reset_ai_provider(Engine, "openai")
            assert reset.name == "OpenAI" and reset.enabled is True

            assert delete_ai_provider(Engine, "custom")
            assert not provider_has_api_key(Engine, "custom")
            assert all(item.id != "custom" for item in load_ai_providers(Engine))

            try:
                validate_provider_endpoint("https://example.com/v1?api_key=secret")
            except AiProviderConfigError:
                pass
            else:
                raise AssertionError("credential-bearing Provider URL was accepted")

            try:
                save_ai_provider(
                    Engine,
                    provider_id="../bad",
                    name="Bad",
                    protocol="openai",
                    base_url="https://example.com",
                )
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
