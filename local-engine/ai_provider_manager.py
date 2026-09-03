from __future__ import annotations

import json
import os
import re
import stat
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from runtime_storage import state_dir as runtime_state_dir
from url_policy import validated_public_http_url

PROVIDERS_FILENAME = "ai-providers.json"
SECRETS_FILENAME = "ai-provider-secrets.json"
PROMPTS_FILENAME = "ai-prompts.json"
MAX_AI_INPUT_CHARS = 450_000
MAX_AI_RESPONSE_BYTES = 4_000_000
PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/ -]{0,159}$")

DEFAULT_PROVIDERS = {
    "openai": ("OpenAI", "openai", "https://api.openai.com/v1/chat/completions"),
    "anthropic": ("Anthropic", "anthropic", "https://api.anthropic.com/v1/messages"),
    "google": ("Google Gemini", "google", "https://generativelanguage.googleapis.com/v1beta"),
    "deepseek": ("DeepSeek", "openai", "https://api.deepseek.com/chat/completions"),
    "groq": ("Groq", "openai", "https://api.groq.com/openai/v1/chat/completions"),
    "huggingface": ("Hugging Face", "openai", "https://router.huggingface.co/v1/chat/completions"),
    "openrouter": ("OpenRouter", "openai", "https://openrouter.ai/api/v1/chat/completions"),
    "xai": ("xAI", "openai", "https://api.x.ai/v1/chat/completions"),
    "ollama": ("Ollama", "ollama", "http://127.0.0.1:11434/api/chat"),
    "lmstudio": ("LM Studio", "openai", "http://127.0.0.1:1234/v1/chat/completions"),
}

DEFAULT_PROMPTS = (
    ("summary", "结构化摘要", "请只根据转录内容生成结构化摘要，包含核心结论、关键要点、时间线和待核实事项。"),
    ("cleanup", "文字清理", "清理口语、重复和明显语法问题，但不要改变事实或添加原文没有的信息。"),
    ("faq", "FAQ", "根据内容生成常见问题与简洁答案；答案必须能从原文找到依据。"),
    ("statistics", "数据与事实", "提取出现的数字、日期、指标、人物、组织和可核实事实，按主题分组。"),
    ("mindmap", "思维导图", "将内容整理成 Markdown 层级思维导图，突出主题、分支和关键关系。"),
    ("paraphrase", "改写", "在保持事实和含义不变的前提下，将内容改写得更清晰、简洁。"),
    ("translate", "翻译", "将内容翻译成用户指定的目标语言；保留专有名词、数字和时间信息。"),
)


class AiProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AiProvider:
    id: str
    name: str
    protocol: str
    base_url: str
    model: str = ""
    enabled: bool = True
    custom: bool = False

    def public_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["baseUrl"] = data.pop("base_url")
        return data


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    title: str
    instructions: str
    icon: str = "sparkles"
    builtin: bool = False

    def public_payload(self) -> dict[str, Any]:
        return asdict(self)


def _state_path(engine_module, filename: str) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / filename


def _atomic_json(path: Path, payload: object, *, secret: bool = False) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if secret and os.name != "nt":
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
    temporary.replace(path)
    if secret and os.name != "nt":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _is_loopback_endpoint(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _validated_endpoint(url: object, *, allow_loopback: bool) -> str:
    value = str(url or "").strip()
    try:
        parsed = urlparse(value)
    except ValueError as exc:
        raise AiProviderError("AI Provider URL 无效") from exc
    if parsed.username is not None or parsed.password is not None:
        raise AiProviderError("AI Provider URL 不能包含凭据")
    if allow_loopback and _is_loopback_endpoint(value) and parsed.scheme == "http":
        return value.rstrip("/")
    if parsed.scheme != "https":
        raise AiProviderError("远程 AI Provider 必须使用 HTTPS")
    try:
        return validated_public_http_url(value).rstrip("/")
    except Exception as exc:
        raise AiProviderError("AI Provider 必须是公网 HTTPS 地址") from exc


def _normalize_model(value: object) -> str:
    model = " ".join(str(value or "").split()).strip()
    return model[:160] if MODEL_RE.fullmatch(model) else ""


def _default_provider(provider_id: str) -> AiProvider:
    name, protocol, url = DEFAULT_PROVIDERS[provider_id]
    return AiProvider(provider_id, name, protocol, url, "", True, False)


def load_ai_providers(engine_module) -> list[AiProvider]:
    defaults = {key: _default_provider(key) for key in DEFAULT_PROVIDERS}
    try:
        payload = json.loads(_state_path(engine_module, PROVIDERS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return list(defaults.values())
    custom_rows = payload if isinstance(payload, list) else []
    result = dict(defaults)
    for row in custom_rows[:100]:
        if not isinstance(row, dict):
            continue
        provider_id = str(row.get("id") or "").strip().lower()
        if not PROVIDER_ID_RE.fullmatch(provider_id):
            continue
        base = defaults.get(provider_id)
        protocol = str(row.get("protocol") or (base.protocol if base else "openai")).lower()
        if protocol not in {"openai", "anthropic", "google", "ollama"}:
            continue
        name = " ".join(str(row.get("name") or (base.name if base else provider_id)).split())[:80]
        raw_url = row.get("baseUrl") or (base.base_url if base else "")
        try:
            base_url = _validated_endpoint(raw_url, allow_loopback=provider_id in {"ollama", "lmstudio"} or bool(row.get("allowLocal")))
        except AiProviderError:
            continue
        result[provider_id] = AiProvider(
            id=provider_id,
            name=name or provider_id,
            protocol=protocol,
            base_url=base_url,
            model=_normalize_model(row.get("model")),
            enabled=bool(row.get("enabled", True)),
            custom=provider_id not in defaults,
        )
    return list(result.values())


def save_ai_provider(
    engine_module,
    *,
    provider_id: object,
    name: object,
    protocol: object,
    base_url: object,
    model: object,
    api_key: object = "",
    enabled: bool = True,
    allow_local: bool = False,
) -> AiProvider:
    clean_id = str(provider_id or "").strip().lower()
    if not PROVIDER_ID_RE.fullmatch(clean_id):
        raise AiProviderError("Provider ID 无效")
    clean_protocol = str(protocol or "openai").strip().lower()
    if clean_protocol not in {"openai", "anthropic", "google", "ollama"}:
        raise AiProviderError("Provider 协议无效")
    clean_url = _validated_endpoint(base_url, allow_loopback=allow_local or clean_id in {"ollama", "lmstudio"})
    provider = AiProvider(
        clean_id,
        " ".join(str(name or clean_id).split())[:80],
        clean_protocol,
        clean_url,
        _normalize_model(model),
        bool(enabled),
        clean_id not in DEFAULT_PROVIDERS,
    )
    rows = [item.public_payload() for item in load_ai_providers(engine_module) if item.id != clean_id]
    row = provider.public_payload()
    row["allowLocal"] = bool(allow_local or clean_id in {"ollama", "lmstudio"})
    rows.append(row)
    _atomic_json(_state_path(engine_module, PROVIDERS_FILENAME), rows)
    key = str(api_key or "").strip()
    if key:
        secrets = _load_secrets(engine_module)
        secrets[clean_id] = key[:4096]
        _atomic_json(_state_path(engine_module, SECRETS_FILENAME), secrets, secret=True)
    return provider


def _load_secrets(engine_module) -> dict[str, str]:
    try:
        payload = json.loads(_state_path(engine_module, SECRETS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return {str(key): str(value) for key, value in payload.items() if isinstance(key, str) and isinstance(value, str)} if isinstance(payload, dict) else {}


def provider_has_key(engine_module, provider_id: str) -> bool:
    return bool(_load_secrets(engine_module).get(provider_id))


def delete_provider_key(engine_module, provider_id: object) -> None:
    clean_id = str(provider_id or "").strip().lower()
    secrets = _load_secrets(engine_module)
    secrets.pop(clean_id, None)
    _atomic_json(_state_path(engine_module, SECRETS_FILENAME), secrets, secret=True)


def load_prompt_library(engine_module) -> list[PromptTemplate]:
    defaults = {item[0]: PromptTemplate(item[0], item[1], item[2], "sparkles", True) for item in DEFAULT_PROMPTS}
    try:
        payload = json.loads(_state_path(engine_module, PROMPTS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return list(defaults.values())
    result = dict(defaults)
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, dict):
            continue
        prompt_id = str(row.get("id") or "").strip().lower()
        if not PROVIDER_ID_RE.fullmatch(prompt_id):
            continue
        title = " ".join(str(row.get("title") or prompt_id).split())[:100]
        instructions = str(row.get("instructions") or "").strip()[:20_000]
        if instructions:
            result[prompt_id] = PromptTemplate(prompt_id, title, instructions, str(row.get("icon") or "sparkles")[:40], prompt_id in defaults)
    return list(result.values())


def save_prompt(engine_module, *, prompt_id: object, title: object, instructions: object, icon: object = "sparkles") -> PromptTemplate:
    clean_id = str(prompt_id or "").strip().lower()
    if not PROVIDER_ID_RE.fullmatch(clean_id):
        raise AiProviderError("Prompt ID 无效")
    clean_instructions = str(instructions or "").strip()[:20_000]
    if not clean_instructions:
        raise AiProviderError("Prompt 内容不能为空")
    prompt = PromptTemplate(clean_id, " ".join(str(title or clean_id).split())[:100], clean_instructions, str(icon or "sparkles")[:40], False)
    custom = [item.public_payload() for item in load_prompt_library(engine_module) if not item.builtin and item.id != clean_id]
    custom.append(prompt.public_payload())
    _atomic_json(_state_path(engine_module, PROMPTS_FILENAME), custom)
    return prompt


def restore_default_prompts(engine_module) -> None:
    path = _state_path(engine_module, PROMPTS_FILENAME)
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _bounded_read(response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        block = response.read(min(64 * 1024, MAX_AI_RESPONSE_BYTES - total + 1))
        if not block:
            break
        total += len(block)
        if total > MAX_AI_RESPONSE_BYTES:
            raise AiProviderError("AI 响应超过安全大小限制")
        chunks.append(block)
    return b"".join(chunks)


def _json_request(url: str, payload: dict[str, Any], headers: dict[str, str], *, timeout_seconds: int) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=max(5, min(int(timeout_seconds), 600))) as response:  # noqa: S310 - endpoint validated when provider is saved/loaded
            body = _bounded_read(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        raise AiProviderError(f"AI Provider HTTP {exc.code}: {detail}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise AiProviderError(str(exc)) from exc
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise AiProviderError("AI Provider 返回了无效 JSON") from exc
    if not isinstance(parsed, dict):
        raise AiProviderError("AI Provider 响应格式无效")
    return parsed


def _provider(engine_module, provider_id: object) -> AiProvider:
    clean_id = str(provider_id or "").strip().lower()
    provider = next((item for item in load_ai_providers(engine_module) if item.id == clean_id and item.enabled), None)
    if provider is None:
        raise AiProviderError("AI Provider 不存在或已禁用")
    if not provider.model:
        raise AiProviderError("请先设置 Provider 模型")
    return provider


def run_provider_prompt(
    engine_module,
    provider_id: object,
    instructions: object,
    content: object,
    *,
    timeout_seconds: int = 180,
) -> str:
    provider = _provider(engine_module, provider_id)
    system = str(instructions or "").strip()[:20_000]
    user_content = str(content or "")[:MAX_AI_INPUT_CHARS]
    if not system or not user_content.strip():
        raise AiProviderError("Prompt 或输入内容为空")
    key = _load_secrets(engine_module).get(provider.id, "")

    if provider.protocol == "anthropic":
        if not key:
            raise AiProviderError("该 Provider 尚未保存 API Key")
        payload = {"model": provider.model, "max_tokens": 4096, "system": system, "messages": [{"role": "user", "content": user_content}]}
        result = _json_request(provider.base_url, payload, {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout_seconds=timeout_seconds)
        parts = result.get("content") if isinstance(result.get("content"), list) else []
        text = "\n".join(str(item.get("text") or "") for item in parts if isinstance(item, dict)).strip()
    elif provider.protocol == "google":
        if not key:
            raise AiProviderError("该 Provider 尚未保存 API Key")
        url = f"{provider.base_url}/models/{quote(provider.model, safe='')}:generateContent?key={quote(key, safe='')}"
        result = _json_request(url, {"system_instruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user_content}]}]}, {}, timeout_seconds=timeout_seconds)
        candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
        text = ""
        if candidates and isinstance(candidates[0], dict):
            content_obj = candidates[0].get("content") if isinstance(candidates[0].get("content"), dict) else {}
            parts = content_obj.get("parts") if isinstance(content_obj.get("parts"), list) else []
            text = "\n".join(str(item.get("text") or "") for item in parts if isinstance(item, dict)).strip()
    elif provider.protocol == "ollama":
        result = _json_request(provider.base_url, {"model": provider.model, "stream": False, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}]}, {}, timeout_seconds=timeout_seconds)
        message = result.get("message") if isinstance(result.get("message"), dict) else {}
        text = str(message.get("content") or "").strip()
    else:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        if provider.id not in {"lmstudio"} and not key:
            raise AiProviderError("该 Provider 尚未保存 API Key")
        result = _json_request(provider.base_url, {"model": provider.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}], "temperature": 0.2}, headers, timeout_seconds=timeout_seconds)
        choices = result.get("choices") if isinstance(result.get("choices"), list) else []
        message = choices[0].get("message") if choices and isinstance(choices[0], dict) and isinstance(choices[0].get("message"), dict) else {}
        text = str(message.get("content") or "").strip()

    if not text:
        raise AiProviderError("AI Provider 没有返回文本")
    return text[:1_000_000]


def run_prompt_template(engine_module, provider_id: object, prompt_id: object, content: object, *, extra_instruction: object = "") -> str:
    clean_prompt = str(prompt_id or "").strip().lower()
    prompt = next((item for item in load_prompt_library(engine_module) if item.id == clean_prompt), None)
    if prompt is None:
        raise AiProviderError("Prompt 不存在")
    instructions = prompt.instructions
    extra = str(extra_instruction or "").strip()[:4000]
    if extra:
        instructions += "\n\n额外要求：" + extra
    return run_provider_prompt(engine_module, provider_id, instructions, content)


def test_provider_connection(engine_module, provider_id: object) -> tuple[bool, str]:
    try:
        text = run_provider_prompt(engine_module, provider_id, "只回复 OK。", "connection test", timeout_seconds=30)
    except AiProviderError as exc:
        return False, str(exc)
    return True, text[:200]


def provider_public_status(engine_module) -> list[dict[str, Any]]:
    return [{**item.public_payload(), "hasApiKey": provider_has_key(engine_module, item.id)} for item in load_ai_providers(engine_module)]


def run_ai_provider_manager_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return root / "state"

        providers = load_ai_providers(Engine)
        assert {"openai", "anthropic", "google", "ollama", "lmstudio"}.issubset({item.id for item in providers})
        saved = save_ai_provider(Engine, provider_id="custom", name="Custom", protocol="openai", base_url="https://example.com/v1/chat/completions", model="model-1", api_key="secret")
        assert saved.id == "custom"
        assert provider_has_key(Engine, "custom") is True
        assert "secret" not in json.dumps(provider_public_status(Engine))
        prompts = load_prompt_library(Engine)
        assert {"summary", "faq", "translate"}.issubset({item.id for item in prompts})
        save_prompt(Engine, prompt_id="customprompt", title="Custom", instructions="Do the task")
        assert any(item.id == "customprompt" for item in load_prompt_library(Engine))
