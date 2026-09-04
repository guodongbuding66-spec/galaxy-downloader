from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import desktop_asr
from desktop_asr import install_desktop_asr, run_desktop_asr_self_test
from desktop_hooks import registered_after_build_ui_hooks


class FakeWindow:
    pass


class FakeEngine:
    EngineWindow = FakeWindow

    @staticmethod
    def default_download_dir() -> Path:
        return Path("/managed-downloads")


def run_test() -> None:
    install_desktop_asr(FakeEngine)
    assert getattr(FakeWindow, "_galaxy_desktop_asr_installed", False) is True
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-asr") == 1
    install_desktop_asr(FakeEngine)
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-asr") == 1

    original_api = desktop_asr.Qwen3HeadlessAsrApi
    calls: list[Path] = []

    class FakeQwen3Api:
        def __init__(self, download_root: Path) -> None:
            calls.append(Path(download_root))

    desktop_asr.Qwen3HeadlessAsrApi = FakeQwen3Api
    try:
        instance = desktop_asr._api(FakeEngine)
        assert isinstance(instance, FakeQwen3Api)
        assert calls == [Path("/managed-downloads")]
    finally:
        desktop_asr.Qwen3HeadlessAsrApi = original_api

    devices, device, compute, enabled = desktop_asr._provider_controls(
        "sensevoice", "mps", "int8"
    )
    assert devices == desktop_asr._SENSEVOICE_DEVICES
    assert device == "mps"
    assert compute == "default"
    assert enabled is False

    devices, device, compute, enabled = desktop_asr._provider_controls(
        "parakeet", "mps", "float16"
    )
    assert devices == desktop_asr._PARAKEET_DEVICES
    assert device == "auto"
    assert compute == "default"
    assert enabled is False

    language, locked = desktop_asr._provider_language("parakeet", "en")
    assert language == "auto"
    assert locked is True

    devices, device, compute, enabled = desktop_asr._provider_controls(
        "qwen3-asr", "mps", "float16"
    )
    assert devices == desktop_asr._QWEN3_DEVICES
    assert device == "auto"
    assert compute == "default"
    assert enabled is False

    language, locked = desktop_asr._provider_language("qwen3-asr", "zh")
    assert language == "zh"
    assert locked is False

    language, locked = desktop_asr._provider_language("qwen3-asr", "auto")
    assert language == "auto"
    assert locked is False

    language, locked = desktop_asr._provider_language("faster-whisper", "auto")
    assert language == ""
    assert locked is False

    devices, device, compute, enabled = desktop_asr._provider_controls(
        "faster-whisper", "mps", "float16"
    )
    assert devices == desktop_asr._LEGACY_DEVICES
    assert device == "auto"
    assert compute == "float16"
    assert enabled is True

    run_desktop_asr_self_test()


if __name__ == "__main__":
    run_test()
    print("Desktop ASR self-test passed")
