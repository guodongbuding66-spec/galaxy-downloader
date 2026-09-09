from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import desktop_gallery_dl  # noqa: E402


class DesktopGalleryDlTests(unittest.TestCase):
    def test_module_contract(self) -> None:
        desktop_gallery_dl.run_desktop_gallery_dl_self_test()

    def test_production_entrypoint_installs_desktop_gallery_dl(self) -> None:
        source = (LOCAL_ENGINE / "entrypoint.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        imported_names: set[str] = set()
        called_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "desktop_gallery_dl":
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called_names.append(node.func.id)

        self.assertIn("install_desktop_gallery_dl", imported_names)
        self.assertIn("run_desktop_gallery_dl_self_test", imported_names)
        self.assertEqual(called_names.count("install_desktop_gallery_dl"), 1)
        self.assertEqual(called_names.count("run_desktop_gallery_dl_self_test"), 1)
        self.assertIn("_galaxy_desktop_gallery_dl_installed", source)

    def test_hook_runs_after_quick_download_panel(self) -> None:
        gallery_source = (LOCAL_ENGINE / "desktop_gallery_dl.py").read_text(encoding="utf-8")
        quick_source = (LOCAL_ENGINE / "desktop_quick_download.py").read_text(encoding="utf-8")
        self.assertIn('"desktop-gallery-dl"', gallery_source)
        self.assertIn("order=47", gallery_source)
        self.assertIn('"desktop-quick-download"', quick_source)
        self.assertIn("order=40", quick_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
