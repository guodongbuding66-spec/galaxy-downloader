from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from ai_provider_runtime import ProviderRunResult  # noqa: E402
from ai_workspace import transcript_path  # noqa: E402
from headless_ai_api import HeadlessAiApi, HeadlessAiContext  # noqa: E402
from headless_api import GalaxyApiServer  # noqa: E402
from headless_media_api import HeadlessMediaApi, HeadlessMediaContext  # noqa: E402
from headless_service import HeadlessRuntime  # noqa: E402


def _request_json(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, method=method, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=4) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _http_error_json(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    try:
        _request_json(url, method=method, payload=payload)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    raise AssertionError(f"expected HTTP error for {method} {url}")


def _assert_private_provider_fields_absent(payload: object) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "credentialReference" not in serialized
    assert "OPENAI_API_KEY" not in serialized
    assert "ANTHROPIC_API_KEY" not in serialized
    assert "super-secret" not in serialized


def run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        program = root / "program"
        for target in (downloads, state, data, program):
            target.mkdir()

        ai_context = HeadlessAiContext(program, data, state, downloads)
        ai_api = HeadlessAiApi(downloads, context=ai_context)
        media_context = HeadlessMediaContext(program, state, downloads)
        media_api = HeadlessMediaApi(downloads, context=media_context)
        runtime = HeadlessRuntime(downloads, max_queue_size=2)
        server = GalaxyApiServer(
            ("127.0.0.1", 0),
            runtime,
            "",
            "127.0.0.1",
            media_api,
            ai_api=ai_api,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"

            # Compatibility gate: existing protocol-v2 routing is untouched.
            code, status = _request_json(base + "/v1/status")
            assert code == 200 and status["ok"] is True and status["protocol"] == 2

            code, providers = _request_json(base + "/v1/ai/providers")
            assert code == 200 and len(providers["providers"]) >= 10
            _assert_private_provider_fields_absent(providers)

            code, rejected = _http_error_json(
                base + "/v1/ai/providers",
                method="POST",
                payload={
                    "id": "unsafe-provider",
                    "name": "Unsafe",
                    "protocol": "openai",
                    "baseUrl": "https://example.com/v1/chat/completions",
                    "model": "model-1",
                    "apiKey": "super-secret",
                },
            )
            assert code == 400 and rejected["code"] == "AI_RAW_CREDENTIAL_REJECTED"
            _assert_private_provider_fields_absent(rejected)

            code, created_provider = _request_json(
                base + "/v1/ai/providers",
                method="POST",
                payload={
                    "id": "headless-local",
                    "name": "Headless Local",
                    "protocol": "ollama",
                    "baseUrl": "http://127.0.0.1:11434/api/chat",
                    "model": "qwen3:4b",
                    "allowLocal": True,
                    "credentialReference": "",
                },
            )
            assert code == 201 and created_provider["provider"]["id"] == "headless-local"
            _assert_private_provider_fields_absent(created_provider)

            code, provider_detail = _request_json(base + "/v1/ai/providers/headless-local")
            assert code == 200 and provider_detail["provider"]["model"] == "qwen3:4b"
            _assert_private_provider_fields_absent(provider_detail)

            with patch("headless_ai_api.test_provider_connection", return_value={"success": True, "code": "OK", "detail": "OK"}):
                code, tested = _request_json(base + "/v1/ai/providers/headless-local/test", method="POST")
            assert code == 200 and tested["test"]["success"] is True

            code, prompt = _request_json(
                base + "/v1/ai/prompts",
                method="POST",
                payload={
                    "id": "headless-http",
                    "title": "Headless HTTP",
                    "instructions": "Summarize exactly.",
                    "icon": "sparkles",
                },
            )
            assert code == 201 and prompt["prompt"]["id"] == "headless-http"

            code, copied = _request_json(
                base + "/v1/ai/prompts/headless-http/duplicate",
                method="POST",
                payload={"id": "headless-http-copy", "title": "Headless HTTP Copy"},
            )
            assert code == 201 and copied["prompt"]["id"] == "headless-http-copy"

            media_id = "a" * 32
            transcript_path(ai_context, media_id).write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nhello from transcript\n",
                encoding="utf-8",
            )

            def fake_runtime(_engine, provider_id, _instructions, content):
                assert provider_id == "headless-local"
                return ProviderRunResult(provider_id, "qwen3:4b", "HTTP AI result: " + content[:60])

            with patch("ai_task_service.run_provider_prompt", side_effect=fake_runtime):
                code, text_task = _request_json(
                    base + "/v1/ai/tasks/text",
                    method="POST",
                    payload={
                        "providerId": "headless-local",
                        "promptId": "headless-http",
                        "content": "plain HTTP input",
                        "label": "text task",
                    },
                )
                assert code == 202 and text_task["task"]["state"] == "queued"

                code, transcript_task = _request_json(
                    base + "/v1/ai/tasks/transcript",
                    method="POST",
                    payload={
                        "providerId": "headless-local",
                        "promptId": "headless-http",
                        "mediaId": media_id,
                        "label": "transcript task",
                    },
                )
                assert code == 202 and transcript_task["task"]["state"] == "queued"
                assert ai_api.service.wait_for_idle(4.0)

            text_id = text_task["task"]["id"]
            transcript_id = transcript_task["task"]["id"]
            code, text_status = _request_json(base + f"/v1/ai/tasks/{text_id}")
            assert code == 200 and text_status["task"]["state"] == "succeeded"
            assert text_status["task"]["historyRunId"]
            code, transcript_status = _request_json(base + f"/v1/ai/tasks/{transcript_id}")
            assert code == 200 and transcript_status["task"]["state"] == "succeeded"
            assert transcript_status["task"]["historyRunId"]

            code, task_snapshot = _request_json(base + "/v1/ai/tasks")
            assert code == 200 and "waitingCount" in task_snapshot and "activeCount" in task_snapshot
            serialized_tasks = json.dumps(task_snapshot, ensure_ascii=False)
            assert "plain HTTP input" not in serialized_tasks
            assert "Summarize exactly" not in serialized_tasks

            code, history = _request_json(base + "/v1/ai/history?providerId=headless-local&limit=10")
            assert code == 200 and len(history["history"]) == 2
            assert all("resultText" not in item for item in history["history"])

            run_id = text_status["task"]["historyRunId"]
            code, full_history = _request_json(base + f"/v1/ai/history/{run_id}")
            assert code == 200 and str(full_history["run"]["resultText"]).startswith("HTTP AI result:")

            missing = "0" * 32
            code, missing_task = _http_error_json(base + f"/v1/ai/tasks/{missing}")
            assert code == 404 and missing_task["code"] == "AI_TASK_NOT_FOUND"
            code, missing_history = _http_error_json(base + f"/v1/ai/history/{missing}")
            assert code == 404 and missing_history["code"] == "AI_HISTORY_NOT_FOUND"

            code, removed_history = _request_json(base + f"/v1/ai/history/{run_id}/delete", method="POST")
            assert code == 200 and removed_history["deleted"] is True
            code, cleared_history = _request_json(base + "/v1/ai/history/clear", method="POST")
            assert code == 200 and cleared_history["cleared"] == 1

            code, removed_copy = _request_json(base + "/v1/ai/prompts/headless-http-copy/delete", method="POST")
            assert code == 200 and removed_copy["deleted"] is True
            code, removed_prompt = _request_json(base + "/v1/ai/prompts/headless-http/delete", method="POST")
            assert code == 200 and removed_prompt["deleted"] is True
            code, removed_provider = _request_json(base + "/v1/ai/providers/headless-local/delete", method="POST")
            assert code == 200 and removed_provider["deleted"] is True
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            ai_api.shutdown()
            runtime.stop()


if __name__ == "__main__":
    run()
    print("Headless AI API self-test passed")
