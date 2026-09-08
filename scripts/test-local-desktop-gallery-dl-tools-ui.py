from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_tools import _gallery_action_from_inventory, _gallery_action_label  # noqa: E402


class DesktopGalleryDlToolsUiTests(unittest.TestCase):
    def test_gallery_action_tracks_inventory_readiness(self) -> None:
        self.assertEqual(_gallery_action_from_inventory({}), "install")
        self.assertEqual(_gallery_action_from_inventory({"galleryDlReady": False}), "install")
        self.assertEqual(_gallery_action_from_inventory({"galleryDlReady": True}), "update")
        self.assertEqual(_gallery_action_label({}), "安装 gallery-dl")
        self.assertEqual(
            _gallery_action_label({"galleryDlReady": True}),
            "更新 gallery-dl",
        )

    def test_desktop_surface_uses_inventory_and_managed_action_contract_only(self) -> None:
        source_path = LOCAL_ENGINE / "desktop_tools.py"
        source = source_path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(source_path))

        self.assertIn('inventory.get("galleryDlReady")', source)
        self.assertIn('inventory.get("galleryDlSource")', source)
        self.assertIn('inventory.get("galleryDlVersion")', source)
        self.assertIn('ManagedToolActionRequest(', source)
        self.assertIn('perform_managed_tool_action(engine_module, request)', source)
        self.assertIn('"gallery-dl",\n            "check"', source)
        self.assertIn('"gallery-dl",\n            "remove"', source)
        self.assertIn('_gallery_action_from_inventory(inventory)', source)

        self.assertNotIn("from gallery_dl_manager import", source)
        self.assertNotIn("import gallery_dl_manager", source)
        self.assertNotIn("install_managed_gallery_dl_online", source)
        self.assertNotIn("remove_managed_gallery_dl", source)

    def test_ui_copy_distinguishes_optional_gallery_from_bundled_fallbacks(self) -> None:
        source = (LOCAL_ENGINE / "desktop_tools.py").read_text(encoding="utf-8")
        self.assertIn("gallery-dl 是可选托管工具，可随时移除回未安装状态", source)
        self.assertIn("固定 PyPI gallery-dl 项目元数据", source)
        self.assertIn("SHA-256", source)
        self.assertIn("provenance", source)
        self.assertIn("不会删除任何已下载文件、历史记录或设置", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
