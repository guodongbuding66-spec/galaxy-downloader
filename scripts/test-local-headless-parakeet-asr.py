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

import headless_parakeet_asr_api as module  # noqa: E402
import headless_sensevoice_asr_api as sense_module  # noqa: E402
from asr_preferences import save_asr_preferences  # noqa: E402
from headless_asr_api import HeadlessAsrApiError, HeadlessAsrContext  # noqa: E402
from headless_parakeet_asr_api import ParakeetHeadlessAsrApi  # noqa: E402


class FakeRecommendation:
    provider = "parakeet"
    model = "tdt-0.6b-v3"
    profile = "balanced"
    runtime_available = True
    model_installed = True
    device = "cuda:0"
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
        api = ParakeetHeadlessAsrApi(downloads, context=context)
        recommendation = FakeRecommendation()

        providers = [
            {"id": "whisper", "runtimeAvailable": True},
            {"id": "faster-whisper", "runtimeAvailable": True},
            {"id": "sensevoice", "runtimeAvailable": True},
            {
                "id": "parakeet",
                "name": "NVIDIA Parakeet",
                "runtimeAvailable": True,
                "installedModels": ["tdt-0.6b-v3"],
                "models": ["tdt-0.6b-v3"],
                "languages": ["auto"],
                "supportedLanguages": list(module.PARAKEET_SUPPORTED_LANGUAGES),
                "explicitInstallRequired": True,
                "localFilesOnly": True,
            },
        ]
        with patch.object(sense_module, "list_routable_asr_providers", return_value=providers):
            payload = api.providers()
            assert payload["count"] == 4
            assert [row["id"] for row in payload["providers"]] == [
                "whisper",
                "faster-whisper",
                "sensevoice",
                "parakeet",
            ]

        status = SimpleNamespace(installed_models=("tdt-0.6b-v3",))
        with patch.object(module, "parakeet_status", return_value=status):
            models = api.models("parakeet")
            assert models["count"] == 1
            row = models["models"][0]
            assert row["provider"] == "parakeet"
            assert row["model"] == "tdt-0.6b-v3"
            assert row["installed"] is True
            assert row["languages"] == ["auto"]
            assert row["automaticLanguageDetection"] is True
            assert row["mps"] is False
            rendered = json.dumps(models)
            assert str(data) not in rendered and str(downloads) not in rendered

        with patch.object(module, "recommend_asr_route", return_value=recommendation):
            saved = api.save_preferences(
                {
                    "provider": "parakeet",
                    "profile": "balanced",
                    "model": "tdt-0.6b-v3",
                    "language": "",
                    "device": "cuda:0",
                    "computeType": "default",
                }
            )
            assert saved["settings"]["provider"] == "parakeet"
            assert saved["settings"]["model"] == "tdt-0.6b-v3"
            assert saved["settings"]["language"] == "auto"
            assert saved["settings"]["computeType"] == ""
            recommended = api.recommend(
                {
                    "provider": "parakeet",
                    "profile": "balanced",
                    "hardware": {"gpuAvailable": True, "vramGb": 8},
                }
            )
            assert recommended["recommendation"]["provider"] == "parakeet"

        hostile = f"installed under {data / 'models' / 'asr' / 'parakeet' / 'tdt-0.6b-v3'}"
        with patch.object(module, "install_parakeet_model", return_value=(True, hostile)):
            installed = api.install_model(
                "parakeet",
                "tdt-0.6b-v3",
                {"timeoutSeconds": 1},
            )
            assert installed["operation"]["success"] is True
            assert str(data) not in installed["operation"]["detail"]
            assert "[LOCAL_PATH]" in installed["operation"]["detail"]

        with patch.object(
            module,
            "remove_parakeet_model",
            return_value=(True, f"removed {downloads / 'model-cache'}"),
        ):
            removed = api.remove_model("parakeet", "tdt-0.6b-v3")
            assert removed["operation"]["success"] is True
            assert str(downloads) not in removed["operation"]["detail"]

        artifact = SimpleNamespace(
            kind="transcript",
            media_id="a" * 32,
            path=state / "transcripts" / "secret.srt",
            model="parakeet:tdt-0.6b-v3",
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
                    "provider": "parakeet",
                    "model": "tdt-0.6b-v3",
                    "ready": True,
                }
            }
            kwargs = transcribe.call_args.kwargs
            assert kwargs["provider"] == "parakeet"
            assert kwargs["model"] == "tdt-0.6b-v3"
            assert kwargs["language"] == "auto"
            assert kwargs["device"] == "cuda:0"
            assert kwargs["compute_type"] == ""
            rendered = json.dumps(result)
            assert str(state) not in rendered and '"path"' not in rendered.lower()

        # One-off switches must not inherit provider-specific SenseVoice state.
        save_asr_preferences(
            context,
            provider="sensevoice",
            profile="accurate",
            model="small",
            language="zh",
            device="mps",
            compute_type="",
        )
        switched_artifact = SimpleNamespace(
            kind="transcript",
            media_id="b" * 32,
            path=state / "transcripts" / "switched.srt",
            model="parakeet:tdt-0.6b-v3",
        )
        with (
            patch.object(module, "recommend_asr_route", return_value=recommendation),
            patch.object(module, "transcribe_with_provider", return_value=switched_artifact) as switched,
        ):
            switched_result = api.transcribe(
                {"mediaId": "b" * 32, "provider": "parakeet"}
            )
            assert switched_result["transcript"]["model"] == "tdt-0.6b-v3"
            kwargs = switched.call_args.kwargs
            assert kwargs["model"] == ""
            assert kwargs["language"] == "auto"
            assert kwargs["device"] == ""
            assert kwargs["compute_type"] == ""

        _expect_code(
            lambda: api.install_model("parakeet", "../../escape"),
            "ASR_MODEL_INVALID",
        )
        _expect_code(
            lambda: api.save_preferences(
                {
                    "provider": "parakeet",
                    "model": "tdt-0.6b-v3",
                    "language": "en",
                }
            ),
            "ASR_LANGUAGE_INVALID",
        )
        _expect_code(
            lambda: api.save_preferences(
                {
                    "provider": "parakeet",
                    "model": "tdt-0.6b-v3",
                    "device": "mps",
                }
            ),
            "ASR_DEVICE_INVALID",
        )
        _expect_code(
            lambda: api.save_preferences(
                {
                    "provider": "parakeet",
                    "model": "tdt-0.6b-v3",
                    "computeType": "float16",
                }
            ),
            "ASR_COMPUTE_TYPE_INVALID",
        )


if __name__ == "__main__":
    run()
    print("Headless Parakeet ASR self-test passed")
