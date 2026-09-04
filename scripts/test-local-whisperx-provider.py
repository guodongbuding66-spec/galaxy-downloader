from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from whisperx_provider import run_whisperx_provider_self_test


if __name__ == "__main__":
    with patch("whisperx_provider._python_executable", return_value=Path(sys.executable).resolve(strict=True)):
        run_whisperx_provider_self_test()
    print("WhisperX provider self-test passed")
