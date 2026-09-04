from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_ai_api import HeadlessAiApi, HeadlessAiContext  # noqa: E402
from headless_ai_http import AiGalaxyApiServer  # noqa: E402
from headless_media_api import HeadlessMediaApi, HeadlessMediaContext  # noqa: E402
from headless_service import HeadlessRuntime  # noqa: E402


class FakeAiService:
    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}

    def snapshot(self) -> dict:
        return {
            "waitingCount": 0,
            "activeCount": 0,
            "concurrencyLimit": 1,
            "queueCapacity": 50,
            "active": [],
            "waiting": [],
        }

    def status(self, task_id: object) -> dict | None:
        return self.tasks.get(str(task_id))

    def submit_text(self, **_kwargs) -> dict:
        task_id = "a" * 32
        task = {"id": task_id, "state": "queued", "accepted": True, "position": 1}
        self.tasks[task_id] = task
        return task

    def submit_media_transcript(self, **_kwargs) -> dict:
        task_id = "b" * 32
        task = {"id": task_id, "state": "queued", "accepted": True, "position": 1}
        self.tasks[task_id] = task
        return task

    def cancel(self, task_id: object) -> dict:
        key = str(task_id)
        task = self.tasks.get(key)
        if task is None:
            return {"cancelled": False, "code": "AI_TASK_NOT_FOUND"}
        task = {**task, "state": "cancelled", "cancelled": True, "code": "AI_TASK_CANCELLED"}
        self.tasks[key] = task
        return task


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str = "",
) -> tuple[int, dict]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, method=method, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=4) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _http_error_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str = "",
) -> tuple[int, dict]:
    try:
        _request_json(url, method=method, payload=payload, token=token)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    raise AssertionError(f"expected HTTP error for {method} {url}")


def _assert_public(payload: dict, *, roots: tuple[Path, ...], secret: str) -> None:
    rendered = json.dumps(payload, ensure_ascii=False)
    assert secret not in rendered
    assert '"apiKey"' not in rendered
    for root in roots:
        assert str(root) not in rendered


def run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        program = root / "program"
        state = root / "state"
        data = root / "data"
        downloads = root / "downloads"
        for target in (program, state, data, downloads):
            target.mkdir()

        media_context = HeadlessMediaContext(program, state, downloads)
        media_api = HeadlessMediaApi(downloads, context=media_context)
        ai_context = HeadlessAiContext(program, data, state, downloads)
        fake_service = FakeAiService()
        ai_api = HeadlessAiApi(downloads, context=ai_context, service=fake_service)  # type: ignore[arg-type]
        runtime = HeadlessRuntime(downloads, max_queue_size=2)
        token = "headless-ai-http-token-1234567890"
        secret = "must-never-leak-secret"

        previous = os.environ.get("HTTP_AI_KEY")
        os.environ["HTTP_AI_KEY"] = secret
        server = AiGalaxyApiServer(
            ("127.0.0.1", 0),
            runtime,
            token,
            "127.0.0.1",
            media_api,
            ai_api=ai_api,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"

            code, unauthorized = _http_error_json(base + "/v1/ai/providers")
            assert code == 401 and unauthorized["ok"] is False

            code, status = _request_json(base + "/v1/status", token=token)
            assert code == 200 and status["ok"] is True and status["protocol"] == 2

            code, providers = _request_json(base + "/v1/ai/providers", token=token)
            assert code == 200 and providers["count"] >= 8
            _assert_public(providers, roots=(state, data, downloads), secret=secret)

            code, provider = _request_json(
                base + "/v1/ai/providers",
                method="POST",
                token=token,
                payload={
                    "id": "http-local",
                    "name": "HTTP Local",
                    "protocol": "openai",
                    "baseUrl": "http://127.0.0.1:9999/v1/chat/completions",
                    "model": "local-model",
                    "allowLocal": True,
                    "credentialReference": "env:HTTP_AI_KEY",
                },
            )
            assert code == 200 and provider["provider"]["id"] == "http-local"
            assert provider["provider"]["hasApiKey"] is True
            _assert_public(provider, roots=(state, data, downloads), secret=secret)

            code, prompt = _request_json(
                base + "/v1/ai/prompts",
                method="POST",
                token=token,
                payload={
                    "id": "http-notes",
                    "title": "HTTP Notes",
                    "instructions": "Extract decisions and actions.",
                    "icon": "notebook-pen",
                },
            )
            assert code == 200 and prompt["prompt"]["id"] == "http-notes"

            code, detail = _request_json(base + "/v1/ai/prompts/http-notes", token=token)
            assert code == 200 and detail["prompt"]["title"] == "HTTP Notes"

            code, duplicate = _request_json(
                base + "/v1/ai/prompts/http-notes/duplicate",
                method="POST",
                token=token,
                payload={"id": "http-notes-copy", "title": "HTTP Notes Copy"},
            )
            assert code == 201 and duplicate["prompt"]["id"] == "http-notes-copy"

            code, queue = _request_json(base + "/v1/ai/queue", token=token)
            assert code == 200 and queue["queueCapacity"] == 50

            code, submitted = _request_json(
                base + "/v1/ai/tasks/text",
                method="POST",
                token=token,
                payload={
                    "providerId": "http-local",
                    "content": "HTTP task content",
                    "promptId": "http-notes",
                    "label": "HTTP Task",
                },
            )
            task_id = submitted["task"]["id"]
            assert code == 202 and task_id == "a" * 32

            code, task = _request_json(base + f"/v1/ai/tasks/{task_id}", token=token)
            assert code == 200 and task["task"]["state"] == "queued"

            code, transcript_task = _request_json(
                base + "/v1/ai/tasks/transcript",
                method="POST",
                token=token,
                payload={
                    "providerId": "http-local",
                    "mediaId": "c" * 32,
                    "promptId": "summary",
                },
            )
            assert code == 202 and transcript_task["task"]["id"] == "b" * 32

            code, cancelled = _request_json(
                base + f"/v1/ai/tasks/{task_id}/cancel",
                method="POST",
                token=token,
            )
            assert code == 200 and cancelled["task"]["state"] == "cancelled"

            code, history = _request_json(base + "/v1/ai/history?limit=10", token=token)
            assert code == 200 and history["runs"] == [] and history["limit"] == 10

            code, cleared = _request_json(
                base + "/v1/ai/history/clear",
                method="POST",
                token=token,
            )
            assert code == 200 and cleared["deleted"] == 0

            code, invalid_task = _http_error_json(
                base + "/v1/ai/tasks/not-a-task",
                token=token,
            )
            assert code == 400 and invalid_task["code"] == "AI_INVALID_TASK_ID"

            code, missing_task = _http_error_json(
                base + "/v1/ai/tasks/" + "f" * 32,
                token=token,
            )
            assert code == 404 and missing_task["code"] == "AI_TASK_NOT_FOUND"

            code, missing_history = _http_error_json(
                base + "/v1/ai/history/" + "e" * 32,
                token=token,
            )
            assert code == 404 and missing_history["code"] == "AI_HISTORY_NOT_FOUND"

            code, removed_prompt = _request_json(
                base + "/v1/ai/prompts/http-notes-copy/delete",
                method="POST",
                token=token,
            )
            assert code == 200 and removed_prompt["deleted"] is True

            code, reset_prompts = _request_json(
                base + "/v1/ai/prompts/reset",
                method="POST",
                token=token,
            )
            assert code == 200 and reset_prompts["count"] >= 8

            code, removed_provider = _request_json(
                base + "/v1/ai/providers/http-local/delete",
                method="POST",
                token=token,
            )
            assert code == 200 and removed_provider["deleted"] is True
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()
            if previous is None:
                os.environ.pop("HTTP_AI_KEY", None)
            else:
                os.environ["HTTP_AI_KEY"] = previous


if __name__ == "__main__":
    run()
    print("Headless AI HTTP self-test passed")
