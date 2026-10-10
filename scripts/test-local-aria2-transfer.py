from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from aria2_transfer import run_aria2_transfer_self_test  # noqa: E402
from transfer_center import run_transfer_center_self_test  # noqa: E402


class Aria2TransferTests(unittest.TestCase):
    def test_lifecycle_parser_retry_and_security_boundaries(self) -> None:
        run_aria2_transfer_self_test()

    def test_transfer_facade_preserves_legacy_contract(self) -> None:
        run_transfer_center_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
