from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from runtime_storage import run_runtime_storage_self_test  # noqa: E402
from subscription_v2 import run_subscription_v2_self_test  # noqa: E402
from subscriptions import run_subscriptions_self_test  # noqa: E402


if __name__ == "__main__":
    run_subscriptions_self_test()
    run_subscription_v2_self_test()
    run_runtime_storage_self_test()
    print("Subscription V2 rules, reconcile and migration self-tests passed")
