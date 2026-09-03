from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from ai_provider_manager import run_ai_provider_manager_self_test
from bilibili_advanced import run_bilibili_advanced_self_test
from desktop_advanced import run_desktop_advanced_self_test
from galaxy_cli import run_cli_self_test
from headless_service import run_headless_service_self_test
from local_media_import import run_local_media_import_self_test
from media_postprocess import run_media_postprocess_self_test
from music_workspace import run_music_workspace_self_test
from plugin_marketplace import run_plugin_marketplace_self_test
from reader_library import run_reader_library_self_test
from subscription_rules import run_subscription_rules_self_test
from telegram_transfer import run_telegram_transfer_self_test
from transcript_workspace import run_transcript_workspace_self_test


def main() -> int:
    checks = (
        ("AI provider manager", run_ai_provider_manager_self_test),
        ("Bilibili advanced", run_bilibili_advanced_self_test),
        ("Advanced desktop wiring", run_desktop_advanced_self_test),
        ("Galaxy CLI", run_cli_self_test),
        ("Headless service", run_headless_service_self_test),
        ("Local media import", run_local_media_import_self_test),
        ("Media postprocess", run_media_postprocess_self_test),
        ("Music workspace", run_music_workspace_self_test),
        ("Plugin marketplace", run_plugin_marketplace_self_test),
        ("Reader library", run_reader_library_self_test),
        ("Subscription rules", run_subscription_rules_self_test),
        ("Telegram transfer", run_telegram_transfer_self_test),
        ("Transcript workspace", run_transcript_workspace_self_test),
    )
    for label, check in checks:
        check()
        print(f"[ok] {label}")
    print("Galaxy 54 advanced module gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
