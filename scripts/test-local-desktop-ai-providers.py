from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_ai_providers import (  # noqa: E402
    install_desktop_ai_providers,
    run_desktop_ai_providers_self_test,
)
from desktop_hooks import registered_after_build_ui_hooks  # noqa: E402


class FakeWindow:
    pass


class FakeEngine:
    EngineWindow = FakeWindow


def run() -> None:
    installed = install_desktop_ai_providers(FakeEngine)
    assert installed is FakeWindow
    assert getattr(FakeWindow, "_galaxy_desktop_ai_providers_installed", False) is True
    hooks = registered_after_build_ui_hooks(FakeWindow)
    assert "desktop-ai-providers" in hooks

    install_desktop_ai_providers(FakeEngine)
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-ai-providers") == 1
    run_desktop_ai_providers_self_test()

    source = (LOCAL_ENGINE / "desktop_ai_providers.py").read_text(encoding="utf-8")
    for required in (
        "provider_public_status",
        "save_ai_provider",
        "reset_ai_provider",
        "delete_ai_provider",
        "test_provider_connection",
        "threading.Thread",
        "Credential ref",
        "Allow local endpoint",
        "Testing…",
    ):
        assert required in source
    assert "API Key" in source
    assert "env:OPENAI_API_KEY" in source
    assert "os.environ" not in source

    entrypoint = (LOCAL_ENGINE / "entrypoint.py").read_text(encoding="utf-8")
    assert "install_desktop_ai_providers(engine)" in entrypoint
    assert "run_desktop_ai_providers_self_test()" in entrypoint


if __name__ == "__main__":
    run()
    print("Desktop AI Provider manager contract passed")
