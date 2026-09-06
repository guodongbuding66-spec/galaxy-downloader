from __future__ import annotations

import unittest
from pathlib import Path


_DASHBOARD_SCRIPT = Path(__file__).with_name("web-dashboard") / "learning.js"


class HeadlessLearningProviderUiTests(unittest.TestCase):
    def test_download_selector_excludes_discovery_only_providers(self) -> None:
        script = _DASHBOARD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("provider.downloadAvailable !== false", script)
        self.assertIn("/v1/learning/providers", script)
        self.assertNotIn('<option value="hotmart">', script.lower())


if __name__ == "__main__":
    unittest.main()
