from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_qr_transfer import run_desktop_qr_transfer_self_test  # noqa: E402


class DesktopQrTransferTests(unittest.TestCase):
    def test_helpers_self_test(self) -> None:
        run_desktop_qr_transfer_self_test()

    def test_transfer_center_mounts_qr_tab_and_cleans_up(self) -> None:
        source = (LOCAL_ENGINE / "desktop_transfers.py").read_text(encoding="utf-8")
        self.assertIn("from desktop_qr_transfer import build_qr_transfer_tab", source)
        self.assertIn("qr_tab = build_qr_transfer_tab(notebook, dialog)", source)
        self.assertIn("qr_tab._galaxy_qr_stop()", source)
        self.assertIn("LAN P2P/QR ✓", source)
        self.assertIn("assert callable(build_qr_transfer_tab)", source)

        show_start = source.index("def _show_transfer_center(window, engine_module) -> None:")
        show_end = source.index("\ndef _add_transfer_entry(window, engine_module) -> None:", show_start)
        show_block = source[show_start:show_end]
        self.assertLess(show_block.index("build_telegram_download_tab("), show_block.index("build_qr_transfer_tab("))
        self.assertLess(show_block.index("build_qr_transfer_tab("), show_block.index("    def refresh_status() -> None:"))
        close_block = show_block[show_block.index("    def close() -> None:"):]
        self.assertLess(close_block.index("qr_tab._galaxy_qr_stop()"), close_block.index("stop_sender()"))
        self.assertLess(close_block.index("stop_sender()"), close_block.index("dialog.destroy()"))

    def test_qr_surface_uses_native_picker_and_readonly_outputs(self) -> None:
        source = (LOCAL_ENGINE / "desktop_qr_transfer.py").read_text(encoding="utf-8")
        for marker in (
            'notebook.add(tab, text="QR 手机接收")',
            'filedialog.askopenfilename(parent=dialog',
            'state="readonly"',
            'readonlybackground=ui.PANEL_3',
            'text="创建二维码"',
            'text="停止发送"',
            'QRTransferSession(source).start()',
            'session.qr_png_bytes(box_size=7, border=4)',
            'threading.Thread(target=worker, name="GalaxyQRTransfer", daemon=True).start()',
            'dialog.after(0, finish)',
            'tab._galaxy_qr_stop',
        ):
            self.assertIn(marker, source)

    def test_qr_surface_does_not_add_network_or_destination_escape(self) -> None:
        source = (LOCAL_ENGINE / "desktop_qr_transfer.py").read_text(encoding="utf-8").lower()
        for forbidden in (
            "requests.",
            "urllib.request",
            "http.server",
            "subprocess.run",
            "shell=true",
            "filedialog.askdirectory",
            "outputroot",
            "outputdirectory",
            "bot_token",
        ):
            self.assertNotIn(forbidden, source)

    def test_existing_transfer_workflows_remain_present(self) -> None:
        source = (LOCAL_ENGINE / "desktop_transfers.py").read_text(encoding="utf-8")
        for marker in (
            'notebook.add(torrent_tab, text="Torrent / Magnet")',
            'notebook.add(p2p_tab, text="P2P 短码")',
            'notebook.add(telegram_tab, text="Telegram")',
            "download_torrent(engine_module, source)",
            "receive_p2p_file(engine_module, code, on_progress=progress)",
            "upload_to_telegram(",
            "build_telegram_download_tab(notebook, dialog, engine_module)",
            'threading.Thread(target=worker, name="GalaxyTelegramUpload", daemon=True).start()',
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
