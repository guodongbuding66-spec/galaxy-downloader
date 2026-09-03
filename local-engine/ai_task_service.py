from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_history import (
    AiRunBinding,
    CANCELLED,
    FAILED,
    MAX_TRANSCRIPT_BYTES,
    SUCCEEDED,
    fingerprint_text,
    raw_prompt_fingerprint,
    record_ai_run,
)
from ai_provider_registry import load_ai_providers
from ai_provider_runtime import AiProviderRuntimeError, ProviderRunResult, run_provider_prompt
from ai_task_queue import AiTaskQueue, AiTaskRequest
from ai_workspace import transcript_path
from prompt_library import get_prompt

MAX_SERVICE_HISTORY_LINKS = 200
_MEDIA_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")


class AiTaskServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class _ExecutionContext:
    binding: AiRunBinding


class AiTaskService:
    """Connect the AI queue, Provider runtime and immutable AI History.

    The service captures Prompt and transcript versions before queueing work.
    Worker execution uses that captured Prompt text rather than resolving a
    mutable template again later, so the stored fingerprint always identifies
    the actual instructions sent to the Provider.
    """

    def __init__(
        self,
        engine_module,
        *,
        queue: AiTaskQueue | None = None,
    ) -> None:
        self.engine_module = engine_module
        self.queue = queue or AiTaskQueue()
        self._condition = threading.Condition(threading.RLock())
        self._contexts: dict[str, _ExecutionContext] = {}
        self._history_links: OrderedDict[str, str] = OrderedDict()
        self.queue.start(self._execute)

    def submit_text(
        self,
        *,
        provider_id: object,
        content: object,
        prompt_id: object = "",
        instructions: object = "",
        extra_instruction: object = "",
        label: object = "",
    ) -> dict[str, Any]:
        system, clean_prompt, prompt_hash = self._capture_prompt(
            prompt_id=prompt_id,
            instructions=instructions,
            extra_instruction=extra_instruction,
        )
        binding = AiRunBinding("", "", clean_prompt, prompt_hash)
        return self._submit_captured(
            provider_id=provider_id,
            content=content,
            prompt_id=clean_prompt,
            instructions=system,
            label=label,
            binding=binding,
        )

    def submit_media_transcript(
        self,
        *,
        provider_id: object,
        media_id: object,
        prompt_id: object = "",
        instructions: object = "",
        extra_instruction: object = "",
        label: object = "",
    ) -> dict[str, Any]:
        clean_media, content, transcript_hash = self._transcript_snapshot(media_id)
        system, clean_prompt, prompt_hash = self._capture_prompt(
            prompt_id=prompt_id,
            instructions=instructions,
            extra_instruction=extra_instruction,
        )
        binding = AiRunBinding(clean_media, transcript_hash, clean_prompt, prompt_hash)
        return self._submit_captured(
            provider_id=provider_id,
            content=content,
            prompt_id=clean_prompt,
            instructions=system,
            label=label or clean_prompt or clean_media,
            binding=binding,
        )

    def cancel(self, task_id: object) -> dict[str, Any]:
        task_key = str(task_id or "").strip().lower()
        result = self.queue.cancel(task_key)
        if result.get("state") == CANCELLED:
            with self._condition:
                context = self._contexts.pop(task_key, None)
            status = self.queue.status(task_key)
            if context is not None and status is not None:
                provider_id = str(status.get("providerId") or "")
                run_id = record_ai_run(
                    self.engine_module,
                    provider_id=provider_id,
                    model=self._provider_model(provider_id),
                    status=CANCELLED,
                    binding=context.binding,
                    task_id=task_key,
                    input_chars=0,
                    created_at=status.get("createdAt"),
                    finished_at=status.get("finishedAt"),
                )
                self._remember_history_link(task_key, run_id)
        return self.status(task_key) or result

    def status(self, task_id: object) -> dict[str, Any] | None:
        task_key = str(task_id or "").strip().lower()
        payload = self.queue.status(task_key)
        if payload is None:
            return None
        with self._condition:
            run_id = self._history_links.get(task_key)
        return {**payload, "historyRunId": run_id}

    def snapshot(self) -> dict[str, Any]:
        return self.queue.snapshot()

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        return self.queue.wait_for_idle(timeout)

    def shutdown(self, *, cancel_running: bool = False, timeout: float = 5.0) -> None:
        self.queue.shutdown(cancel_running=cancel_running, timeout=timeout)

    def _submit_captured(
        self,
        *,
        provider_id: object,
        content: object,
        prompt_id: str,
        instructions: str,
        label: object,
        binding: AiRunBinding,
    ) -> dict[str, Any]:
        submitted = self.queue.submit(
            provider_id=provider_id,
            content=content,
            prompt_id=prompt_id,
            instructions=instructions,
            label=label,
        )
        task_id = str(submitted["id"])
        with self._condition:
            self._contexts[task_id] = _ExecutionContext(binding)
            self._condition.notify_all()
        return {**submitted, **binding.public_payload()}

    def _capture_prompt(
        self,
        *,
        prompt_id: object,
        instructions: object,
        extra_instruction: object,
    ) -> tuple[str, str, str]:
        clean_prompt = str(prompt_id or "").strip().lower()
        extra = str(extra_instruction or "").strip()[:4000]
        if clean_prompt:
            prompt = get_prompt(self.engine_module, clean_prompt)
            if prompt is None:
                raise AiTaskServiceError("Prompt 不存在")
            canonical = json.dumps(
                {
                    "id": prompt.id,
                    "title": prompt.title,
                    "instructions": prompt.instructions,
                    "icon": prompt.icon,
                    "builtin": bool(prompt.builtin),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            base_hash = fingerprint_text(canonical)
            effective_hash = (
                fingerprint_text(
                    json.dumps(
                        {"templateHash": base_hash, "extraInstruction": extra},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                if extra
                else base_hash
            )
            system = prompt.instructions
            if extra:
                system += "\n\n额外要求：" + extra
            return system, prompt.id, effective_hash

        system = str(instructions or "").strip()
        if not system:
            raise AiTaskServiceError("Raw AI task 必须提供 instructions")
        prompt_hash = raw_prompt_fingerprint(system, extra_instruction=extra)
        if extra:
            system += "\n\n额外要求：" + extra
        return system, "", prompt_hash

    def _transcript_snapshot(self, media_id: object) -> tuple[str, str, str]:
        clean = str(media_id or "").strip().lower()
        if not _MEDIA_ID_RE.fullmatch(clean):
            raise AiTaskServiceError("媒体条目 ID 无效")
        source = transcript_path(self.engine_module, clean)
        if not source.is_file() or source.is_symlink():
            raise AiTaskServiceError("字幕文件不存在或不是受支持的普通文件")
        try:
            size = source.stat().st_size
            if size <= 0:
                raise AiTaskServiceError("字幕文件为空")
            if size > MAX_TRANSCRIPT_BYTES:
                raise AiTaskServiceError("字幕文件超过 16 MB 上限")
            raw = source.read_bytes()
        except AiTaskServiceError:
            raise
        except OSError as exc:
            raise AiTaskServiceError(str(exc)) from exc
        if len(raw) != size:
            raise AiTaskServiceError("字幕文件在读取过程中发生变化，请重试")
        content = raw.decode("utf-8", errors="replace")
        if not content.strip():
            raise AiTaskServiceError("字幕内容为空")
        return clean, content, hashlib.sha256(raw).hexdigest()

    def _wait_context(self, task_id: str) -> _ExecutionContext:
        deadline = time.monotonic() + 2.0
        with self._condition:
            while task_id not in self._contexts:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AiTaskServiceError("AI Task execution context 不可用")
                self._condition.wait(remaining)
            return self._contexts[task_id]

    def _provider_model(self, provider_id: str) -> str:
        provider = next(
            (
                item
                for item in load_ai_providers(self.engine_module)
                if item.id == provider_id
            ),
            None,
        )
        return str(provider.model if provider is not None else "")

    def _execute(self, request: AiTaskRequest, cancel_event: threading.Event) -> ProviderRunResult | None:
        context = self._wait_context(request.id)
        started = time.monotonic()
        model = self._provider_model(request.provider_id)
        try:
            if cancel_event.is_set():
                self._record_cancelled(request, context, model, started)
                return None
            result = run_provider_prompt(
                self.engine_module,
                request.provider_id,
                request.instructions,
                request.content,
            )
            model = result.model or model
            if cancel_event.is_set():
                self._record_cancelled(request, context, model, started)
                return None
            run_id = record_ai_run(
                self.engine_module,
                provider_id=request.provider_id,
                model=model,
                status=SUCCEEDED,
                binding=context.binding,
                task_id=request.id,
                result_text=result.text,
                input_chars=len(request.content),
                duration_ms=round((time.monotonic() - started) * 1000),
                created_at=request.created_at,
                finished_at=time.time(),
            )
            self._remember_history_link(request.id, run_id)
            return result
        except Exception as exc:
            if cancel_event.is_set():
                self._record_cancelled(request, context, model, started)
                return None
            code = str(getattr(exc, "code", "") or exc.__class__.__name__)
            run_id = record_ai_run(
                self.engine_module,
                provider_id=request.provider_id,
                model=model,
                status=FAILED,
                binding=context.binding,
                task_id=request.id,
                error_code=code,
                error_detail=str(exc),
                input_chars=len(request.content),
                duration_ms=round((time.monotonic() - started) * 1000),
                created_at=request.created_at,
                finished_at=time.time(),
            )
            self._remember_history_link(request.id, run_id)
            raise
        finally:
            with self._condition:
                self._contexts.pop(request.id, None)

    def _record_cancelled(
        self,
        request: AiTaskRequest,
        context: _ExecutionContext,
        model: str,
        started: float,
    ) -> None:
        run_id = record_ai_run(
            self.engine_module,
            provider_id=request.provider_id,
            model=model,
            status=CANCELLED,
            binding=context.binding,
            task_id=request.id,
            input_chars=len(request.content),
            duration_ms=round((time.monotonic() - started) * 1000),
            created_at=request.created_at,
            finished_at=time.time(),
        )
        self._remember_history_link(request.id, run_id)

    def _remember_history_link(self, task_id: str, run_id: str) -> None:
        with self._condition:
            self._history_links.pop(task_id, None)
            self._history_links[task_id] = run_id
            while len(self._history_links) > MAX_SERVICE_HISTORY_LINKS:
                self._history_links.popitem(last=False)


def run_ai_task_service_self_test() -> None:
    import tempfile
    from unittest.mock import patch

    from ai_history import get_ai_run, list_ai_runs
    from ai_provider_registry import save_ai_provider
    from ai_task_queue import AiTaskQueue
    from prompt_library import save_prompt

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        data = root / "data"
        state.mkdir()
        data.mkdir()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return state

            @staticmethod
            def data_dir() -> Path:
                return data

        save_ai_provider(
            Engine,
            provider_id="ollama",
            name="Ollama",
            protocol="ollama",
            base_url="http://127.0.0.1:11434/api/chat",
            model="qwen3:4b",
            allow_local=True,
        )
        save_prompt(
            Engine,
            prompt_id="service-test",
            title="Service Test",
            instructions="Summarize exactly.",
        )
        media_id = "a" * 32
        transcript = transcript_path(Engine, media_id)
        transcript.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nhello service\n",
            encoding="utf-8",
        )

        service = AiTaskService(
            Engine,
            queue=AiTaskQueue(max_waiting=4, concurrency_limit=1),
        )

        def success_runtime(_engine, provider_id, _instructions, content):
            assert provider_id == "ollama"
            assert "hello service" in content
            return ProviderRunResult("ollama", "qwen3:4b", "service result")

        with patch("ai_task_service.run_provider_prompt", side_effect=success_runtime):
            submitted = service.submit_media_transcript(
                provider_id="ollama",
                media_id=media_id,
                prompt_id="service-test",
                extra_instruction="Keep it short",
            )
            assert len(str(submitted["transcriptHash"])) == 64
            assert len(str(submitted["promptHash"])) == 64
            assert service.wait_for_idle(3.0)

        completed = service.status(submitted["id"])
        assert completed is not None and completed["state"] == "succeeded"
        assert completed["historyRunId"]
        history = get_ai_run(Engine, completed["historyRunId"])
        assert history is not None
        assert history["resultText"] == "service result"
        assert history["transcriptHash"] == submitted["transcriptHash"]
        assert history["promptHash"] == submitted["promptHash"]

        def failing_runtime(*_args, **_kwargs):
            raise AiProviderRuntimeError("RATE_LIMIT", "rate limited")

        with patch("ai_task_service.run_provider_prompt", side_effect=failing_runtime):
            failed_task = service.submit_text(
                provider_id="ollama",
                content="plain text",
                instructions="Analyze",
            )
            assert service.wait_for_idle(3.0)
        failed_status = service.status(failed_task["id"])
        assert failed_status is not None and failed_status["state"] == "failed"
        failed_history = get_ai_run(Engine, failed_status["historyRunId"])
        assert failed_history is not None and failed_history["errorCode"] == "RATE_LIMIT"

        first_started = threading.Event()
        release_first = threading.Event()

        def blocking_runtime(_engine, provider_id, _instructions, content):
            if content == "block":
                first_started.set()
                release_first.wait(5.0)
            return ProviderRunResult(provider_id, "qwen3:4b", "ok")

        with patch("ai_task_service.run_provider_prompt", side_effect=blocking_runtime):
            first = service.submit_text(
                provider_id="ollama",
                content="block",
                instructions="Do it",
            )
            assert first_started.wait(2.0)
            queued = service.submit_text(
                provider_id="ollama",
                content="cancel me",
                instructions="Do it",
            )
            cancelled = service.cancel(queued["id"])
            assert cancelled["state"] == "cancelled"
            assert cancelled["historyRunId"]
            cancelled_history = get_ai_run(Engine, cancelled["historyRunId"])
            assert cancelled_history is not None and cancelled_history["status"] == "cancelled"
            release_first.set()
            assert service.wait_for_idle(3.0)
            assert service.status(first["id"])["state"] == "succeeded"

        assert len(list_ai_runs(Engine)) == 4
        assert "hello service" not in repr(service.snapshot())
        service.shutdown(timeout=1.0)
