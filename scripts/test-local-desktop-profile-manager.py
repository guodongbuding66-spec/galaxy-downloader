#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_hooks import registered_after_build_ui_hooks  # noqa: E402
from desktop_profile_manager import (  # noqa: E402
    _merge_editable_settings,
    _settings_summary,
    _split_patterns,
    install_desktop_profile_manager,
    preview_profile_match,
    run_desktop_profile_manager_self_test,
)
from download_profiles import create_profile  # noqa: E402


class FakeWindow:
    pass


class FakeEngine:
    APP_NAME = "Galaxy"
    EngineWindow = FakeWindow


def state_engine(root: Path):
    state = root / "state"
    state.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(app_dir=lambda: root, state_dir=lambda: state, APP_NAME="Galaxy")


def run() -> None:
    installed = install_desktop_profile_manager(FakeEngine)
    assert installed is FakeWindow
    assert getattr(FakeWindow, "_galaxy_desktop_profile_manager_installed", False) is True
    assert "desktop-profile-manager" in registered_after_build_ui_hooks(FakeWindow)
    install_desktop_profile_manager(FakeEngine)
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-profile-manager") == 1

    run_desktop_profile_manager_self_test()
    assert _split_patterns("youtube.com/*\n*.youtube.com/*") == ["youtube.com/*", "*.youtube.com/*"]
    assert _settings_summary({"video": "best", "directory": "Video/YouTube"}) == "best · Video/YouTube"

    preserved = _merge_editable_settings(
        {"script": {"enabled": False, "postDownload": "echo keep-me"}},
        video="2160p",
        audio="best",
        container="mkv",
        subtitle="en",
        archive=True,
        browser="chrome",
        directory="Video/YouTube",
        filename="%(title)s",
        rate_limit_mib="8",
        chapters=True,
        sponsor_block=True,
        post_process="remux",
    )
    assert preserved["script"]["postDownload"] == "echo keep-me"
    assert preserved["rateLimitMiB"] == "8"

    with tempfile.TemporaryDirectory() as directory:
        engine = state_engine(Path(directory))
        youtube = create_profile(engine, "YouTube", patterns=["youtube.com/*"])
        course = create_profile(engine, "Course", patterns=["udemy.com/course/*"])

        automatic = preview_profile_match(engine, "https://youtube.com/watch?v=1")
        assert automatic["matched"] is True
        assert automatic["mode"] == "auto"
        assert automatic["profileId"] == youtube["id"]

        manual = preview_profile_match(
            engine,
            "https://youtube.com/watch?v=1",
            manual_profile_id=course["id"],
        )
        assert manual["matched"] is True
        assert manual["mode"] == "manual"
        assert manual["profileId"] == course["id"]

        missing = preview_profile_match(engine, "https://example.com/video")
        assert missing == {
            "matched": False,
            "mode": "auto",
            "profileId": "",
            "profileName": "",
        }

    source = (LOCAL_ENGINE / "desktop_profile_manager.py").read_text(encoding="utf-8")
    for required in (
        "list_profiles",
        "create_profile",
        "update_profile",
        "duplicate_profile",
        "delete_profile",
        "import_profiles",
        "export_profiles",
        "resolve_profile",
        "manual_profile_id",
        "URL Match Preview",
        "Manual override",
        "Import JSON",
        "Export JSON",
        "Script 配置仅由 core 保存并原样保留",
    ):
        assert required in source
    assert "subprocess" not in source
    assert "os.system" not in source

    entrypoint = (LOCAL_ENGINE / "entrypoint.py").read_text(encoding="utf-8")
    assert "install_desktop_profile_manager(engine)" in entrypoint
    assert "run_desktop_profile_manager_self_test()" in entrypoint
    assert "_galaxy_desktop_profile_manager_installed" in entrypoint


if __name__ == "__main__":
    run()
    print("Desktop Download Profile manager contract passed")
