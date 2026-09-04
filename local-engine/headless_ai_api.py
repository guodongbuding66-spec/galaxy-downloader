from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ai_history import AiHistoryError, clear_ai_history, delete_ai_run, get_ai_run, list_ai_runs
from ai_provider_registry import (
    AiProviderConfigError,
    delete_ai_provider,
    load_ai_providers,
    provider_has_api_key,
    save_ai_provider,
    reset_ai_provider,
)
from ai_provider_runtime import test_provider_connection
from ai_task_queue import AiQueueError, AiQueueFullError
from ai_task_service import AiTaskService, AiTaskServiceError
from platform_paths import resolve_platform_paths
from prompt_library import (
    PromptLibraryError,
    delete_prompt,
    duplicate_prompt,
    get_prompt,
    load_prompt_library,
    restore_default_prompts,
    save_prompt,
)

_SYMBOLIC_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_OBJECT_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
_FORBIDDEN_SECRET_FIELDS = frozenset({"apikey", "api_key", "token", "secret", "password", "credential"})


class HeadlessAiApiError(RuntimeError):
    status = 400
    code = "AI_INVALID_REQUEST"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class HeadlessAiNotFoundError(HeadlessAiApiError):
    status = 404
    code = "AI_NOT_FOUND"


class HeadlessAiConflictError(HeadlessAiApiError):
    status = 409
    code = "AI_CONFLICT"


def _safe_directory(value: Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    if raw.exists() and raw.is_symlink():
        raise HeadlessAiApiError(f"{label} cannot be a symbolic link")
    resolved = raw.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _clean_symbolic_id(value: object, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not _SYMBOLIC_ID_RE.fullmatch(clean):
        raise HeadlessAiApiError(f"invalid {label} id", code=f"AI_INVALID_{label.upper()}_ID")
    return clean


def _clean_object_id(value: object, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not _OBJECT_ID_RE.fullmatch(clean):
        raise HeadlessAiApiError(f"invalid {label} id", code=f"AI_INVALID_{label.upper()}_ID")
    return clean


def _clean_media_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _MEDIA_ID_RE.fullmatch(clean):
        raise HeadlessAiApiError("invalid media id", code="AI_INVALID_MEDIA_ID")
    return clean


def _strict_bool(value: object, *, label: str) -> bool:
    if isinstance(value, bool):
        return value
    raise HeadlessAiApiError(f"{label} must be a boolean")


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def _reject_secret_fields(payload: Mapping[str, Any]) -> None:
    for key in payload:
        normalized = str(key).replace("-", "_").lower()
        if normalized in _FORBIDDEN_SECRET_FIELDS:
            raise HeadlessAiApiError(
                "raw AI credentials are not accepted; use credentialReference=env:VARIABLE_NAME",
                code="AI_RAW_CREDENTIAL_REJECTED",
            )


def _public_provider(engine_module, provider) -> dict[str, Any]:
    payload = provider.public_payload(has_credential=provider_has_api_key(engine_module, provider.id))
    payload.pop("credentialReference", None)
    return payload


def _translate_error(exc: Exception) -> HeadlessAiApiError:
    detail = str(exc).strip()
    if isinstance(exc, AiQueueFullError):
        return HeadlessAiConflictError("AI queue is full", code="AI_QUEUE_FULL")
    if detail in {"Prompt 不存在", "源 Prompt 不存在"}:
        return HeadlessAiNotFoundError("prompt not found", code="AI_PROMPT_NOT_FOUND")
    if "Prompt ID 已存在" in detail:
        return HeadlessAiConflictError("prompt id already exists", code="AI_PROMPT_EXISTS")
    if "AI Provider 不存在" in detail:
        return HeadlessAiNotFoundError("provider not found", code="AI_PROVIDER_NOT_FOUND")
    if "数量超过安全上限" in detail:
        return HeadlessAiConflictError("AI resource limit reached", code="AI_LIMIT_REACHED")
    return HeadlessAiApiError(detail or "AI operation failed")


@dataclass(frozen=True)
class HeadlessAiContext:
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


def build_headless_ai_context(
    download_root: Path,
    *,
    program_dir: Path | None = None,
    data_dir: Path | None = None,
    state_dir: Path | None = None,
) -> HeadlessAiContext:
    program = Path(program_dir or Path(__file__).resolve().parent).expanduser().resolve(strict=False)
    paths = resolve_platform_paths(program_dir=program)
    data = _safe_directory(Path(data_dir or paths.data_dir), label="AI data directory")
    state = _safe_directory(Path(state_dir or paths.state_dir), label="AI state directory")
    downloads = _safe_directory(Path(download_root), label="AI download root")
    return HeadlessAiContext(program, data, state, downloads)


class HeadlessAiApi:
    def __init__(
        self,
        download_root: Path,
        *,
        context: HeadlessAiContext | None = None,
        service: AiTaskService | None = None,
        program_dir: Path | None = None,
        data_dir: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.context = context or build_headless_ai_context(
            download_root,
            program_dir=program_dir,
            data_dir=data_dir,
            state_dir=state_dir,
        )
        self.service = service or AiTaskService(self.context)
        self._owns_service = service is None

    def shutdown(self) -> None:
        if self._owns_service:
            self.service.shutdown(cancel_running=True, timeout=5.0)

    # Providers
    def providers(self) -> dict[str, Any]:
        try:
            rows = load_ai_providers(self.context)
        except AiProviderConfigError as exc:
            raise _translate_error(exc) from exc
        return {"providers": [_public_provider(self.context, item) for item in rows]}

    def provider_detail(self, provider_id: object) -> dict[str, Any]:
        clean = _clean_symbolic_id(provider_id, "provider")
        try:
            provider = next((item for item in load_ai_providers(self.context) if item.id == clean), None)
        except AiProviderConfigError as exc:
            raise _translate_error(exc) from exc
        if provider is None:
            raise HeadlessAiNotFoundError("provider not found", code="AI_PROVIDER_NOT_FOUND")
        return {"provider": _public_provider(self.context, provider)}

    def save_provider(self, payload: Mapping[str, Any], *, provider_id: object = "") -> dict[str, Any]:
        _reject_secret_fields(payload)
        clean_id = _clean_symbolic_id(provider_id or payload.get("id"), "provider")
        enabled = _strict_bool(payload.get("enabled"), label="enabled") if "enabled" in payload else True
        allow_local = _strict_bool(payload.get("allowLocal"), label="allowLocal") if "allowLocal" in payload else False
        try:
            provider = save_ai_provider(
                self.context,
                provider_id=clean_id,
                name=payload.get("name", clean_id),
                protocol=payload.get("protocol", "openai"),
                base_url=payload.get("baseUrl", ""),
                model=payload.get("model", ""),
                enabled=enabled,
                allow_local=allow_local,
                timeout_seconds=payload.get("timeoutSeconds", 180),
                credential_reference=payload.get("credentialReference", ""),
            )
        except AiProviderConfigError as exc:
            raise _translate_error(exc) from exc
        return {"provider": _public_provider(self.context, provider)}

    def reset_provider(self, provider_id: object) -> dict[str, Any]:
        clean = _clean_symbolic_id(provider_id, "provider")
        try:
            provider = reset_ai_provider(self.context, clean)
        except AiProviderConfigError as exc:
            raise _translate_error(exc) from exc
        return {"provider": _public_provider(self.context, provider)}

    def remove_provider(self, provider_id: object) -> dict[str, Any]:
        clean = _clean_symbolic_id(provider_id, "provider")
        try:
            deleted = delete_ai_provider(self.context, clean)
        except AiProviderConfigError as exc:
            raise _translate_error(exc) from exc
        if not deleted:
            raise HeadlessAiNotFoundError("provider not found", code="AI_PROVIDER_NOT_FOUND")
        return {"providerId": clean, "deleted": True}

    def test_provider(self, provider_id: object) -> dict[str, Any]:
        clean = _clean_symbolic_id(provider_id, "provider")
        self.provider_detail(clean)
        result = test_provider_connection(self.context, clean)
        return {"providerId": clean, "test": result}

    # Prompt library
    def prompts(self) -> dict[str, Any]:
        try:
            rows = load_prompt_library(self.context)
        except PromptLibraryError as exc:
            raise _translate_error(exc) from exc
        return {"prompts": [item.public_payload() for item in rows]}

    def prompt_detail(self, prompt_id: object) -> dict[str, Any]:
        clean = _clean_symbolic_id(prompt_id, "prompt")
        try:
            prompt = get_prompt(self.context, clean)
        except PromptLibraryError as exc:
            raise _translate_error(exc) from exc
        if prompt is None:
            raise HeadlessAiNotFoundError("prompt not found", code="AI_PROMPT_NOT_FOUND")
        return {"prompt": prompt.public_payload()}

    def save_prompt(self, payload: Mapping[str, Any], *, prompt_id: object = "") -> dict[str, Any]:
        clean = _clean_symbolic_id(prompt_id or payload.get("id"), "prompt")
        try:
            prompt = save_prompt(
                self.context,
                prompt_id=clean,
                title=payload.get("title", clean),
                instructions=payload.get("instructions"),
                icon=payload.get("icon", "sparkles"),
            )
        except PromptLibraryError as exc:
            raise _translate_error(exc) from exc
        return {"prompt": prompt.public_payload()}

    def duplicate_prompt(self, prompt_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        clean = _clean_symbolic_id(prompt_id, "prompt")
        try:
            prompt = duplicate_prompt(
                self.context,
                clean,
                new_id=payload.get("id", payload.get("newId", "")),
                title=payload.get("title", ""),
            )
        except PromptLibraryError as exc:
            raise _translate_error(exc) from exc
        return {"prompt": prompt.public_payload()}

    def remove_prompt(self, prompt_id: object) -> dict[str, Any]:
        clean = _clean_symbolic_id(prompt_id, "prompt")
        try:
            existed = get_prompt(self.context, clean)
            if existed is None:
                raise HeadlessAiNotFoundError("prompt not found", code="AI_PROMPT_NOT_FOUND")
            deleted = delete_prompt(self.context, clean)
        except HeadlessAiApiError:
            raise
        except PromptLibraryError as exc:
            raise _translate_error(exc) from exc
        # Built-ins that were never overridden cannot be removed; deleting an override resets it.
        return {"promptId": clean, "deleted": bool(deleted), "builtin": bool(existed.builtin)}

    def reset_prompts(self) -> dict[str, Any]:
        restore_default_prompts(self.context)
        return self.prompts()

    # Tasks
    def tasks(self) -> dict[str, Any]:
        return self.service.snapshot()

    def task_detail(self, task_id: object) -> dict[str, Any]:
        clean = _clean_object_id(task_id, "task")
        result = self.service.status(clean)
        if result is None:
            raise HeadlessAiNotFoundError("task not found", code="AI_TASK_NOT_FOUND")
        return {"task": result}

    def submit_text(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        provider_id = _clean_symbolic_id(payload.get("providerId"), "provider")
        self._require_runnable_provider(provider_id)
        try:
            result = self.service.submit_text(
                provider_id=provider_id,
                content=payload.get("content"),
                prompt_id=payload.get("promptId", ""),
                instructions=payload.get("instructions", ""),
                extra_instruction=payload.get("extraInstruction", ""),
                label=payload.get("label", ""),
            )
        except (AiTaskServiceError, AiQueueError) as exc:
            raise _translate_error(exc) from exc
        return {"task": result}

    def submit_transcript(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        provider_id = _clean_symbolic_id(payload.get("providerId"), "provider")
        media_id = _clean_media_id(payload.get("mediaId"))
        self._require_runnable_provider(provider_id)
        try:
            result = self.service.submit_media_transcript(
                provider_id=provider_id,
                media_id=media_id,
                prompt_id=payload.get("promptId", ""),
                instructions=payload.get("instructions", ""),
                extra_instruction=payload.get("extraInstruction", ""),
                label=payload.get("label", ""),
            )
        except (AiTaskServiceError, AiQueueError) as exc:
            raise _translate_error(exc) from exc
        return {"task": result}

    def cancel_task(self, task_id: object) -> dict[str, Any]:
        clean = _clean_object_id(task_id, "task")
        if self.service.status(clean) is None:
            raise HeadlessAiNotFoundError("task not found", code="AI_TASK_NOT_FOUND")
        try:
            result = self.service.cancel(clean)
        except (AiTaskServiceError, AiQueueError) as exc:
            raise _translate_error(exc) from exc
        return {"task": result}

    def clear_waiting(self) -> dict[str, Any]:
        count = self.service.queue.clear_waiting()
        return {"cleared": count, **self.service.snapshot()}

    # History
    def history(
        self,
        *,
        media_id: object = "",
        provider_id: object = "",
        status: object = "",
        limit: object = 50,
    ) -> dict[str, Any]:
        safe_limit = _bounded_int(limit, 50, 1, 200)
        try:
            rows = list_ai_runs(
                self.context,
                media_id=media_id,
                provider_id=provider_id,
                status=status,
                limit=safe_limit,
            )
        except AiHistoryError as exc:
            raise _translate_error(exc) from exc
        return {"history": rows, "limit": safe_limit}

    def history_detail(self, run_id: object) -> dict[str, Any]:
        clean = _clean_object_id(run_id, "history")
        try:
            result = get_ai_run(self.context, clean)
        except AiHistoryError as exc:
            raise _translate_error(exc) from exc
        if result is None:
            raise HeadlessAiNotFoundError("history run not found", code="AI_HISTORY_NOT_FOUND")
        return {"run": result}

    def remove_history(self, run_id: object) -> dict[str, Any]:
        clean = _clean_object_id(run_id, "history")
        try:
            deleted = delete_ai_run(self.context, clean)
        except AiHistoryError as exc:
            raise _translate_error(exc) from exc
        if not deleted:
            raise HeadlessAiNotFoundError("history run not found", code="AI_HISTORY_NOT_FOUND")
        return {"runId": clean, "deleted": True}

    def clear_history(self) -> dict[str, Any]:
        try:
            count = clear_ai_history(self.context)
        except AiHistoryError as exc:
            raise _translate_error(exc) from exc
        return {"cleared": count}

    def _require_runnable_provider(self, provider_id: str) -> None:
        try:
            provider = next((item for item in load_ai_providers(self.context) if item.id == provider_id), None)
        except AiProviderConfigError as exc:
            raise _translate_error(exc) from exc
        if provider is None:
            raise HeadlessAiNotFoundError("provider not found", code="AI_PROVIDER_NOT_FOUND")
        if not provider.enabled:
            raise HeadlessAiConflictError("provider is disabled", code="AI_PROVIDER_DISABLED")
        if not provider.base_url:
            raise HeadlessAiConflictError("provider base URL is not configured", code="AI_PROVIDER_NOT_CONFIGURED")
        if not provider.model:
            raise HeadlessAiConflictError("provider model is not configured", code="AI_PROVIDER_MODEL_REQUIRED")


def run_headless_ai_api_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    from ai_provider_runtime import ProviderRunResult
    from ai_workspace import transcript_path

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        program = root / "program"
        data = root / "data"
        state = root / "state"
        downloads = root / "downloads"
        for target in (program, data, state, downloads):
            target.mkdir()
        context = HeadlessAiContext(program, data, state, downloads)
        api = HeadlessAiApi(downloads, context=context)
        try:
            providers = api.providers()["providers"]
            assert providers and all("credentialReference" not in item for item in providers)
            try:
                api.save_provider({
                    "id": "bad-secret",
                    "name": "Bad",
                    "protocol": "openai",
                    "baseUrl": "https://example.com/v1/chat/completions",
                    "apiKey": "must-not-be-accepted",
                })
            except HeadlessAiApiError as exc:
                assert exc.code == "AI_RAW_CREDENTIAL_REJECTED"
            else:
                raise AssertionError("raw provider credential was accepted")

            saved = api.save_provider({
                "id": "local-test",
                "name": "Local Test",
                "protocol": "ollama",
                "baseUrl": "http://127.0.0.1:11434/api/chat",
                "model": "qwen3:4b",
                "allowLocal": True,
                "credentialReference": "",
            })["provider"]
            assert saved["id"] == "local-test" and "credentialReference" not in saved

            prompt = api.save_prompt({
                "id": "headless-test",
                "title": "Headless Test",
                "instructions": "Summarize exactly.",
            })["prompt"]
            assert api.prompt_detail(prompt["id"])["prompt"]["title"] == "Headless Test"
            copy = api.duplicate_prompt(prompt["id"], {"id": "headless-test-copy"})["prompt"]
            assert copy["id"] == "headless-test-copy"

            media_id = "a" * 32
            transcript_path(context, media_id).write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nhello headless AI\n",
                encoding="utf-8",
            )

            def fake_runtime(_engine, provider_id, _instructions, content):
                assert provider_id == "local-test"
                return ProviderRunResult(provider_id, "qwen3:4b", "result: " + content[:40])

            with patch("ai_task_service.run_provider_prompt", side_effect=fake_runtime):
                text_task = api.submit_text({
                    "providerId": "local-test",
                    "content": "plain input",
                    "promptId": prompt["id"],
                })["task"]
                transcript_task = api.submit_transcript({
                    "providerId": "local-test",
                    "mediaId": media_id,
                    "promptId": prompt["id"],
                })["task"]
                assert api.service.wait_for_idle(3.0)

            text_status = api.task_detail(text_task["id"])["task"]
            transcript_status = api.task_detail(transcript_task["id"])["task"]
            assert text_status["state"] == "succeeded" and text_status["historyRunId"]
            assert transcript_status["state"] == "succeeded" and transcript_status["historyRunId"]
            history = api.history(limit=10)["history"]
            assert len(history) == 2 and all("resultText" not in item for item in history)
            full = api.history_detail(text_status["historyRunId"])["run"]
            assert str(full["resultText"]).startswith("result:")
            assert api.remove_history(text_status["historyRunId"])["deleted"] is True
            assert api.clear_history()["cleared"] == 1

            assert api.remove_prompt(copy["id"])["deleted"] is True
            assert api.remove_provider("local-test")["deleted"] is True
        finally:
            api.shutdown()
