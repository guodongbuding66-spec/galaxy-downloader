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

import headless_api as production  # noqa: E402
import headless_api_base as base  # noqa: E402
from headless_api import GalaxyApiRequestHandler, GalaxyApiServer  # noqa: E402
from headless_service import HeadlessRuntime  # noqa: E402


class FakeAiApi:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    def providers(self) -> dict:
        return {
            "providers": [
                {
                    "id": "fake-ai",
                    "name": "Fake AI",
                    "hasApiKey": False,
                    "credentialReference": "",
                }
            ],
            "count": 1,
        }

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class FakeAsrApi:
    def providers(self) -> dict:
        return {
            "providers": [
                {"id": "whisper", "runtimeAvailable": True},
                {"id": "faster-whisper", "runtimeAvailable": True},
            ],
            "count": 2,
        }

    def recommend(self, payload: dict) -> dict:
        return {
            "recommendation": {
                "provider": "faster-whisper",
                "model": "base",
                "profile": payload.get("profile", "balanced"),
            }
        }


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


def run() -> None:
    # The legacy run_server entrypoint must now resolve the production composite.
    assert base.GalaxyApiServer is GalaxyApiServer
    assert base.GalaxyApiRequestHandler is GalaxyApiRequestHandler

    with tempfile.TemporaryDirectory() as directory:
        downloads = Path(directory).resolve() / "downloads"
        downloads.mkdir()
        runtime = HeadlessRuntime(downloads, max_queue_size=2)
        ai = FakeAiApi()
        asr = FakeAsrApi()
        token = "headless-asr-production-token-1234567890"
        server = GalaxyApiServer(
            ("127.0.0.1", 0),
            runtime,
            token,
            "127.0.0.1",
            object(),
            ai_api=ai,  # type: ignore[arg-type]
            asr_api=asr,  # type: ignore[arg-type]
        )
        assert server.ai_api is ai
        assert server.asr_api is asr
        assert server._owns_ai_api is False
        assert server._owns_asr_api is False

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_address[1]}"

            code, unauthorized_ai = _http_error_json(endpoint + "/v1/ai/providers")
            assert code == 401 and unauthorized_ai["ok"] is False

            code, unauthorized_asr = _http_error_json(endpoint + "/v1/asr/providers")
            assert code == 401 and unauthorized_asr["ok"] is False

            code, status = _request_json(endpoint + "/v1/status", token=token)
            assert code == 200 and status["ok"] is True

            code, ai_payload = _request_json(endpoint + "/v1/ai/providers", token=token)
            assert code == 200 and ai_payload["count"] == 1
            assert ai_payload["providers"][0]["id"] == "fake-ai"

            code, asr_payload = _request_json(endpoint + "/v1/asr/providers", token=token)
            assert code == 200 and asr_payload["count"] == 2
            assert {item["id"] for item in asr_payload["providers"]} == {
                "whisper",
                "faster-whisper",
            }

            code, recommendation = _request_json(
                endpoint + "/v1/asr/recommend",
                method="POST",
                token=token,
                payload={"profile": "accurate", "hardware": {"ramGb": 32}},
            )
            assert code == 200
            assert recommendation["recommendation"] == {
                "provider": "faster-whisper",
                "model": "base",
                "profile": "accurate",
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()

        # Injected adapters are caller-owned and must never be shut down here.
        assert ai.shutdown_calls == 0

    # Verify automatic production adapter creation and AI ownership cleanup
    # without starting real model/provider workers in the test process.
    with tempfile.TemporaryDirectory() as directory:
        downloads = Path(directory).resolve() / "downloads"
        downloads.mkdir()
        runtime = HeadlessRuntime(downloads, max_queue_size=1)
        owned_ai = FakeAiApi()
        owned_asr = FakeAsrApi()
        with (
            patch.object(production, "HeadlessAiApi", return_value=owned_ai),
            patch.object(production, "SenseVoiceHeadlessAsrApi", return_value=owned_asr),
        ):
            server = GalaxyApiServer(
                ("127.0.0.1", 0),
                runtime,
                "",
                "127.0.0.1",
                object(),
            )
        try:
            assert server.ai_api is owned_ai
            assert server.asr_api is owned_asr
            assert server._owns_ai_api is True
            assert server._owns_asr_api is True
        finally:
            server.server_close()
            server.server_close()
            runtime.stop()
        assert owned_ai.shutdown_calls == 1


if __name__ == "__main__":
    run()
    print("Headless ASR production composition self-test passed")
