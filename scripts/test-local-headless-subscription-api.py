from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiServer  # noqa: E402
from headless_media_api import HeadlessMediaApi, HeadlessMediaContext  # noqa: E402
from headless_service import HeadlessRuntime  # noqa: E402
from headless_subscription_api import (  # noqa: E402
    HeadlessSubscriptionApi,
    HeadlessSubscriptionContext,
    run_headless_subscription_api_self_test,
)
from subscription_v2 import ingest_subscription_entries  # noqa: E402
from subscriptions import SubscriptionEntry  # noqa: E402


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
) -> tuple[int, dict]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, method=method, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=4) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def run() -> None:
    run_headless_subscription_api_self_test()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        downloads = root / "downloads"
        state = root / "state"
        program = root / "program"
        for target in (downloads, state, program):
            target.mkdir()

        subscription_context = HeadlessSubscriptionContext(program, state)
        subscription_api = HeadlessSubscriptionApi(context=subscription_context)
        media_context = HeadlessMediaContext(program, state, downloads)
        media_api = HeadlessMediaApi(downloads, context=media_context)
        runtime = HeadlessRuntime(downloads, max_queue_size=2)
        server = GalaxyApiServer(
            ("127.0.0.1", 0),
            runtime,
            "",
            "127.0.0.1",
            media_api,
            subscription_api=subscription_api,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            base = f"http://127.0.0.1:{port}"

            code, created = _request_json(
                base + "/v1/subscriptions",
                method="POST",
                payload={
                    "sourceUrl": "https://example.com/channel?utm_source=api&token=secret",
                    "title": "API Channel",
                    "intervalMinutes": 60,
                    "autoDownload": False,
                },
            )
            assert code == 201
            subscription = created["subscription"]
            subscription_id = subscription["id"]
            assert "token=" not in subscription["sourceUrl"] and "utm_" not in subscription["sourceUrl"]
            assert "seenEntryIds" not in subscription

            code, listed = _request_json(base + "/v1/subscriptions")
            assert code == 200 and listed["total"] == 1
            assert listed["subscriptions"][0]["id"] == subscription_id

            code, rules = _request_json(
                base + f"/v1/subscriptions/{subscription_id}/rules",
                method="POST",
                payload={
                    "manualReview": True,
                    "autoDownload": False,
                    "includeKeywords": ["Episode"],
                    "tags": ["api"],
                    "filename": "%(title)s [%(id)s].%(ext)s",
                },
            )
            assert code == 200 and rules["rules"]["manualReview"] is True
            assert "directory" not in rules["rules"]

            ingest_subscription_entries(
                subscription_context,
                subscription_id,
                [
                    SubscriptionEntry(
                        "episode:1",
                        "Episode One",
                        "https://example.com/watch/1?token=hidden&sig=abc",
                        "20260903",
                    )
                ],
                observed_at="2026-09-03T12:00:00Z",
            )

            code, items = _request_json(base + f"/v1/subscriptions/{subscription_id}/items?present=true")
            assert code == 200 and len(items["items"]) == 1
            item = items["items"][0]
            assert item["sourceUrl"] == "https://example.com/watch/1"
            assert "url" not in item and "token=" not in json.dumps(item)

            code, transitioned = _request_json(
                base + f"/v1/subscriptions/{subscription_id}/items/transition",
                method="POST",
                payload={"entryId": "episode:1", "state": "approved", "reason": "user"},
            )
            assert code == 200 and transitioned["item"]["state"] == "approved"

            code, counts = _request_json(base + f"/v1/subscriptions/{subscription_id}/counts")
            assert code == 200 and counts["counts"]["approved"] == 1

            code, reconciled = _request_json(
                base + f"/v1/subscriptions/{subscription_id}/reconcile",
                method="POST",
                payload={},
            )
            assert code == 200 and reconciled["subscriptionId"] == subscription_id

            code, updated = _request_json(
                base + f"/v1/subscriptions/{subscription_id}/update",
                method="POST",
                payload={"title": "Updated Channel", "enabled": False},
            )
            assert code == 200 and updated["subscription"]["title"] == "Updated Channel"
            assert updated["subscription"]["enabled"] is False

            try:
                _request_json(
                    base + f"/v1/subscriptions/{subscription_id}/rules",
                    method="POST",
                    payload={"directory": str(root / "private")},
                )
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
            else:
                raise AssertionError("subscription API accepted a local output directory")

            code, detail = _request_json(base + f"/v1/subscriptions/{subscription_id}")
            assert code == 200 and detail["subscription"]["title"] == "Updated Channel"
            assert "directory" not in detail["rules"]

            code, deleted = _request_json(
                base + f"/v1/subscriptions/{subscription_id}/delete",
                method="POST",
            )
            assert code == 200 and deleted["deleted"] is True

            try:
                _request_json(base + f"/v1/subscriptions/{subscription_id}")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
            else:
                raise AssertionError("deleted subscription remained addressable")

            code, core = _request_json(base + "/v1/status")
            assert code == 200 and core["ok"] is True and core["protocol"] == 2
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()


if __name__ == "__main__":
    run()
    print("Headless Subscription API self-test passed")
