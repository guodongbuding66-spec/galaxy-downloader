from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ai_history import (
    AiHistoryError,
    clear_ai_history,
    delete_ai_run,
    get_ai_run,
    list_ai_runs,
)
from ai_provider_registry import (
    AiProviderConfigError,
    delete_ai_provider,
    provider_public_status,
    reset_ai_provider,
    save_ai_provider,
)
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

_TASK_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_RUN_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_PROMPT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")


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


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def _clean_id(value: object, pattern: re.Pattern[str], label: str, code: str) -> str:
    clean = str(value or "").strip().lower()
    if not pattern.fullmatch(clean):
        raise HeadlessAiApiError(f"invalid {label} id", code=code)
    return clean


def _safe_directory(value: Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    if raw.exists() and raw.is_symlink():
        raise HeadlessAiApiError(f"{label} cannot be a symbolic link")
    resolved = raw.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _translate_error(exc: Exception) -> HeadlessAiApiError:
    if isinstance(exc, HeadlessAiApiError):
        return exc
    detail = str(exc).strip()
    if isinstance(exc, AiQueueFullError):
        return HeadlessAiConflictError("AI queue is full", code="AI_QUEUE_FULL")
    if detail in {"Prompt 不存在", "源 Prompt 不存在"}:
        return HeadlessAiNotFoundError("prompt not found", code="AI_PROMPT_NOT_FOUND")
    if detail in {"AI Task ID 无效"}:
        return HeadlessAiApiError("invalid task id", code="AI_INVALID_TASK_ID")
    if detail in {"媒体条目 ID 无效"}:
        return HeadlessAiApiError("invalid media id", code="AI_INVALID_MEDIA_ID")
    if "已存在" in detail:
        return HeadlessAiConflictError("AI resource already exists", code="AI_RESOURCE_EXISTS")
    if isinstance(exc, (AiProviderConfigError, PromptLibraryError, AiHistoryError, AiQueueError, AiTaskServiceError)):
        return HeadlessAiApiError(detail or "AI operation failed")
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
            self.service.shutdown(cancel_running=True, timeout=2.0)

    # Provider registry -------------------------------------------------
    def providers(self) -> dict[str, Any]:
        try:
            rows = provider_public_status(self.context)
        except Exception as exc:
            raise _translate_error(exc) from exc
        return {"providers": rows, "count": len(rows)}

    def save_provider(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            provider = save_ai_provider(
                self.context,
                provider_id=payload.get("id", payload.get("providerId")),
                name=payload.get("name", ""),
                protocol=payload.get("protocol", ""),
                base_url=payload.get("baseUrl", ""),
                model=payload.get("model", ""),
                enabled=bool(payload.get("enabled", True)),
                allow_local=bool(payload.get("allowLocal", False)),
                timeout_seconds=payload.get("timeoutSeconds", 180),
                credential_reference=payload.get("credentialReference", ""),
            )
            rows = provider_public_status(self.context)
        except Exception as exc:
            raise _translate_error(exc) from exc
        rendered = next((row for row in rows if row.get("id") == provider.id), provider.public_payload())
        return {"provider": rendered}

    def reset_provider(self, provider_id: object) -> dict[str, Any]:
        clean = _clean_id(provider_id, _PROVIDER_ID_RE, "provider", "AI_INVALID_PROVIDER_ID")
        try:
            reset_ai_provider(self.context, clean)
            rows = provider_public_status(self.context)
        except Exception as exc:
            raise _translate_error(exc) from exc
        rendered = next((row for row in rows if row.get("id") == clean), None)
        if rendered is None:
            raise HeadlessAiNotFoundError("provider not found", code="AI_PROVIDER_NOT_FOUND")
        return {"provider": rendered}

    def remove_provider(self, provider_id: object) -> dict[str, Any]:
        clean = _clean_id(provider_id, _PROVIDER_ID_RE, "provider", "AI_INVALID_PROVIDER_ID")
        try:
            deleted = delete_ai_provider(self.context, clean)
        except Exception as exc:
            raise _translate_error(exc) from exc
        if not deleted:
            raise HeadlessAiNotFoundError("provider not found", code="AI_PROVIDER_NOT_FOUND")
        return {"providerId": clean, "deleted": True}

    # Prompt library ----------------------------------------------------
    def prompts(self) -> dict[str, Any]:
        try:
            rows = [item.public_payload() for item in load_prompt_library(self.context)]
        except Exception as exc:
            raise _translate_error(exc) from exc
        return {"prompts": rows, "count": len(rows)}

    def prompt_detail(self, prompt_id: object) -> dict[str, Any]:
        clean = _clean_id(prompt_id, _PROMPT_ID_RE, "prompt", "AI_INVALID_PROMPT_ID")
        try:
            prompt = get_prompt(self.context, clean)
        except Exception as exc:
            raise _translate_error(exc) from exc
        if prompt is None:
            raise HeadlessAiNotFoundError("prompt not found", code="AI_PROMPT_NOT_FOUND")
        return {"prompt": prompt.public_payload()}

    def save_prompt(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            prompt = save_prompt(
                self.context,
                prompt_id=payload.get("id", payload.get("promptId")),
                title=payload.get("title", ""),
                instructions=payload.get("instructions", ""),
                icon=payload.get("icon", "sparkles"),
            )
        except Exception as exc:
            raise _translate_error(exc) from exc
        return {"prompt": prompt.public_payload()}

    def duplicate_prompt(self, prompt_id: object, payload: Mapping[str, Any]) -> dict[str, Any]:
        clean = _clean_id(prompt_id, _PROMPT_ID_RE, "prompt", "AI_INVALID_PROMPT_ID")
        try:
            prompt = duplicate_prompt(
                self.context,
                clean,
                new_id=payload.get("id", payload.get("newId", "")),
                title=payload.get("title", ""),
            )
        except Exception as exc:
            raise _translate_error(exc) from exc
        return {"prompt": prompt.public_payload()}

    def remove_prompt(self, prompt_id: object) -> dict[str, Any]:
        clean = _clean_id(prompt_id, _PROMPT_ID_RE, "prompt", "AI_INVALID_PROMPT_ID")
        try:
            existed = get_prompt(self.context, clean) is not None
            deleted = delete_prompt(self.context, clean)
        except Exception as exc:
            raise _translate_error(exc) from exc
        if not existed:
            raise HeadlessAiNotFoundError("prompt not found", code="AI_PROMPT_NOT_FOUND")
        return {"promptId": clean, "deleted": bool(deleted), "restoredDefault": bool(existed and not deleted)}

    def restore_prompts(self) -> dict[str, Any]:
        try:
            restore_default_prompts(self.context)
            rows = [item.public_payload() for item in load_prompt_library(self.context)]
        except Exception as exc:
            raise _translate_error(exc) from exc
        return {"prompts": rows, "count": len(rows)}

    # Queue / task service ---------------------------------------------
    def queue(self) -> dict[str, Any]:
        try:
            return self.service.snapshot()
        except Exception as exc:
            raise _translate_error(exc) from exc

    def task_detail(self, task_id: object) -> dict[str, Any]:
        clean = _clean_id(task_id, _TASK_ID_RE, "task", "AI_INVALID_TASK_ID")
        try:
            task = self.service.status(clean)
        except Exception as exc:
            raise _translate_error(exc) from exc
        if task is None:
            raise HeadlessAiNotFoundError("task not found", code="AI_TASK_NOT_FOUND")
        return {"task": task}

    def submit_text(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            task = self.service.submit_text(
                provider_id=payload.get("providerId"),
                content=payload.get("content"),
                prompt_id=payload.get("promptId", ""),
                instructions=payload.get("instructions", ""),
                extra_instruction=payload.get("extraInstruction", ""),
                label=payload.get("label", ""),
            )
        except Exception as exc:
            raise _translate_error(exc) from exc
        return {"task": task}

    def submit_transcript(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        media_id = _clean_id(payload.get("mediaId"), _MEDIA_ID_RE, "media", "AI_INVALID_MEDIA_ID")
        try:
            task = self.service.submit_media_transcript(
                provider_id=payload.get("providerId"),
                media_id=media_id,
                prompt_id=payload.get("promptId", ""),
                instructions=payload.get("instructions", ""),
                extra_instruction=payload.get("extraInstruction", ""),
                label=payload.get("label", ""),
            )
        except Exception as exc:
            raise _translate_error(exc) from exc
        return {"task": task}

    def cancel_task(self, task_id: object) -> dict[str, Any]:
        clean = _clean_id(task_id, _TASK_ID_RE, "task", "AI_INVALID_TASK_ID")
        try:
            result = self.service.cancel(clean)
        except Exception as exc:
            raise _translate_error(exc) from exc
        if result.get("code") == "AI_TASK_NOT_FOUND":
            raise HeadlessAiNotFoundError("task not found", code="AI_TASK_NOT_FOUND")
        return {"task": result}

    # Immutable history -------------------------------------------------
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
        except Exception as exc:
            raise _translate_error(exc) from exc
        return {"runs": rows, "limit": safe_limit}

    def history_detail(self, run_id: object) -> dict[str, Any]:
        clean = _clean_id(run_id, _RUN_ID_RE, "history run", "AI_INVALID_HISTORY_ID")
        try:
            run = get_ai_run(self.context, clean)
        except Exception as exc:
            raise _translate_error(exc) from exc
        if run is None:
            raise HeadlessAiNotFoundError("history run not found", code="AI_HISTORY_NOT_FOUND")
        return {"run": run}

    def remove_history(self, run_id: object) -> dict[str, Any]:
        clean = _clean_id(run_id, _RUN_ID_RE, "history run", "AI_INVALID_HISTORY_ID")
        try:
            deleted = delete_ai_run(self.context, clean)
        except Exception as exc:
            raise _translate_error(exc) from exc
        if not deleted:
            raise HeadlessAiNotFoundError("history run not found", code="AI_HISTORY_NOT_FOUND")
        return {"runId": clean, "deleted": True}

    def clear_history(self) -> dict[str, Any]:
        try:
            count = clear_ai_history(self.context)
        except Exception as exc:
            raise _translate_error(exc) from exc
        return {"deleted": count}


def run_headless_ai_api_self_test() -> None:
    import tempfile

    class FakeService:
        def __init__(self) -> None:
            self.tasks: dict[str, dict[str, Any]] = {}

        def snapshot(self) -> dict[str, Any]:
            return {"waitingCount": 0, "activeCount": 0, "active": [], "waiting": []}

        def status(self, task_id: object) -> dict[str, Any] | None:
            return self.tasks.get(str(task_id))

        def submit_text(self, **_kwargs: Any) -> dict[str, Any]:
            task_id = "a" * 32
            task = {"id": task_id, "state": "queued", "accepted": True, "position": 1}
            self.tasks[task_id] = task
            return task

        def submit_media_transcript(self, **_kwargs: Any) -> dict[str, Any]:
            return self.submit_text()

        def cancel(self, task_id: object) -> dict[str, Any]:
            task = self.tasks.get(str(task_id))
            if task is None:
                return {"cancelled": False, "code": "AI_TASK_NOT_FOUND"}
            task = {**task, "state": "cancelled", "cancelled": True}
            self.tasks[str(task_id)] = task
            return task

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        program = root / "program"
        data = root / "data"
        state = root / "state"
        downloads = root / "downloads"
        for target in (program, data, state, downloads):
            target.mkdir()
        context = HeadlessAiContext(program, data, state, downloads)
        api = HeadlessAiApi(downloads, context=context, service=FakeService())  # type: ignore[arg-type]

        providers = api.providers()
        assert providers["count"] >= 8
        assert all("apiKey" not in row for row in providers["providers"])

        saved_provider = api.save_provider(
            {
                "id": "local-test",
                "name": "Local Test",
                "protocol": "openai",
                "baseUrl": "http://127.0.0.1:9999/v1/chat/completions",
                "allowLocal": True,
                "model": "test-model",
            }
        )
        assert saved_provider["provider"]["id"] == "local-test"
        assert api.remove_provider("local-test")["deleted"] is True

        defaults = api.prompts()
        assert defaults["count"] >= 8
        custom = api.save_prompt(
            {"id": "headless-test", "title": "Headless", "instructions": "Summarize exactly."}
        )
        assert custom["prompt"]["id"] == "headless-test"
        copied = api.duplicate_prompt("headless-test", {"id": "headless-copy"})
        assert copied["prompt"]["id"] == "headless-copy"
        assert api.remove_prompt("headless-copy")["deleted"] is True

        queued = api.submit_text(
            {"providerId": "openai", "content": "hello", "promptId": "summary"}
        )
        task_id = queued["task"]["id"]
        assert api.task_detail(task_id)["task"]["state"] == "queued"
        assert api.cancel_task(task_id)["task"]["state"] == "cancelled"
        assert api.queue()["waitingCount"] == 0

        try:
            api.task_detail("bad")
        except HeadlessAiApiError:
            pass
        else:
            raise AssertionError("invalid task id was accepted")
