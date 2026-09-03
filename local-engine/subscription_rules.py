from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from runtime_storage import state_dir as runtime_state_dir
from subscriptions import SubscriptionEntry

RULES_FILENAME = "subscription-rules.json"
ITEMS_DATABASE_FILENAME = "subscription-items.sqlite3"
MAX_KEYWORDS = 20
MAX_TAGS = 20
ALLOWED_ITEM_STATES = {"waiting", "queued", "downloading", "completed", "failed", "skipped"}


@dataclass(frozen=True)
class SubscriptionRules:
    subscription_id: str
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    latest_count: int = 0
    manual_review: bool = False
    directory_template: str = ""
    filename_template: str = ""

    def public_payload(self) -> dict[str, Any]:
        return {
            "subscriptionId": self.subscription_id,
            "includeKeywords": list(self.include_keywords),
            "excludeKeywords": list(self.exclude_keywords),
            "tags": list(self.tags),
            "latestCount": self.latest_count,
            "manualReview": self.manual_review,
            "directoryTemplate": self.directory_template,
            "filenameTemplate": self.filename_template,
        }


def _rules_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / RULES_FILENAME


def _items_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / ITEMS_DATABASE_FILENAME


def _items_connection(engine_module) -> sqlite3.Connection:
    connection = sqlite3.connect(_items_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_items (
            subscription_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL DEFAULT '',
            published TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'waiting',
            detail TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(subscription_id, entry_id)
        )
        """
    )
    return connection


def _clean_id(value: object) -> str:
    text = str(value or "").strip()[:100]
    return text if re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", text) else ""


def _clean_values(values: object, *, limit: int, max_length: int) -> tuple[str, ...]:
    result: list[str] = []
    for raw in values if isinstance(values, (list, tuple)) else ():
        text = " ".join(str(raw or "").split()).strip()[:max_length]
        if text and text.lower() not in {item.lower() for item in result}:
            result.append(text)
        if len(result) >= limit:
            break
    return tuple(result)


def _clean_template(value: object) -> str:
    text = str(value or "").strip()[:300]
    return text if not any(token in text for token in ("..", "\x00")) else ""


def _clean_rule(value: object) -> SubscriptionRules | None:
    if not isinstance(value, dict):
        return None
    subscription_id = _clean_id(value.get("subscriptionId"))
    if not subscription_id:
        return None
    try:
        latest = max(0, min(int(value.get("latestCount") or 0), 20))
    except (TypeError, ValueError):
        latest = 0
    return SubscriptionRules(
        subscription_id=subscription_id,
        include_keywords=_clean_values(value.get("includeKeywords"), limit=MAX_KEYWORDS, max_length=80),
        exclude_keywords=_clean_values(value.get("excludeKeywords"), limit=MAX_KEYWORDS, max_length=80),
        tags=_clean_values(value.get("tags"), limit=MAX_TAGS, max_length=60),
        latest_count=latest,
        manual_review=bool(value.get("manualReview", False)),
        directory_template=_clean_template(value.get("directoryTemplate")),
        filename_template=_clean_template(value.get("filenameTemplate")),
    )


def load_subscription_rules(engine_module) -> dict[str, SubscriptionRules]:
    try:
        payload = json.loads(_rules_path(engine_module).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    result: dict[str, SubscriptionRules] = {}
    for row in payload if isinstance(payload, list) else []:
        cleaned = _clean_rule(row)
        if cleaned is not None:
            result[cleaned.subscription_id] = cleaned
    return result


def get_subscription_rules(engine_module, subscription_id: object) -> SubscriptionRules:
    clean_id = _clean_id(subscription_id)
    return load_subscription_rules(engine_module).get(clean_id, SubscriptionRules(clean_id))


def save_subscription_rules(engine_module, rules: SubscriptionRules) -> SubscriptionRules:
    cleaned = _clean_rule(rules.public_payload())
    if cleaned is None:
        raise ValueError("Invalid subscription rules")
    existing = load_subscription_rules(engine_module)
    existing[cleaned.subscription_id] = cleaned
    path = _rules_path(engine_module)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps([item.public_payload() for item in existing.values()], ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return cleaned


def filter_subscription_entries(rules: SubscriptionRules, entries: Iterable[SubscriptionEntry]) -> tuple[SubscriptionEntry, ...]:
    result: list[SubscriptionEntry] = []
    includes = tuple(item.lower() for item in rules.include_keywords)
    excludes = tuple(item.lower() for item in rules.exclude_keywords)
    for entry in entries:
        haystack = f"{entry.title} {entry.url}".lower()
        if includes and not any(keyword in haystack for keyword in includes):
            continue
        if excludes and any(keyword in haystack for keyword in excludes):
            continue
        result.append(entry)
    if rules.latest_count > 0:
        result = result[: rules.latest_count]
    return tuple(result)


def record_subscription_entries(engine_module, subscription_id: object, entries: Iterable[SubscriptionEntry], *, state: str = "waiting") -> int:
    clean_id = _clean_id(subscription_id)
    clean_state = state if state in ALLOWED_ITEM_STATES else "waiting"
    count = 0
    with closing(_items_connection(engine_module)) as connection:
        for entry in entries:
            connection.execute(
                """
                INSERT INTO subscription_items(subscription_id, entry_id, title, url, published, state)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(subscription_id, entry_id) DO UPDATE SET
                  title=excluded.title, url=excluded.url, published=excluded.published,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (clean_id, entry.entry_id[:240], entry.title[:300], entry.url[:1200], entry.published[:80], clean_state),
            )
            count += 1
        connection.commit()
    return count


def set_subscription_item_state(engine_module, subscription_id: object, entry_id: object, state: str, detail: object = "") -> None:
    clean_id = _clean_id(subscription_id)
    clean_state = state if state in ALLOWED_ITEM_STATES else "failed"
    with closing(_items_connection(engine_module)) as connection:
        connection.execute(
            "UPDATE subscription_items SET state=?, detail=?, updated_at=CURRENT_TIMESTAMP WHERE subscription_id=? AND entry_id=?",
            (clean_state, " ".join(str(detail or "").split())[:500], clean_id, str(entry_id or "")[:240]),
        )
        connection.commit()


def list_subscription_items(engine_module, subscription_id: object, *, limit: int = 200) -> list[dict[str, Any]]:
    clean_id = _clean_id(subscription_id)
    with closing(_items_connection(engine_module)) as connection:
        rows = connection.execute(
            "SELECT * FROM subscription_items WHERE subscription_id=? ORDER BY updated_at DESC LIMIT ?",
            (clean_id, max(1, min(int(limit), 1000))),
        ).fetchall()
    return [
        {
            "subscriptionId": str(row["subscription_id"]),
            "entryId": str(row["entry_id"]),
            "title": str(row["title"]),
            "url": str(row["url"]),
            "published": str(row["published"]),
            "state": str(row["state"]),
            "detail": str(row["detail"]),
        }
        for row in rows
    ]


def apply_rules_to_payload(payload: dict[str, Any], rules: SubscriptionRules) -> dict[str, Any]:
    result = dict(payload)
    if rules.tags:
        result["subscriptionTags"] = list(rules.tags)
    if rules.directory_template:
        result["subscriptionDirectoryTemplate"] = rules.directory_template
    if rules.filename_template:
        result["subscriptionFilenameTemplate"] = rules.filename_template
    return result


def run_subscription_rules_self_test() -> None:
    rules = SubscriptionRules("abc", include_keywords=("python",), exclude_keywords=("shorts",), latest_count=1)
    entries = (
        SubscriptionEntry("1", "Python tutorial", "https://example.com/1"),
        SubscriptionEntry("2", "Python Shorts", "https://example.com/2"),
        SubscriptionEntry("3", "Rust", "https://example.com/3"),
    )
    filtered = filter_subscription_entries(rules, entries)
    assert [item.entry_id for item in filtered] == ["1"]
    assert apply_rules_to_payload({"sourceUrl": "https://example.com"}, SubscriptionRules("abc", tags=("podcast",)))["subscriptionTags"] == ["podcast"]
