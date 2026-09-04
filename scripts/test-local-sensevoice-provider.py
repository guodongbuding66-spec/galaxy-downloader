from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import sensevoice_provider as provider  # noqa: E402


if __name__ == "__main__":
    provider.run_sensevoice_provider_self_test()
    print("SenseVoice provider self-test passed")
