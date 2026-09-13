from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_telegram_download import run_desktop_telegram_download_self_test  # noqa: E402


class DesktopTelegramDownloadTests(unittest.TestCase):
    def test_helpers_self_test(self) -> None:
        run_desktop_telegram_download_self_test()

    def test_transfer_center_mounts_download_tab_through_builder(self) -> None:
        source = (LOCAL_ENGINE / "desktop_transfers.py").read_text(encoding="utf-8")
        self.assertIn("from desktop_telegram_download import build_telegram_download_tab", source)
        call = "build_telegram_download_tab(notebook, dialog, engine_module)"
        self.assertIn(call, source)

        show_start = source.index("def _show_transfer_center(window, engine_module) -> None:")
        show_end = source.index("\ndef _add_transfer_entry(window, engine_module) -> None:", show_start)
        show_block = source[show_start:show_end]
        self.assertIn(call, show_block)
        self.assertLess(show_block.index('notebook.add(telegram_tab, text="Telegram")'), show_block.index(call))
        self.assertLess(show_block.index(call), show_block.index("    def refresh_status() -> None:"))

    def test_download_surface_has_bounded_browser_and_batch_controls(self) -> None:
        source = (LOCAL_ENGINE / "desktop_telegram_download.py").read_text(encoding="utf-8")
        for marker in (
            'notebook.add(tab, text="Telegram 下载")',
            '"Telegram 下载 / Chat Browser"',
            'text="浏览公共来源"',
            'text="搜索 Chat"',
            'text="浏览 Chat"',
            'text="下载所选"',
            'text="下载当前列表"',
            'selectmode="extended"',
            "to=100",
            "ids = ids[:100]",
            "下载文件只写入 Galaxy 管理的 Telegram 目录。",
        ):
            self.assertIn(marker, source)

    def test_download_surface_reuses_core_and_has_no_direct_network_or_destination_escape(self) -> None:
        source = (LOCAL_ENGINE / "desktop_telegram_download.py").read_text(encoding="utf-8")
        for marker in (
            "browse_public_telegram(",
            "browse_telegram_chat(",
            "list_telegram_chats(",
            "download_public_telegram(",
            "download_telegram_chat(",
        ):
            self.assertIn(marker, source)

        lowered = source.lower()
        for forbidden in (
            "requests.",
            "urllib.request",
            "api.telegram.org",
            "subprocess.run",
            "shell=true",
            "filedialog.askdirectory",
            "bot_token",
            "secrets_filename",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_network_work_runs_off_ui_thread_and_returns_via_after(self) -> None:
        source = (LOCAL_ENGINE / "desktop_telegram_download.py").read_text(encoding="utf-8")
        for marker in (
            'threading.Thread(target=worker, name="GalaxyTelegramBrowsePublic", daemon=True).start()',
            'threading.Thread(target=worker, name="GalaxyTelegramBrowseChat", daemon=True).start()',
            'threading.Thread(target=worker, name="GalaxyTelegramDownload", daemon=True).start()',
            "dialog.after(0, finish)",
        ):
            self.assertIn(marker, source)

    def test_existing_transfer_center_workflows_remain_present(self) -> None:
        source = (LOCAL_ENGINE / "desktop_transfers.py").read_text(encoding="utf-8")
        for marker in (
            'notebook.add(torrent_tab, text="Torrent / Magnet")',
            'notebook.add(p2p_tab, text="P2P 短码")',
            'notebook.add(telegram_tab, text="Telegram")',
            "download_torrent(engine_module, source)",
            "receive_p2p_file(engine_module, code, on_progress=progress)",
            "upload_to_telegram(",
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
