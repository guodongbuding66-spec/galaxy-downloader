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

import headless_qwen3_asr_api as module  # noqa: E402
from asr_preferences import save_asr_preferences  # noqa: E402
from headless_asr_api import HeadlessAsrApiError, HeadlessAsrContext  # noqa: E402
from headless_qwen3_asr_api import Qwen3HeadlessAsrApi  # noqa: E402
from qwen3_asr_provider import LANGUAGES as QWEN3_LANGUAGES  # noqa: E402


class FakeRecommendation:
    provider = "qwen3-asr"
    model = "0.6b-hf"
    profile = "accurate"
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
        api = Qwen3HeadlessAsrApi(downloads, context=context)
        recommendation = FakeRecommendation()

        status = SimpleNamespace(installed_models=("0.6b-hf",))
        with patch.object(module, "qwen3_asr_status", return_value=status):
            models = api.models("qwen3-asr")
            assert models["count"] == 1
            row = models["models"][0]
            assert row["provider"] == "qwen3-asr"
            assert row["model"] == "0.6b-hf"
            assert row["installed"] is True and row["managed"] is True
            assert row["automaticLanguageDetection"] is True
            assert row["forcedLanguage"] is True
            assert row["mps"] is False
            assert "auto" in row["languages"] and "zh" in row["languages"]
            rendered = json.dumps(models)
            assert str(data) not in rendered and str(downloads) not in rendered

        with patch.object(module, "recommend_asr_route", return_value=recommendation):
            saved = api.save_preferences(
                {
                    "provider": "qwen3-asr",
                    "profile": "accurate",
                    "model": "0.6b-hf",
                    "language": "zh",
                    "device": "cuda:0",
                    "computeType": "default",
                }
            )
            assert saved["settings"]["provider"] == "qwen3-asr"
            assert saved["settings"]["model"] == "0.6b-hf"
            assert saved["settings"]["language"] == "zh"
            assert saved["settings"]["computeType"] == ""
            assert saved["modelDownloadAutomatic"] is False
            recommended = api.recommend(
                {
                    "provider": "qwen3-asr",
                    "profile": "accurate",
                    "hardware": {"gpuAvailable": True, "vramGb": 8},
                }
            )
            assert recommended["recommendation"]["provider"] == "qwen3-asr"

        hostile = f"installed under {data / 'models' / 'asr' / 'qwen3-asr' / '0.6b-hf'}"
        with patch.object(module, "install_qwen3_asr_model", return_value=(True, hostile)):
            installed = api.install_model("qwen3-asr", "0.6b-hf", {"timeoutSeconds": 60})
            assert installed["operation"]["success"] is True
            assert str(data) not in installed["operation"]["detail"]
            assert "[LOCAL_PATH]" in installed["operation"]["detail"]

        with patch.object(
            module,
            "remove_qwen3_asr_model",
            return_value=(True, f"removed {downloads / 'model-cache'}"),
        ):
            removed = api.remove_model("qwen3-asr", "0.6b-hf")
            assert removed["operation"]["success"] is True
            assert str(downloads) not in removed["operation"]["detail"]

        artifact = SimpleNamespace(
            kind="transcript",
            media_id="a" * 32,
            path=state / "transcripts" / "secret.srt",
            model="0.6b-hf",
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
                    "provider": "qwen3-asr",
                    "model": "0.6b-hf",
                    "ready": True,
                }
            }
            kwargs = transcribe.call_args.kwargs
            assert kwargs["provider"] == "qwen3-asr"
            assert kwargs["model"] == "0.6b-hf"
            assert kwargs["language"] == "zh"
            assert kwargs["device"] == "cuda:0"
            assert kwargs["compute_type"] == ""
            rendered = json.dumps(result)
            assert str(state) not in rendered and '"path"' not in rendered.lower()

        save_asr_preferences(
            context,
            provider="faster-whisper",
            profile="balanced",
            model="base",
            language="en",
            device="cpu",
            compute_type="int8",
        )
        switched_artifact = SimpleNamespace(
            kind="transcript",
            media_id="b" * 32,
            path=state / "transcripts" / "switched.srt",
            model="0.6b-hf",
        )
        with (
            patch.object(module, "recommend_asr_route", return_value=recommendation),
            patch.object(module, "transcribe_with_provider", return_value=switched_artifact) as switched,
        ):
            switched_result = api.transcribe(
                {"mediaId": "b" * 32, "provider": "qwen3-asr", "language": "auto"}
            )
            assert switched_result["transcript"]["model"] == "0.6b-hf"
            kwargs = switched.call_args.kwargs
            assert kwargs["model"] == ""
            assert kwargs["language"] == "auto"
            assert kwargs["device"] == ""
            assert kwargs["compute_type"] == ""

        assert "auto" in QWEN3_LANGUAGES and "zh" in QWEN3_LANGUAGES
        _expect_code(
            lambda: api.install_model("qwen3-asr", "../../escape"),
            "ASR_MODEL_INVALID",
        )
        _expect_code(
            lambda: api.save_preferences(
                {"provider": "qwen3-asr", "model": "0.6b-hf", "language": "xx"}
            ),
            "ASR_LANGUAGE_INVALID",
        )
        _expect_code(
            lambda: api.save_preferences(
                {"provider": "qwen3-asr", "model": "0.6b-hf", "device": "mps"}
            ),
            "ASR_DEVICE_INVALID",
        )
        _expect_code(
            lambda: api.save_preferences(
                {
                    "provider": "qwen3-asr",
                    "model": "0.6b-hf",
                    "computeType": "float16",
                }
            ),
            "ASR_COMPUTE_TYPE_INVALID",
        )


if __name__ == "__main__":
    run()
    print("Headless Qwen3-ASR self-test passed")
