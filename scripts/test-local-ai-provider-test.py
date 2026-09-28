from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_ai_api import HeadlessAiApi, HeadlessAiApiError  # noqa: E402


def run() -> None:
    api = HeadlessAiApi.__new__(HeadlessAiApi)
    api.context = object()

    failed = {
        "success": False,
        "code": "RATE_LIMIT",
        "detail": "rate limited",
        "httpStatus": 429,
    }
    with patch("headless_ai_api.test_provider_connection", return_value=failed) as probe:
        result = api.test_provider("openai")
    assert result["test"]["success"] is False
    assert result["test"]["code"] == "RATE_LIMIT"
    assert result["test"]["httpStatus"] == 429
    probe.assert_called_once_with(api.context, "openai")

    success = {
        "success": True,
        "code": "OK",
        "detail": "OK",
        "providerId": "ollama",
        "model": "qwen3",
    }
    with patch("headless_ai_api.test_provider_connection", return_value=success):
        result = api.test_provider("ollama")
    assert result["test"]["success"] is True
    assert result["test"]["providerId"] == "ollama"

    with patch(
        "headless_ai_api.test_provider_connection",
        return_value={"success": False, "code": "NETWORK", "detail": "x" * 800},
    ):
        bounded = api.test_provider("openai")
    assert len(bounded["test"]["detail"]) == 500

    try:
        api.test_provider("INVALID PROVIDER")
    except HeadlessAiApiError as exc:
        assert exc.code == "AI_INVALID_PROVIDER_ID"
    else:
        raise AssertionError("invalid provider id was accepted")

    http_source = (LOCAL_ENGINE / "headless_ai_http.py").read_text(encoding="utf-8")
    assert 'if action == "test":' in http_source
    assert "self.ai_api.test_provider(provider_id)" in http_source

    ui_source = (LOCAL_ENGINE / "web-dashboard" / "ai-subscriptions.js").read_text(encoding="utf-8")
    for required in (
        "providerTests: {}",
        "data-ai-provider-test",
        "Testing…",
        "Connected ·",
        "/v1/ai/providers/",
        "/test",
        "REQUEST_FAILED",
        "providerTestStatus",
    ):
        assert required in ui_source
    assert "test.success ? 'success' : 'failed'" in ui_source
    assert "result.code || 'Failed'" in ui_source
    assert "apiKey" not in ui_source


if __name__ == "__main__":
    run()
    print("AI Provider connection-test contract passed")
