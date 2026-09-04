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

import headless_asr_api as module  # noqa: E402
from headless_asr_api import (  # noqa: E402
    HeadlessAsrApi,
    HeadlessAsrApiError,
    HeadlessAsrContext,
)


class FakeRecommendation:
    provider = "faster-whisper"
    model = "base"
    profile = "balanced"
    runtime_available = True
    model_installed = True
    device = "cpu"
    compute_type = "int8"

    def public_payload(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "profile": self.profile,
            "runtimeAvailable": self.runtime_available,
            "modelInstalled": self.model_installed,
            "device": self.device,
            "computeType": self.compute_type,
        }


def _render(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _assert_no_local_paths(payload: object, roots: tuple[Path, ...]) -> None:
    rendered = _render(payload)
    assert '"path"' not in rendered.lower()
    for root in roots:
        assert str(root) not in rendered
        assert root.as_posix() not in rendered


def _expect_error(fn, *, code: str) -> HeadlessAsrApiError:
    try:
        fn()
    except HeadlessAsrApiError as exc:
        assert exc.code == code
        return exc
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
        api = HeadlessAsrApi(downloads, context=context)
        roots = (program, data, state, downloads)
        recommendation = FakeRecommendation()

        providers = [
            {
                "id": "whisper",
                "name": "Whisper",
                "runtimeAvailable": True,
                "installedModels": ["base"],
                "models": ["tiny", "base"],
                "explicitInstallRequired": True,
                "localFilesOnly": True,
                "supportsCpu": True,
                "supportsGpu": True,
            },
            {
                "id": "faster-whisper",
                "name": "faster-whisper",
                "runtimeAvailable": True,
                "installedModels": ["base"],
                "models": ["tiny", "base"],
                "explicitInstallRequired": True,
                "localFilesOnly": True,
                "supportsCpu": True,
                "supportsGpu": True,
            },
        ]

        whisper_rows = [
            {
                "model": "base",
                "installed": True,
                "managed": True,
                "sizeBytes": 123,
                "sizeMb": 142,
                "languages": "multilingual",
                "precision": "fp16/fp32",
                "cpu": True,
                "gpu": True,
                # This is deliberately hostile input. The public adapter must
                # project it away rather than trusting the lower layer.
                "path": str(data / "models" / "asr" / "whisper" / "base"),
            }
        ]
        faster_status = SimpleNamespace(
            available=True,
            version="test",
            installed_models=("base",),
            root=data / "models" / "asr" / "faster-whisper",
        )

        with (
            patch.object(module, "list_asr_providers", return_value=providers),
            patch.object(module, "recommend_asr_route", return_value=recommendation),
            patch.object(module, "list_whisper_models", return_value=whisper_rows),
            patch.object(module, "faster_whisper_status", return_value=faster_status),
        ):
            provider_payload = api.providers()
            assert provider_payload["count"] == 2
            assert {row["id"] for row in provider_payload["providers"]} == {
                "whisper",
                "faster-whisper",
            }

            recommended = api.recommend(
                {
                    "provider": "auto",
                    "profile": "balanced",
                    "hardware": {
                        "ramGb": 64,
                        "vramGb": 16,
                        "gpuAvailable": True,
                        "ignoredLocalPath": str(root / "secret"),
                    },
                }
            )
            assert recommended["recommendation"]["provider"] == "faster-whisper"
            assert recommended["recommendation"]["model"] == "base"

            saved = api.save_preferences(
                {
                    "provider": "faster-whisper",
                    "profile": "accurate",
                    "model": "base",
                    "language": "zh",
                    "device": "cpu",
                    "computeType": "int8",
                    "hardware": {"ramGb": 16, "gpuAvailable": False},
                }
            )
            assert saved["settings"]["provider"] == "faster-whisper"
            assert saved["modelDownloadAutomatic"] is False

            with patch.object(
                module,
                "asr_preferences_status",
                return_value={
                    "settings": saved["settings"],
                    "recommendation": recommendation.public_payload(),
                    "modelDownloadAutomatic": False,
                },
            ):
                status = api.preferences({"ramGb": 32, "gpuAvailable": False})
                assert status["modelDownloadAutomatic"] is False

            models = api.models()
            assert models["count"] == len(module.WHISPER_MODELS) + 1
            whisper = next(
                row
                for row in models["models"]
                if row["provider"] == "whisper" and row["model"] == "base"
            )
            assert whisper["installed"] is True
            _assert_no_local_paths(models, roots)

            reset = api.reset_preferences()
            assert reset["settings"]["provider"] == "auto"
            assert reset["modelDownloadAutomatic"] is False

        hostile_detail = (
            f"installer failed in {data / 'models' / 'asr' / 'whisper' / 'base'}; "
            "python=C:\\Users\\tester\\AppData\\Local\\Programs\\Python\\python.exe"
        )
        fake_operation = SimpleNamespace(success=False, detail=hostile_detail)
        with patch.object(module, "install_whisper_model", return_value=fake_operation):
            installed = api.install_model("whisper", "base", {"timeoutSeconds": 1})
            assert installed["operation"]["success"] is False
            assert "[LOCAL_PATH]" in installed["operation"]["detail"]
            assert str(data) not in installed["operation"]["detail"]
            assert "C:\\Users\\tester" not in installed["operation"]["detail"]

        with patch.object(
            module,
            "remove_faster_whisper_model",
            return_value=(True, f"removed {downloads / 'private-model-cache'}"),
        ):
            removed = api.remove_model("faster-whisper", "base")
            assert removed["operation"]["success"] is True
            assert str(downloads) not in removed["operation"]["detail"]

        with patch.object(
            module,
            "install_whisper_model",
            side_effect=RuntimeError(
                f"subprocess failed: {program / 'python'} {state / 'private.json'}"
            ),
        ):
            try:
                api.install_model("whisper", "base")
            except HeadlessAsrApiError as exc:
                rendered_error = str(exc)
                assert "[LOCAL_PATH]" in rendered_error
                for item in roots:
                    assert str(item) not in rendered_error
            else:
                raise AssertionError("expected sanitized install error")

        fake_artifact = SimpleNamespace(
            kind="transcript",
            media_id="c" * 32,
            path=state / "transcripts" / "secret.srt",
            model="base",
        )
        with (
            patch.object(module, "load_asr_preferences") as load_preferences,
            patch.object(module, "recommend_asr_route", return_value=recommendation),
            patch.object(module, "transcribe_with_provider", return_value=fake_artifact),
        ):
            load_preferences.return_value = SimpleNamespace(
                provider="auto",
                profile="balanced",
                model="",
                language="",
                device="",
                compute_type="",
            )
            transcript = api.transcribe(
                {
                    "mediaId": "c" * 32,
                    "provider": "auto",
                    "profile": "balanced",
                    "hardware": {"ramGb": 8, "gpuAvailable": False},
                }
            )
            assert transcript == {
                "transcript": {
                    "kind": "transcript",
                    "mediaId": "c" * 32,
                    "provider": "faster-whisper",
                    "model": "base",
                    "ready": True,
                }
            }
            _assert_no_local_paths(transcript, roots)

        _expect_error(
            lambda: api.models("shell-provider"),
            code="ASR_PROVIDER_INVALID",
        )
        _expect_error(
            lambda: api.install_model("whisper", "../../escape"),
            code="ASR_MODEL_INVALID",
        )
        _expect_error(
            lambda: api.transcribe({"mediaId": "../../etc/passwd"}),
            code="ASR_INVALID_MEDIA_ID",
        )
        _expect_error(
            lambda: api.save_preferences(
                {
                    "provider": "whisper",
                    "profile": "balanced",
                    "model": "base",
                    "language": "zh;rm -rf /",
                }
            ),
            code="ASR_LANGUAGE_INVALID",
        )


if __name__ == "__main__":
    run()
    print("Headless ASR API self-test passed")
