from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import faster_whisper_provider as provider  # noqa: E402


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root
            @staticmethod
            def data_dir() -> Path:
                target = root / "data"
                target.mkdir(exist_ok=True)
                return target

        assert not provider.provider_status(Engine).installed_models
        assert provider.recommend({"ramGb": 4}, profile="fast")["model"] == "base"
        assert provider.recommend({"gpuAvailable": True, "vramGb": 12}, profile="accurate")["model"] == "large-v3"
        assert "local_files_only=True" in provider._transcribe_script()

        target = provider.model_dir(Engine, "base")

        def fake_download(command, **_kwargs):
            assert command[-2:] == ["base", str(target)]
            target.mkdir(parents=True, exist_ok=True)
            (target / "config.json").write_text("{}", encoding="utf-8")
            (target / "model.bin").write_bytes(b"x" * provider.MIN_MODEL_BYTES)
            return SimpleNamespace(returncode=0, stdout="ready", stderr="")

        with patch("faster_whisper_provider.subprocess.run", side_effect=fake_download):
            ok, detail = provider.install_model(Engine, "base", python_executable=sys.executable)
        assert ok, detail
        assert provider.require_model(Engine, "base") == target
        assert "base" in provider.provider_status(Engine).installed_models

        assert provider.remove_model(Engine, "base")[0]
        assert not target.exists()

        try:
            provider.model_dir(Engine, "../bad")
        except provider.FasterWhisperError:
            pass
        else:
            raise AssertionError("unsafe faster-whisper model id was accepted")

    print("faster-whisper provider self-test passed")
