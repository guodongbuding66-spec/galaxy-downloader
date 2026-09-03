from __future__ import annotations

import io
import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from ai_provider_registry import (
    AiProviderConfig,
    load_ai_providers,
    provider_api_key,
    validate_provider_endpoint,
)
from prompt_library import get_prompt

NETWORK = "NETWORK"
AUTH = "AUTH"
MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
RATE_LIMIT = "RATE_LIMIT"
TIMEOUT = "TIMEOUT"
PROVIDER_ERROR = "PROVIDER_ERROR"
MAX_AI_INPUT_CHARS = 450_000
MAX_AI_RESPONSE_BYTES = 4_000_000
MAX_AI_OUTPUT_CHARS = 1_000_000
_MODEL_ERROR_RE = re.compile(r"\b(model|deployment)\b.*\b(not found|does not exist|unknown|invalid)\b|\b(not found|does not exist|unknown|invalid)\b.*\b(model|deployment)\b", re.I)
_SECRET_DETAIL_RE = re.compile(r"(?i)(authorization|api[-_ ]?key|token|secret)\s*[:=]\s*[^\s,;]+")


class AiProviderRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, *, http_status: int = 0) -> None:
        super().__init__(message)
        self.code = code if code in {NETWORK, AUTH, MODEL_NOT_FOUND, RATE_LIMIT, TIMEOUT, PROVIDER_ERROR} else PROVIDER_ERROR
        self.http_status = max(0, int(http_status or 0))

    def public_payload(self) -> dict[str, Any]:
        return {"success": False, "code": self.code, "detail": str(self), "httpStatus": self.http_status}


@dataclass(frozen=True)
class ProviderRunResult:
    provider_id: str
    model: str
    text: str

    def public_payload(self) -> dict[str, str]:
        return {"providerId": self.provider_id, "model": self.model, "text": self.text}


def _provider(engine_module, provider_id: object) -> AiProviderConfig:
    clean = str(provider_id or "").strip().lower()
    provider = next((item for item in load_ai_providers(engine_module) if item.id == clean), None)
    if provider is None or not provider.enabled:
        raise AiProviderRuntimeError(PROVIDER_ERROR, "AI Provider 不存在或已禁用")
    if not provider.base_url:
        raise AiProviderRuntimeError(PROVIDER_ERROR, "AI Provider 尚未配置 Base URL")
    if not provider.model:
        raise AiProviderRuntimeError(MODEL_NOT_FOUND, "AI Provider 尚未配置模型")
    try:
        validate_provider_endpoint(provider.base_url, allow_local=provider.allow_local)
    except Exception as exc:
        raise AiProviderRuntimeError(PROVIDER_ERROR, "AI Provider Base URL 未通过安全校验") from exc
    return provider


def _scrub_detail(value: object, secret: str = "") -> str:
    detail = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    if secret:
        detail = detail.replace(secret, "[REDACTED]")
    detail = _SECRET_DETAIL_RE.sub(lambda match: match.group(1) + ": [REDACTED]", detail)
    return detail[-1400:]


def _bounded_read(response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = MAX_AI_RESPONSE_BYTES - total
        block = response.read(min(64 * 1024, remaining + 1))
        if not block:
            break
        total += len(block)
        if total > MAX_AI_RESPONSE_BYTES:
            raise AiProviderRuntimeError(PROVIDER_ERROR, "AI Provider 响应超过 4 MB 安全上限")
        chunks.append(block)
    return b"".join(chunks)


def _http_error_code(status: int, detail: str) -> str:
    if status in {401, 403}:
        return AUTH
    if status == 429:
        return RATE_LIMIT
    if status in {408, 504}:
        return TIMEOUT
    if status in {400, 404, 422} and _MODEL_ERROR_RE.search(detail):
        return MODEL_NOT_FOUND
    return PROVIDER_ERROR


def _json_request(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    timeout_seconds: int,
    secret: str = "",
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - provider endpoint is validated before this call
            raw = _bounded_read(response)
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read(4000).decode("utf-8", errors="replace")
        except Exception:
            error_body = ""
        detail = _scrub_detail(error_body or f"HTTP {exc.code}", secret)
        raise AiProviderRuntimeError(_http_error_code(exc.code, detail), detail or f"HTTP {exc.code}", http_status=exc.code) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise AiProviderRuntimeError(TIMEOUT, "AI Provider 请求超时") from exc
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
            raise AiProviderRuntimeError(TIMEOUT, "AI Provider 请求超时") from exc
        raise AiProviderRuntimeError(NETWORK, _scrub_detail(getattr(exc, "reason", exc), secret) or "AI Provider 网络错误") from exc
    except OSError as exc:
        raise AiProviderRuntimeError(NETWORK, _scrub_detail(exc, secret) or "AI Provider 网络错误") from exc
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise AiProviderRuntimeError(PROVIDER_ERROR, "AI Provider 返回了无效 JSON") from exc
    if not isinstance(result, dict):
        raise AiProviderRuntimeError(PROVIDER_ERROR, "AI Provider 响应格式无效")
    return result


def _credential(engine_module, provider: AiProviderConfig) -> str:
    key = provider_api_key(engine_module, provider.id)
    if provider.allow_local:
        return key
    if provider.protocol in {"openai", "anthropic", "google", "azure-openai"} and not key:
        raise AiProviderRuntimeError(AUTH, f"{provider.name} 的 API Key Reference 当前没有可用值")
    return key


def _azure_url(provider: AiProviderConfig) -> str:
    raw = provider.base_url.rstrip("/")
    parsed = urlsplit(raw)
    if "/openai/deployments/" in parsed.path and parsed.path.endswith("/chat/completions"):
        return raw
    path = parsed.path.rstrip("/") + f"/openai/deployments/{quote(provider.model, safe='')}/chat/completions"
    query = parsed.query or "api-version=2024-10-21"
    return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def _google_url(provider: AiProviderConfig) -> str:
    return f"{provider.base_url.rstrip('/')}/models/{quote(provider.model, safe='')}:generateContent"


def _openai_text(result: dict[str, Any]) -> str:
    choices = result.get("choices") if isinstance(result.get("choices"), list) else []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return ""


def _anthropic_text(result: dict[str, Any]) -> str:
    content = result.get("content") if isinstance(result.get("content"), list) else []
    return "\n".join(str(item.get("text") or "") for item in content if isinstance(item, dict)).strip()


def _google_text(result: dict[str, Any]) -> str:
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    if not candidates or not isinstance(candidates[0], dict):
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0].get("content"), dict) else {}
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    return "\n".join(str(item.get("text") or "") for item in parts if isinstance(item, dict)).strip()


def _ollama_text(result: dict[str, Any]) -> str:
    message = result.get("message") if isinstance(result.get("message"), dict) else {}
    return str(message.get("content") or "").strip()


def run_provider_prompt(
    engine_module,
    provider_id: object,
    instructions: object,
    content: object,
) -> ProviderRunResult:
    provider = _provider(engine_module, provider_id)
    system = str(instructions or "").strip()[:20_000]
    user_content = str(content or "")[:MAX_AI_INPUT_CHARS]
    if not system or not user_content.strip():
        raise AiProviderRuntimeError(PROVIDER_ERROR, "Prompt 或输入内容为空")
    key = _credential(engine_module, provider)
    timeout = provider.timeout_seconds

    if provider.protocol == "anthropic":
        result = _json_request(
            provider.base_url,
            {"model": provider.model, "max_tokens": 4096, "system": system, "messages": [{"role": "user", "content": user_content}]},
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
            timeout_seconds=timeout,
            secret=key,
        )
        text = _anthropic_text(result)
    elif provider.protocol == "google":
        result = _json_request(
            _google_url(provider),
            {"system_instruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user_content}]}]},
            {"x-goog-api-key": key},
            timeout_seconds=timeout,
            secret=key,
        )
        text = _google_text(result)
    elif provider.protocol == "ollama":
        result = _json_request(
            provider.base_url,
            {"model": provider.model, "stream": False, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}]},
            {},
            timeout_seconds=timeout,
        )
        text = _ollama_text(result)
    elif provider.protocol == "azure-openai":
        result = _json_request(
            _azure_url(provider),
            {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}], "temperature": 0.2},
            {"api-key": key},
            timeout_seconds=timeout,
            secret=key,
        )
        text = _openai_text(result)
    else:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        result = _json_request(
            provider.base_url,
            {"model": provider.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}], "temperature": 0.2},
            headers,
            timeout_seconds=timeout,
            secret=key,
        )
        text = _openai_text(result)

    if not text:
        raise AiProviderRuntimeError(PROVIDER_ERROR, "AI Provider 没有返回文本")
    return ProviderRunResult(provider.id, provider.model, text[:MAX_AI_OUTPUT_CHARS])


def run_prompt_template(
    engine_module,
    provider_id: object,
    prompt_id: object,
    content: object,
    *,
    extra_instruction: object = "",
) -> ProviderRunResult:
    prompt = get_prompt(engine_module, prompt_id)
    if prompt is None:
        raise AiProviderRuntimeError(PROVIDER_ERROR, "Prompt 不存在")
    instructions = prompt.instructions
    extra = str(extra_instruction or "").strip()[:4000]
    if extra:
        instructions += "\n\n额外要求：" + extra
    return run_provider_prompt(engine_module, provider_id, instructions, content)


def test_provider_connection(engine_module, provider_id: object) -> dict[str, Any]:
    try:
        result = run_provider_prompt(engine_module, provider_id, "Reply with exactly OK.", "connection test")
    except AiProviderRuntimeError as exc:
        return exc.public_payload()
    return {"success": True, "code": "OK", "detail": result.text[:200], "providerId": result.provider_id, "model": result.model}


def run_ai_provider_runtime_self_test() -> None:
    import os
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    from ai_provider_registry import save_ai_provider
    from prompt_library import save_prompt

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
            save_ai_provider(
                Engine,
                provider_id="custom",
                name="Custom",
                protocol="openai",
                base_url="https://example.com/v1/chat/completions",
                model="model-1",
                credential_reference="env:CUSTOM_AI_KEY",
                timeout_seconds=17,
            )
            save_prompt(Engine, prompt_id="test-prompt", title="Test", instructions="Summarize")

        calls: list[tuple[str, dict[str, Any], dict[str, str], int, str]] = []

        def fake_request(url, payload, headers, *, timeout_seconds, secret=""):
            calls.append((url, payload, headers, timeout_seconds, secret))
            return {"choices": [{"message": {"content": "OK result"}}]}

        with patch.dict(os.environ, {"CUSTOM_AI_KEY": "super-secret"}, clear=False), patch(
            "ai_provider_runtime.validate_provider_endpoint", side_effect=lambda value, **_kwargs: value
        ), patch("ai_provider_runtime._json_request", side_effect=fake_request):
            result = run_provider_prompt(Engine, "custom", "System", "User")
            assert result.text == "OK result"
            assert calls[-1][2]["Authorization"] == "Bearer super-secret"
            assert calls[-1][3] == 17
            templated = run_prompt_template(Engine, "custom", "test-prompt", "content")
            assert templated.text == "OK result"

        assert _http_error_code(401, "bad") == AUTH
        assert _http_error_code(429, "slow") == RATE_LIMIT
        assert _http_error_code(504, "timeout") == TIMEOUT
        assert _http_error_code(404, "model foo not found") == MODEL_NOT_FOUND
        assert _http_error_code(404, "endpoint missing") == PROVIDER_ERROR
        assert "super-secret" not in _scrub_detail("Authorization=super-secret", "super-secret")

        error = urllib.error.HTTPError("https://example.com", 429, "Too Many", {}, io.BytesIO(b'{"error":"rate limited"}'))
        with patch("ai_provider_runtime.urllib.request.urlopen", side_effect=error):
            try:
                _json_request("https://example.com", {"x": 1}, {}, timeout_seconds=5)
            except AiProviderRuntimeError as exc:
                assert exc.code == RATE_LIMIT and exc.http_status == 429
            else:
                raise AssertionError("HTTP 429 was not classified")

        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
            def read(self, _size=-1):
                if getattr(self, "done", False):
                    return b""
                self.done = True
                return b'{"ok":true}'

        with patch("ai_provider_runtime.urllib.request.urlopen", return_value=FakeResponse()):
            assert _json_request("https://example.com", {"x": 1}, {}, timeout_seconds=5)["ok"] is True
