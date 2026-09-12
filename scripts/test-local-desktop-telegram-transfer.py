from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import desktop_transfers  # noqa: E402


class DesktopTelegramTransferTests(unittest.TestCase):
    def test_settings_helper_normalizes_plain_ui_values(self) -> None:
        settings = desktop_transfers._telegram_settings(
            " BOT ",
            " @example_user ",
            " VIDEO ",
            " galaxy-telegram-user ",
        )
        self.assertEqual(settings.mode, "bot")
        self.assertEqual(settings.chat_id, "@example_user")
        self.assertEqual(settings.send_as, "video")
        self.assertEqual(settings.user_adapter, "galaxy-telegram-user")

    def test_transfer_center_has_integrated_telegram_tab_and_no_direct_network_stack(self) -> None:
        source = (LOCAL_ENGINE / "desktop_transfers.py").read_text(encoding="utf-8")
        for marker in (
            'notebook.add(telegram_tab, text="Telegram")',
            '"Telegram 账户与目标"',
            '"上传 / Leech"',
            'text="保存设置"',
            'text="清除 Token"',
            'text="选择 Galaxy 文件"',
            'text="上传到 Telegram"',
            'text=">50 MB 自动分片"',
            'show="•"',
            'state="readonly"',
            'readonlybackground=ui.PANEL_3',
            'values=("bot", "user")',
            'values=("document", "video", "audio")',
            'threading.Thread(target=worker, name="GalaxyTelegramUpload", daemon=True).start()',
            'save_telegram_upload_settings(',
            'upload_to_telegram(',
            'telegram_bot_token_configured(',
            'clear_telegram_bot_token(',
        ):
            self.assertIn(marker, source)

        for forbidden in (
            "requests.post",
            "api.telegram.org",
            "shell=true",
            "subprocess.run",
        ):
            self.assertNotIn(forbidden, source.lower())

    def test_upload_worker_uses_ui_thread_snapshot_only(self) -> None:
        source = (LOCAL_ENGINE / "desktop_transfers.py").read_text(encoding="utf-8")
        start = source.index("    def start_telegram_upload() -> None:")
        end = source.index("    telegram_upload_button = ui.ActionButton(", start)
        block = source[start:end]
        worker_start = block.index("        def worker() -> None:")
        before_worker = block[:worker_start]
        worker = block[worker_start:]

        for ui_read in (
            "telegram_file_var.get()",
            "telegram_token_var.get()",
            "telegram_name_var.get()",
            "telegram_ext_var.get()",
            "telegram_thumbnail_var.get()",
            "telegram_caption_var.get()",
            "telegram_chunk_var.get()",
        ):
            self.assertIn(ui_read, before_worker)
            self.assertNotIn(ui_read, worker)

        self.assertIn("settings = current_telegram_settings()", before_worker)
        self.assertNotIn("current_telegram_settings()", worker)
        self.assertIn("dialog.after(0, finish)", worker)

    def test_bot_token_is_not_preloaded_or_echoed_into_token_field(self) -> None:
        source = (LOCAL_ENGINE / "desktop_transfers.py").read_text(encoding="utf-8")
        telegram = source[source.index("    # Telegram"):]
        self.assertIn('telegram_token_var = tk.StringVar(value="")', telegram)
        self.assertIn('value="Bot Token 已保存" if telegram_bot_token_configured(engine_module) else "Bot Token 未保存"', telegram)
        # Status checks and explicit clear/save actions are allowed. The Desktop
        # surface must never import/read the private token value or secret file.
        self.assertNotIn("from telegram_transfer import _bot_token", source)
        self.assertNotIn("telegram_token_var.set(_bot_token", telegram)
        self.assertNotIn("telegram_token_var = tk.StringVar(value=_bot_token", telegram)
        self.assertNotIn("SECRETS_FILENAME", telegram)
        self.assertNotIn("read_text", telegram)

    def test_file_and_thumbnail_use_system_pickers_and_source_is_described_as_galaxy_file(self) -> None:
        source = (LOCAL_ENGINE / "desktop_transfers.py").read_text(encoding="utf-8")
        telegram = source[source.index("    # Telegram"):]
        self.assertGreaterEqual(telegram.count("filedialog.askopenfilename("), 2)
        self.assertIn('title="选择 Galaxy 下载文件"', telegram)
        self.assertIn('initial = str(Path(engine_module.default_download_dir()).resolve(strict=False))', telegram)
        self.assertIn('title="选择 Telegram JPEG 缩略图"', telegram)
        self.assertIn('filetypes=(("JPEG", "*.jpg *.jpeg"),)', telegram)

    def test_busy_state_covers_mutating_controls_and_restores_mode_capability(self) -> None:
        source = (LOCAL_ENGINE / "desktop_transfers.py").read_text(encoding="utf-8")
        telegram = source[source.index("    # Telegram"):]
        for marker in (
            "telegram_busy_controls: list[object]",
            "settings_save_button",
            "settings_clear_button",
            "file_choose_button",
            "thumbnail_button",
            "telegram_busy_controls.append(telegram_upload_button)",
            'control.state(["disabled" if busy else "!disabled"])',
            'mode_combo.configure(state="readonly")',
            'send_combo.configure(state="readonly")',
            "refresh_telegram_mode()",
        ):
            self.assertIn(marker, telegram)

    def test_existing_torrent_and_p2p_workflows_remain_present(self) -> None:
        source = (LOCAL_ENGINE / "desktop_transfers.py").read_text(encoding="utf-8")
        for marker in (
            'notebook.add(torrent_tab, text="Torrent / Magnet")',
            'notebook.add(p2p_tab, text="P2P 短码")',
            "download_torrent(engine_module, source)",
            "P2PSenderSession(Path(value), on_status=sender_status).start()",
            "receive_p2p_file(engine_module, code, on_progress=progress)",
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
