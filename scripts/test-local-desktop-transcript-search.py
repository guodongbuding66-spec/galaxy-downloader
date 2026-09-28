from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_transcript import run_desktop_transcript_search_self_test
from transcript_workspace import run_transcript_workspace_self_test


def run_test() -> None:
    run_desktop_transcript_search_self_test()
    run_transcript_workspace_self_test()


if __name__ == "__main__":
    run_test()
    print("Desktop Transcript Search self-test passed")
