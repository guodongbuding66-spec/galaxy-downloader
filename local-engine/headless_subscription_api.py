from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from platform_paths import resolve_platform_paths
from subscription_v2 import (
    ITEM_STATES,
    SubscriptionV2Error,
    configure_subscription_rules,
    delete_subscription_v2_state,
    get_subscription_rules,
    list_subscription_items,
    reconcile_subscription_items,
    subscription_item_counts,
    transition_subscription_item,
)
from subscriptions import (
    ALLOWED_INTERVALS,
    add_subscription,
    delete_subscription,
    load_subscriptions,
    update_subscription,
)

_SUBSCRIPTION_FIELDS = frozenset(
    {
        "sourceUrl",
        "title",
        "browser",
        "enabled",
        "autoDownload",
        "intervalMinutes",
        "videoQuality",
        "audioQuality",
        "includeAudio",
    }
)
_RULE_FIELDS = frozenset(
    {
        "includeKeywords",
        "excludeKeywords",
        "latestN",
        "tags",
        "manualReview",
        "autoDownload",
        "profile",
        "filename",
    }
)
_SECRET_DETAIL_RE = re.compile(
    r"(?i)(authorization|api[-_ ]?key|token|secret|cookie|session|password)\s*[:=]\s*[^\s,;]+"
)


class HeadlessSubscriptionApiError(RuntimeError):
    pass


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def _safe_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()[:limit]


def _safe_detail(value: object, limit: int = 600) -> str:
    text = _safe_text(value, limit)
    return _SECRET_DETAIL_RE.sub(r"\1=[REDACTED]", text)[:limit]


def _public_url(value: object) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "", ""
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return "", ""
    host = hostname
    try:
        if parsed.port:
            host = f"{hostname}:{parsed.port}"
    except ValueError:
        return "", ""
    return urlunsplit((parsed.scheme.lower(), host, parsed.path or "/", "", ""))[:900], hostname[:160]


def _clean_changes(payload: object, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise HeadlessSubscriptionApiError("request must be a JSON object")
    unknown = sorted(str(key) for key in payload if str(key) not in allowed)
    if unknown:
        raise HeadlessSubscriptionApiError(f"unsupported fields: {', '.join(unknown[:8])}")
    return {key: payload[key] for key in allowed if key in payload}


def _public_subscription(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _safe_text(item.get("id"), 80),
        "sourceUrl": _safe_text(item.get("sourceUrl"), 1200),
        "title": _safe_text(item.get("title"), 180),
        "browser": _safe_text(item.get("browser"), 24) or "none",
        "enabled": bool(item.get("enabled", True)),
        "autoDownload": bool(item.get("autoDownload", False)),
        "intervalMinutes": _bounded_int(item.get("intervalMinutes"), 60, min(ALLOWED_INTERVALS), max(ALLOWED_INTERVALS)),
        "videoQuality": _safe_text(item.get("videoQuality"), 40) or "best",
        "audioQuality": _safe_text(item.get("audioQuality"), 40) or "best",
        "includeAudio": bool(item.get("includeAudio", True)),
        "seenCount": min(len(item.get("seenEntryIds") or []), 800),
        "lastCheckedAt": _safe_text(item.get("lastCheckedAt"), 48),
        "lastError": _safe_detail(item.get("lastError"), 400),
        "createdAt": _safe_text(item.get("createdAt"), 48),
    }


def _public_rules(rules: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "includeKeywords": list(rules.get("includeKeywords") or [])[:30],
        "excludeKeywords": list(rules.get("excludeKeywords") or [])[:30],
        "latestN": _bounded_int(rules.get("latestN"), 0, 0, 200),
        "tags": list(rules.get("tags") or [])[:30],
        "manualReview": bool(rules.get("manualReview", False)),
        "autoDownload": bool(rules.get("autoDownload", False)),
        "profile": _safe_text(rules.get("profile"), 100),
        "filename": _safe_text(rules.get("filename"), 240),
        "directoryConfigured": bool(str(rules.get("directory") or "").strip()),
    }


def _public_item(item: Mapping[str, Any]) -> dict[str, Any]:
    source_url, source_host = _public_url(item.get("url"))
    return {
        "subscriptionId": _safe_text(item.get("subscriptionId"), 80),
        "entryId": _safe_text(item.get("entryId"), 240),
        "title": _safe_text(item.get("title"), 500),
        "sourceUrl": source_url,
        "sourceHost": source_host,
        "published": _safe_text(item.get("published"), 80),
        "tags": [_safe_text(value, 80) for value in (item.get("tags") or [])][:30],
        "state": _safe_text(item.get("state"), 24),
        "stateReason": _safe_text(item.get("stateReason"), 240),
        "present": bool(item.get("present", True)),
        "missingCount": _bounded_int(item.get("missingCount"), 0, 0, 1_000_000),
        "attempts": _bounded_int(item.get("attempts"), 0, 0, 1_000_000),
        "lastError": _safe_detail(item.get("lastError"), 600),
        "firstSeenAt": _safe_text(item.get("firstSeenAt"), 48),
        "lastSeenAt": _safe_text(item.get("lastSeenAt"), 48),
    }


@dataclass(frozen=True)
class HeadlessSubscriptionContext:
    program_path: Path
    state_path: Path

    def app_dir(self) -> Path:
        return self.program_path

    def state_dir(self) -> Path:
        self.state_path.mkdir(parents=True, exist_ok=True)
        return self.state_path


def build_headless_subscription_context(
    *,
    program_dir: Path | None = None,
    state_dir: Path | None = None,
) -> HeadlessSubscriptionContext:
    program = Path(program_dir or Path(__file__).resolve().parent).expanduser().resolve(strict=False)
    paths = resolve_platform_paths(program_dir=program)
    raw_state = Path(state_dir or paths.state_dir).expanduser()
    if raw_state.exists() and raw_state.is_symlink():
        raise HeadlessSubscriptionApiError("subscription state directory cannot be a symbolic link")
    state = raw_state.resolve(strict=False)
    state.mkdir(parents=True, exist_ok=True)
    return HeadlessSubscriptionContext(program, state)


class HeadlessSubscriptionApi:
    def __init__(
        self,
        *,
        context: HeadlessSubscriptionContext | None = None,
        program_dir: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.context = context or build_headless_subscription_context(program_dir=program_dir, state_dir=state_dir)

    def _raw(self, subscription_id: object) -> dict[str, Any]:
        clean = _safe_text(subscription_id, 80)
        item = next((row for row in load_subscriptions(self.context) if str(row.get("id")) == clean), None)
        if item is None:
            raise HeadlessSubscriptionApiError("subscription not found")
        return item

    def list_subscriptions(self) -> dict[str, Any]:
        rows = load_subscriptions(self.context)
        return {"subscriptions": [_public_subscription(row) for row in rows], "total": len(rows)}

    def detail(self, subscription_id: object) -> dict[str, Any]:
        raw = self._raw(subscription_id)
        clean = str(raw["id"])
        try:
            rules = get_subscription_rules(self.context, clean)
            counts = subscription_item_counts(self.context, clean)
        except SubscriptionV2Error as exc:
            raise HeadlessSubscriptionApiError(str(exc)) from exc
        return {
            "subscription": _public_subscription(raw),
            "rules": _public_rules(rules),
            "counts": counts,
        }

    def create(self, payload: object) -> dict[str, Any]:
        changes = _clean_changes(payload, _SUBSCRIPTION_FIELDS)
        if not changes.get("sourceUrl"):
            raise HeadlessSubscriptionApiError("sourceUrl is required")
        try:
            created = add_subscription(self.context, changes)
        except (TypeError, ValueError) as exc:
            raise HeadlessSubscriptionApiError(str(exc)) from exc
        return _public_subscription(created)

    def update(self, subscription_id: object, payload: object) -> dict[str, Any]:
        self._raw(subscription_id)
        changes = _clean_changes(payload, _SUBSCRIPTION_FIELDS)
        if not changes:
            raise HeadlessSubscriptionApiError("at least one subscription field is required")
        try:
            updated = update_subscription(self.context, subscription_id, changes)
        except KeyError as exc:
            raise HeadlessSubscriptionApiError("subscription not found") from exc
        except (TypeError, ValueError) as exc:
            raise HeadlessSubscriptionApiError(str(exc)) from exc
        return _public_subscription(updated)

    def delete(self, subscription_id: object) -> dict[str, Any]:
        raw = self._raw(subscription_id)
        clean = str(raw["id"])
        try:
            delete_subscription_v2_state(self.context, clean)
        except SubscriptionV2Error as exc:
            raise HeadlessSubscriptionApiError(str(exc)) from exc
        if not delete_subscription(self.context, clean):
            raise HeadlessSubscriptionApiError("subscription not found")
        return {"deleted": True, "subscriptionId": clean}

    def rules(self, subscription_id: object) -> dict[str, Any]:
        self._raw(subscription_id)
        try:
            return _public_rules(get_subscription_rules(self.context, subscription_id))
        except SubscriptionV2Error as exc:
            raise HeadlessSubscriptionApiError(str(exc)) from exc

    def configure_rules(self, subscription_id: object, payload: object) -> dict[str, Any]:
        self._raw(subscription_id)
        if isinstance(payload, Mapping) and "directory" in payload:
            raise HeadlessSubscriptionApiError("directory paths cannot be configured through the headless API")
        changes = _clean_changes(payload, _RULE_FIELDS)
        try:
            current = get_subscription_rules(self.context, subscription_id)
            configured = configure_subscription_rules(
                self.context,
                subscription_id,
                {**current, **changes, "directory": current.get("directory", "")},
            )
        except SubscriptionV2Error as exc:
            raise HeadlessSubscriptionApiError(str(exc)) from exc
        return _public_rules(configured)

    def items(
        self,
        subscription_id: object,
        *,
        state: object = "",
        present: bool | None = None,
        limit: object = 200,
    ) -> dict[str, Any]:
        self._raw(subscription_id)
        clean_state = str(state or "").strip().lower()
        if clean_state and clean_state not in ITEM_STATES:
            raise HeadlessSubscriptionApiError("invalid subscription item state")
        safe_limit = _bounded_int(limit, 200, 1, 500)
        try:
            rows = list_subscription_items(
                self.context,
                subscription_id,
                state=clean_state,
                present=present,
                limit=safe_limit,
            )
        except SubscriptionV2Error as exc:
            raise HeadlessSubscriptionApiError(str(exc)) from exc
        return {"items": [_public_item(row) for row in rows], "limit": safe_limit, "state": clean_state}

    def counts(self, subscription_id: object) -> dict[str, int]:
        self._raw(subscription_id)
        try:
            return subscription_item_counts(self.context, subscription_id)
        except SubscriptionV2Error as exc:
            raise HeadlessSubscriptionApiError(str(exc)) from exc

    def transition(self, subscription_id: object, payload: object) -> dict[str, Any]:
        self._raw(subscription_id)
        if not isinstance(payload, Mapping):
            raise HeadlessSubscriptionApiError("request must be a JSON object")
        entry_id = _safe_text(payload.get("entryId"), 240)
        state = _safe_text(payload.get("state"), 24).lower()
        reason = _safe_text(payload.get("reason"), 240)
        if not entry_id or state not in ITEM_STATES:
            raise HeadlessSubscriptionApiError("entryId and a valid state are required")
        try:
            updated = transition_subscription_item(
                self.context,
                subscription_id,
                entry_id,
                state,
                reason=reason or "api",
            )
        except SubscriptionV2Error as exc:
            raise HeadlessSubscriptionApiError(str(exc)) from exc
        return _public_item(updated)

    def reconcile(self, subscription_id: object, payload: object) -> dict[str, Any]:
        self._raw(subscription_id)
        if not isinstance(payload, Mapping):
            raise HeadlessSubscriptionApiError("request must be a JSON object")
        unknown = sorted(str(key) for key in payload if str(key) not in {"retryFailed", "maxAttempts"})
        if unknown:
            raise HeadlessSubscriptionApiError(f"unsupported fields: {', '.join(unknown[:8])}")
        retry_failed = bool(payload.get("retryFailed", False))
        max_attempts = _bounded_int(payload.get("maxAttempts"), 3, 1, 20)
        try:
            result = reconcile_subscription_items(
                self.context,
                subscription_id,
                retry_failed=retry_failed,
                max_attempts=max_attempts,
            )
        except SubscriptionV2Error as exc:
            raise HeadlessSubscriptionApiError(str(exc)) from exc
        return result.public_payload()


def run_headless_subscription_api_self_test() -> None:
    import tempfile

    from subscription_v2 import ingest_subscription_entries
    from subscriptions import SubscriptionEntry

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        program = root / "program"
        state = root / "state"
        program.mkdir()
        state.mkdir()
        context = HeadlessSubscriptionContext(program, state)
        api = HeadlessSubscriptionApi(context=context)
        created = api.create(
            {
                "sourceUrl": "https://example.com/channel?utm_source=demo&token=secret",
                "title": "Demo",
                "intervalMinutes": 60,
            }
        )
        assert "token=" not in created["sourceUrl"] and "utm_" not in created["sourceUrl"]
        assert "seenEntryIds" not in created
        subscription_id = created["id"]
        configured = api.configure_rules(
            subscription_id,
            {"manualReview": True, "tags": ["API"], "filename": "%(title)s.%(ext)s"},
        )
        assert configured["manualReview"] is True and configured["directoryConfigured"] is False
        ingest_subscription_entries(
            context,
            subscription_id,
            [SubscriptionEntry("one", "Episode", "https://example.com/watch?v=1&token=secret")],
        )
        rows = api.items(subscription_id)["items"]
        assert len(rows) == 1 and rows[0]["sourceUrl"] == "https://example.com/watch"
        assert "url" not in rows[0]
        approved = api.transition(subscription_id, {"entryId": "one", "state": "approved", "reason": "user"})
        assert approved["state"] == "approved"
        assert api.counts(subscription_id)["approved"] == 1
        detail = api.detail(subscription_id)
        assert detail["subscription"]["seenCount"] == 0 and "directory" not in detail["rules"]
        try:
            api.configure_rules(subscription_id, {"directory": str(root / "secret")})
        except HeadlessSubscriptionApiError:
            pass
        else:
            raise AssertionError("local directory path was accepted through headless subscription rules")
        deleted = api.delete(subscription_id)
        assert deleted["deleted"] is True and api.list_subscriptions()["total"] == 0
