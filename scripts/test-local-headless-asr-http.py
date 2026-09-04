from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiRequestHandler  # noqa: E402
from headless_asr_api import HeadlessAsrApiError  # noqa: E402
from headless_asr_http import HeadlessAsrHttpMixin  # noqa: E402
from headless_service import HeadlessRuntime  # noqa: E402


class FakeAsrApi:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def providers(self) -> dict:
        self.calls.append(("providers",))
        return {
            "providers": [
                {"id": "whisper", "runtimeAvailable": True},
                {"id": "faster-whisper", "runtimeAvailable": True},
            ],
            "count": 2,
        }

    def preferences(self) -> dict:
        self.calls.append(("preferences",))
        return {
            "settings": {"provider": "auto", "profile": "balanced", "model": ""},
            "recommendation": {"provider": "faster-whisper", "model": "base"},
            "modelDownloadAutomatic": False,
        }

    def models(self, provider_id: object = "") -> dict:
        provider = str(provider_id or "")
        self.calls.append(("models", provider))
        if provider == "explode":
            raise HeadlessAsrApiError("invalid ASR provider", code="ASR_PROVIDER_INVALID")
        return {
            "models": [
                {
                    "provider": provider or "whisper",
                    "model": "base",
                    "installed": True,
                }
            ],
            "count": 1,
        }

    def recommend(self, payload: dict) -> dict:
        self.calls.append(("recommend", payload))
        return {
            "recommendation": {
                "provider": "faster-whisper",
                "model": "base",
                "profile": payload.get("profile", "balanced"),
            }
        }

    def save_preferences(self, payload: dict) -> dict:
        self.calls.append(("save_preferences", payload))
        return {
            "settings": {
                "provider": payload.get("provider", "auto"),
                "profile": payload.get("profile", "balanced"),
                "model": payload.get("model", ""),
            },
            "recommendation": {"provider": "whisper", "model": "base"},
            "modelDownloadAutomatic": False,
        }

    def reset_preferences(self) -> dict:
        self.calls.append(("reset_preferences",))
        return {
            "settings": {"provider": "auto", "profile": "balanced", "model": ""},
            "modelDownloadAutomatic": False,
        }

    def install_model(self, provider_id: object, model_id: object, payload: dict) -> dict:
        self.calls.append(("install_model", str(provider_id), str(model_id), payload))
        return {
            "operation": {
                "success": True,
                "provider": str(provider_id),
                "model": str(model_id),
                "detail": "installed",
            }
        }

    def remove_model(self, provider_id: object, model_id: object) -> dict:
        self.calls.append(("remove_model", str(provider_id), str(model_id)))
        return {
            "operation": {
                "success": True,
                "provider": str(provider_id),
                "model": str(model_id),
                "detail": "removed",
            }
        }

    def transcribe(self, payload: dict) -> dict:
        self.calls.append(("transcribe", payload))
        return {
            "transcript": {
                "kind": "transcript",
                "mediaId": payload.get("mediaId"),
                "provider": "faster-whisper",
                "model": "base",
                "ready": True,
            }
        }


# Before production wiring the public handler does not include the ASR mixin,
# so this contract composes it explicitly. After production wiring the handler
# already inherits the mixin; reusing it directly avoids an invalid duplicate
# MRO while exercising exactly the same HTTP contract in both lifecycle stages.
if issubclass(GalaxyApiRequestHandler, HeadlessAsrHttpMixin):
    CombinedHandler = GalaxyApiRequestHandler
else:
    class CombinedHandler(HeadlessAsrHttpMixin, GalaxyApiRequestHandler):
        pass


class TestServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, runtime: HeadlessRuntime, auth_token: str, asr_api: FakeAsrApi | None) -> None:
        self.runtime = runtime
        self.auth_token = auth_token
        self.bound_host = "127.0.0.1"
        self.asr_api = asr_api
        self.media_api = None
        self.transcript_api = None
        self.subscription_api = None
        self.reader_api = None
        self.learning_api = None
        self.music_api = None
        self.ai_api = None
        super().__init__(address, CombinedHandler)


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str = "",
    raw_body: bytes | None = None,
) -> tuple[int, dict]:
    body = raw_body
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif raw_body is not None:
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
    raw_body: bytes | None = None,
) -> tuple[int, dict]:
    try:
        _request_json(url, method=method, payload=payload, token=token, raw_body=raw_body)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    raise AssertionError(f"expected HTTP error for {method} {url}")


def run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        downloads = Path(directory).resolve() / "downloads"
        downloads.mkdir()
        runtime = HeadlessRuntime(downloads, max_queue_size=2)
        fake = FakeAsrApi()
        token = "headless-asr-http-token-1234567890"
        server = TestServer(("127.0.0.1", 0), runtime, token, fake)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"

            code, unauthorized = _http_error_json(base + "/v1/asr/providers")
            assert code == 401 and unauthorized["ok"] is False

            # Proves ASR composition does not swallow the existing Headless chain.
            code, status = _request_json(base + "/v1/status", token=token)
            assert code == 200 and status["ok"] is True

            code, providers = _request_json(base + "/v1/asr/providers", token=token)
            assert code == 200 and providers["count"] == 2

            code, preferences = _request_json(base + "/v1/asr/preferences", token=token)
            assert code == 200 and preferences["modelDownloadAutomatic"] is False

            code, models = _request_json(
                base + "/v1/asr/models?provider=faster-whisper",
                token=token,
            )
            assert code == 200 and models["models"][0]["provider"] == "faster-whisper"
            assert ("models", "faster-whisper") in fake.calls

            code, recommendation = _request_json(
                base + "/v1/asr/recommend",
                method="POST",
                token=token,
                payload={
                    "profile": "accurate",
                    "hardware": {"ramGb": 32, "vramGb": 12, "gpuAvailable": True},
                },
            )
            assert code == 200 and recommendation["recommendation"]["profile"] == "accurate"

            code, saved = _request_json(
                base + "/v1/asr/preferences",
                method="POST",
                token=token,
                payload={"provider": "whisper", "profile": "balanced", "model": "base"},
            )
            assert code == 200 and saved["settings"]["provider"] == "whisper"

            code, reset = _request_json(
                base + "/v1/asr/preferences/reset",
                method="POST",
                token=token,
            )
            assert code == 200 and reset["settings"]["provider"] == "auto"

            code, installed = _request_json(
                base + "/v1/asr/models/whisper/base/install",
                method="POST",
                token=token,
                payload={"timeoutSeconds": 1800},
            )
            assert code == 200 and installed["operation"]["success"] is True
            assert ("install_model", "whisper", "base", {"timeoutSeconds": 1800}) in fake.calls

            code, removed = _request_json(
                base + "/v1/asr/models/faster-whisper/base/delete",
                method="POST",
                token=token,
            )
            assert code == 200 and removed["operation"]["success"] is True
            assert ("remove_model", "faster-whisper", "base") in fake.calls

            media_id = "c" * 32
            code, transcript = _request_json(
                base + "/v1/asr/transcribe",
                method="POST",
                token=token,
                payload={"mediaId": media_id, "provider": "auto"},
            )
            assert code == 200 and transcript["transcript"]["mediaId"] == media_id
            assert "path" not in json.dumps(transcript).lower()

            code, adapter_error = _http_error_json(
                base + "/v1/asr/models?provider=explode",
                token=token,
            )
            assert code == 400 and adapter_error["code"] == "ASR_PROVIDER_INVALID"

            code, malformed = _http_error_json(
                base + "/v1/asr/recommend",
                method="POST",
                token=token,
                raw_body=b"{not-json",
            )
            assert code == 400 and malformed["code"] == "ASR_INVALID_REQUEST"

            code, missing = _http_error_json(base + "/v1/asr/does-not-exist", token=token)
            assert code == 404 and missing["ok"] is False
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()

    # Explicitly verify the 503 boundary as a separate server instance.
    with tempfile.TemporaryDirectory() as directory:
        downloads = Path(directory).resolve() / "downloads"
        downloads.mkdir()
        runtime = HeadlessRuntime(downloads, max_queue_size=1)
        server = TestServer(("127.0.0.1", 0), runtime, "", None)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            code, unavailable = _http_error_json(base + "/v1/asr/providers")
            assert code == 503 and unavailable["code"] == "ASR_UNAVAILABLE"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()


if __name__ == "__main__":
    run()
    print("Headless ASR HTTP self-test passed")
