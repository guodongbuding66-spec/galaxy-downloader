from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from runtime_health import run_runtime_health_self_test  # noqa: E402
from workspace_policy import run_workspace_self_test  # noqa: E402


def main() -> int:
    run_workspace_self_test()
    run_runtime_health_self_test()
    print("Local runtime/network policy tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
