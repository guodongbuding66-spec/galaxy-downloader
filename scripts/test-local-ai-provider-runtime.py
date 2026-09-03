from __future__ import annotations

import io
import os
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import ai_provider_runtime as runtime  # noqa: E402
from ai_provider_registry import save_ai_provider  # noqa: E402
from prompt_library import save_prompt  # noqa: E402


if __name__ == "__main__":
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

        calls = []

        def fake_request(url, payload, headers, *, timeout_seconds, secret=""):
            calls.append((url, payload, headers, timeout_seconds, secret))
            return {"choices": [{"message": {"content": "OK result"}}]}

        with patch.dict(os.environ, {"CUSTOM_AI_KEY": "super-secret"}, clear=False), patch(
            "ai_provider_runtime.validate_provider_endpoint", side_effect=lambda value, **_kwargs: value
        ), patch("ai_provider_runtime._json_request", side_effect=fake_request):
            result = runtime.run_provider_prompt(Engine, "custom", "System", "User")
            assert result.text == "OK result"
            assert calls[-1][2]["Authorization"] == "Bearer super-secret"
            assert calls[-1][3] == 17
            assert runtime.run_prompt_template(Engine, "custom", "test-prompt", "content").text == "OK result"

        assert runtime._http_error_code(401, "bad") == runtime.AUTH
        assert runtime._http_error_code(429, "slow") == runtime.RATE_LIMIT
        assert runtime._http_error_code(504, "timeout") == runtime.TIMEOUT
        assert runtime._http_error_code(404, "model foo not found") == runtime.MODEL_NOT_FOUND
        assert runtime._http_error_code(404, "endpoint missing") == runtime.PROVIDER_ERROR
        assert "super-secret" not in runtime._scrub_detail("Authorization=super-secret", "super-secret")

        error = urllib.error.HTTPError(
            "https://example.com",
            429,
            "Too Many",
            {},
            io.BytesIO(b'{"error":"rate limited"}'),
        )
        with patch("ai_provider_runtime.urllib.request.urlopen", side_effect=error):
            try:
                runtime._json_request("https://example.com", {"x": 1}, {}, timeout_seconds=5)
            except runtime.AiProviderRuntimeError as exc:
                assert exc.code == runtime.RATE_LIMIT and exc.http_status == 429
            else:
                raise AssertionError("HTTP 429 was not classified")

    print("AI provider runtime self-test passed")
