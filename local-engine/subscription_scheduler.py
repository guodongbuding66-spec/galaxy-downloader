from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from subscriptions import (
    SubscriptionEntry,
    acknowledge_subscription_entries,
    build_subscription_download_payload,
    check_subscription,
    load_subscriptions,
)

MAX_AUTO_SUBMISSIONS_PER_CHECK = 5


@dataclass(frozen=True)
class AutoCheckResult:
    subscription_id: str
    baseline: bool
    discovered: int
    submitted: int
    skipped: int
    failed: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def subscription_due(subscription: dict[str, Any], *, now: datetime | None = None) -> bool:
    if not bool(subscription.get("enabled", True)) or not bool(subscription.get("autoDownload", False)):
        return False
    try:
        minutes = max(15, int(subscription.get("intervalMinutes") or 60))
    except (TypeError, ValueError):
        minutes = 60
    last = _parse_utc(subscription.get("lastCheckedAt"))
    if last is None:
        return True
    current = (now or _utc_now()).astimezone(timezone.utc)
    return current >= last + timedelta(minutes=minutes)


def due_subscription_ids(engine_module, *, now: datetime | None = None, limit: int = 3) -> list[str]:
    result: list[str] = []
    for item in load_subscriptions(engine_module):
        if subscription_due(item, now=now):
            result.append(str(item["id"]))
        if len(result) >= max(1, min(int(limit), 10)):
            break
    return result


def _submission_accepted(result: object) -> bool:
    if isinstance(result, tuple):
        return bool(result[0]) if result else False
    if isinstance(result, dict):
        return bool(result.get("accepted"))
    return bool(getattr(result, "accepted", False))


def run_auto_check(
    engine_module,
    subscription_id: str,
    submit: Callable[[dict[str, Any]], object],
) -> AutoCheckResult:
    checked = check_subscription(engine_module, subscription_id, mark_seen=False, max_entries=30)
    if checked.baseline:
        return AutoCheckResult(subscription_id, True, 0, 0, 0, 0)

    subscription = next(
        (item for item in load_subscriptions(engine_module) if str(item.get("id")) == subscription_id),
        None,
    )
    if subscription is None:
        return AutoCheckResult(subscription_id, False, len(checked.new_entries), 0, 0, len(checked.new_entries))

    submitted = 0
    skipped = 0
    failed = 0
    # Feed payloads are usually newest-first. Submit the selected window oldest-
    # first so queue order is chronological while still prioritizing recent items.
    selected = tuple(reversed(checked.new_entries[:MAX_AUTO_SUBMISSIONS_PER_CHECK]))
    for entry in selected:
        payload = build_subscription_download_payload(subscription, entry)
        if payload is None:
            acknowledge_subscription_entries(engine_module, subscription_id, [entry.entry_id])
            skipped += 1
            continue
        try:
            accepted = _submission_accepted(submit(payload))
        except Exception:
            accepted = False
        if accepted:
            acknowledge_subscription_entries(engine_module, subscription_id, [entry.entry_id])
            submitted += 1
        else:
            failed += 1

    return AutoCheckResult(
        subscription_id=subscription_id,
        baseline=False,
        discovered=len(checked.new_entries),
        submitted=submitted,
        skipped=skipped,
        failed=failed,
    )


def run_subscription_scheduler_self_test() -> None:
    now = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)
    assert subscription_due({"enabled": True, "autoDownload": True, "intervalMinutes": 60, "lastCheckedAt": ""}, now=now)
    assert not subscription_due({"enabled": True, "autoDownload": False}, now=now)
    assert not subscription_due(
        {
            "enabled": True,
            "autoDownload": True,
            "intervalMinutes": 60,
            "lastCheckedAt": "2026-09-02T23:30:00Z",
        },
        now=now,
    )
    assert subscription_due(
        {
            "enabled": True,
            "autoDownload": True,
            "intervalMinutes": 60,
            "lastCheckedAt": "2026-09-02T22:59:00Z",
        },
        now=now,
    )
