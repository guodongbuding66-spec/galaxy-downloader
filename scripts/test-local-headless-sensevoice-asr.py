from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import headless_api  # noqa: E402
import headless_sensevoice_asr_api as module  # noqa: E402
from asr_preferences import save_asr_preferences  # noqa: E402
from headless_asr_api import HeadlessAsrApiError, HeadlessAsrContext  # noqa: E402
from headless_sensevoice_asr_api import SenseVoiceHeadlessAsrApi  # noqa: E402


class FakeRecommendation:
    provider = "sensevoice"
    model = "small"
    profile = "balanced"
    runtime_available = True
    model_installed = True
    device = "cpu"
    compute_type = ""

    def public_payload(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "profile": self.profile,
            "runtimeAvailable": self.runtime_available,
            "modelInstalled": self.model_installed,
            "device": self.device,
            "computeType": None,
        }


def _expect_code(fn, code: str) -> None:
    try:
        fn()
    except HeadlessAsrApiError as exc:
        assert exc.code == code, (exc.code, code, str(exc))
        return
    raise AssertionError(f"expected HeadlessAsrApiError({code})")


def run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        program = root / "program"
        data = root / "data"
        state = root / "state"
        downloads = root / "downloads"
        for target in (program, data, state, downloads):
            target.mkdir()

        context = HeadlessAsrContext(program, data, state, downloads)
        api = SenseVoiceHeadlessAsrApi(downloads, context=context)
        recommendation = FakeRecommendation()
        providers = [
            {"id": "whisper", "runtimeAvailable": True},
            {"id": "faster-whisper", "runtimeAvailable": True},
            {
                "id": "sensevoice",
                "name": "SenseVoice",
                "runtimeAvailable": True,
                "installerAvailable": True,
                "installedModels": ["small"],
                "models": ["small"],
                "languages": ["auto", "zh", "en"],
                "explicitInstallRequired": True,
                "localFilesOnly": True,
            },
        ]

        with patch.object(module, "list_routable_asr_providers", return_value=providers):
            payload = api.providers()
            assert payload["count"] == 3
            assert [row["id"] for row in payload["providers"]] == [
                "whisper",
                "faster-whisper",
                "sensevoice",
            ]

        status = SimpleNamespace(installed_models=("small",))
        with patch.object(module, "sensevoice_status", return_value=status):
            models = api.models("sensevoice")
            assert models == {
                "models": [
                    {
                        "provider": "sensevoice",
                        "model": "small",
                        "installed": True,
                        "managed": True,
                        "languages": list(module.SENSEVOICE_LANGUAGES),
                        "cpu": True,
                        "gpu": True,
                    }
                ],
                "count": 1,
            }
            rendered = json.dumps(models)
            assert str(data) not in rendered and str(downloads) not in rendered

        with patch.object(module, "recommend_asr_route", return_value=recommendation):
            saved = api.save_preferences(
                {
                    "provider": "sensevoice",
                    "profile": "balanced",
                    "model": "small",
                    "language": "zh",
                    "device": "cpu",
                    "computeType": "default",
                }
            )
            assert saved["settings"]["provider"] == "sensevoice"
            assert saved["settings"]["model"] == "small"
            assert saved["settings"]["computeType"] == ""
            recommended = api.recommend(
                {
                    "provider": "sensevoice",
                    "profile": "balanced",
                    "hardware": {"ramGb": 16, "gpuAvailable": False},
                }
            )
            assert recommended["recommendation"]["provider"] == "sensevoice"

        hostile = f"installed under {data / 'models' / 'asr' / 'sensevoice' / 'small'}"
        with patch.object(module, "install_sensevoice_model", return_value=(True, hostile)):
            installed = api.install_model("sensevoice", "small", {"timeoutSeconds": 1})
            assert installed["operation"]["success"] is True
            assert str(data) not in installed["operation"]["detail"]
            assert "[LOCAL_PATH]" in installed["operation"]["detail"]

        with patch.object(
            module,
            "remove_sensevoice_model",
            return_value=(True, f"removed {downloads / 'model-cache'}"),
        ):
            removed = api.remove_model("sensevoice", "small")
            assert removed["operation"]["success"] is True
            assert str(downloads) not in removed["operation"]["detail"]

        artifact = SimpleNamespace(
            kind="transcript",
            media_id="a" * 32,
            path=state / "transcripts" / "secret.srt",
            model="small",
        )
        with (
            patch.object(module, "recommend_asr_route", return_value=recommendation),
            patch.object(module, "transcribe_with_provider", return_value=artifact) as transcribe,
        ):
            result = api.transcribe({"mediaId": "a" * 32})
            assert result == {
                "transcript": {
                    "kind": "transcript",
                    "mediaId": "a" * 32,
                    "provider": "sensevoice",
                    "model": "small",
                    "ready": True,
                }
            }
            kwargs = transcribe.call_args.kwargs
            assert kwargs["provider"] == "sensevoice"
            assert kwargs["model"] == "small"
            assert kwargs["language"] == "zh"
            assert kwargs["compute_type"] == ""
            rendered = json.dumps(result)
            assert str(state) not in rendered and '"path"' not in rendered.lower()

        # A one-off provider switch must not inherit an incompatible model or
        # compute type from a different stored provider.
        save_asr_preferences(
            context,
            provider="faster-whisper",
            profile="accurate",
            model="base",
            language="en",
            device="cpu",
            compute_type="int8",
        )
        switched_artifact = SimpleNamespace(
            kind="transcript",
            media_id="b" * 32,
            path=state / "transcripts" / "switched.srt",
            model="small",
        )
        with (
            patch.object(module, "recommend_asr_route", return_value=recommendation),
            patch.object(
                module,
                "transcribe_with_provider",
                return_value=switched_artifact,
            ) as switched,
        ):
            switched_result = api.transcribe(
                {"mediaId": "b" * 32, "provider": "sensevoice"}
            )
            assert switched_result["transcript"]["model"] == "small"
            switched_kwargs = switched.call_args.kwargs
            assert switched_kwargs["model"] == ""
            assert switched_kwargs["language"] == ""
            assert switched_kwargs["device"] == ""
            assert switched_kwargs["compute_type"] == ""

        _expect_code(
            lambda: api.install_model("sensevoice", "../../escape"),
            "ASR_MODEL_INVALID",
        )
        _expect_code(
            lambda: api.save_preferences(
                {
                    "provider": "sensevoice",
                    "model": "small",
                    "language": "fr",
                }
            ),
            "ASR_LANGUAGE_INVALID",
        )
        _expect_code(
            lambda: api.save_preferences(
                {
                    "provider": "sensevoice",
                    "model": "small",
                    "device": "cuda:999",
                }
            ),
            "ASR_DEVICE_INVALID",
        )
        _expect_code(
            lambda: api.save_preferences(
                {
                    "provider": "sensevoice",
                    "model": "small",
                    "computeType": "float16",
                }
            ),
            "ASR_COMPUTE_TYPE_INVALID",
        )

        # Production wiring: when no ASR adapter is injected, GalaxyApiServer
        # must create the SenseVoice-capable extension rather than the legacy API.
        sentinel_asr = SimpleNamespace(context=context)
        runtime = SimpleNamespace(download_root=downloads)
        ai = SimpleNamespace(shutdown=lambda: None)
        transfer = SimpleNamespace(shutdown=lambda: None)
        with patch.object(headless_api, "SenseVoiceHeadlessAsrApi", return_value=sentinel_asr) as factory:
            server = headless_api.GalaxyApiServer(
                ("127.0.0.1", 0),
                runtime,
                "sensevoice-headless-test-token-1234567890",
                "127.0.0.1",
                SimpleNamespace(),
                ai_api=ai,
                whisperx_api=SimpleNamespace(),
                plugin_api=SimpleNamespace(),
                transfer_api=transfer,
            )
            try:
                assert server.asr_api is sentinel_asr
                factory.assert_called_once_with(downloads)
            finally:
                server.server_close()


if __name__ == "__main__":
    run()
    print("Headless SenseVoice ASR self-test passed")
