from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from runtime_storage import state_dir as runtime_state_dir
from subscriptions import SubscriptionEntry, build_subscription_download_payload, load_subscriptions

DATABASE_FILENAME = "subscription-v2.sqlite3"
SCHEMA_VERSION = 1
ITEM_STATES = frozenset({"waiting", "approved", "queued", "downloading", "completed", "failed", "skipped"})
MAX_RULE_TERMS = 30
MAX_TERM_CHARS = 80
MAX_TAGS = 30
MAX_ITEMS_PER_SYNC = 200
MAX_ITEM_TEXT = 500
MAX_DIRECTORY_CHARS = 1000
MAX_FILENAME_CHARS = 240
MAX_LIST_ITEMS = 2000
_TRANSITIONS = {
    "waiting": frozenset({"approved", "skipped"}),
    "approved": frozenset({"queued", "skipped", "waiting"}),
    "queued": frozenset({"downloading", "completed", "failed", "approved", "waiting", "skipped"}),
    "downloading": frozenset({"completed", "failed", "approved", "waiting"}),
    "completed": frozenset(),
    "failed": frozenset({"approved", "waiting", "skipped"}),
    "skipped": frozenset({"approved", "waiting"}),
}


class SubscriptionV2Error(RuntimeError):
    pass


@dataclass(frozen=True)
class ReconcileResult:
    subscription_id: str
    missing: int
    duplicates: int
    retried: int
    recovered: int

    def public_payload(self) -> dict[str, Any]:
        return {
            "subscriptionId": self.subscription_id,
            "missing": self.missing,
            "duplicates": self.duplicates,
            "retried": self.retried,
            "recovered": self.recovered,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()[:limit]


def _clean_subscription_id(value: object) -> str:
    clean = _safe_text(value, 80)
    if not clean:
        raise SubscriptionV2Error("subscription id is required")
    return clean


def _clean_entry_id(value: object) -> str:
    clean = _safe_text(value, 240)
    if not clean:
        raise SubscriptionV2Error("subscription item id is required")
    return clean


def _subscription(engine_module, subscription_id: object) -> dict[str, Any]:
    clean = _clean_subscription_id(subscription_id)
    item = next((row for row in load_subscriptions(engine_module) if str(row.get("id")) == clean), None)
    if item is None:
        raise SubscriptionV2Error("subscription not found")
    return item


def subscription_v2_database_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / DATABASE_FILENAME


def _connect(engine_module) -> sqlite3.Connection:
    connection = sqlite3.connect(subscription_v2_database_path(engine_module), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS subscription_v2_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS subscription_rules (
          subscription_id TEXT PRIMARY KEY,
          include_keywords_json TEXT NOT NULL DEFAULT '[]',
          exclude_keywords_json TEXT NOT NULL DEFAULT '[]',
          latest_n INTEGER NOT NULL DEFAULT 0,
          tags_json TEXT NOT NULL DEFAULT '[]',
          manual_review INTEGER NOT NULL DEFAULT 0,
          auto_download INTEGER NOT NULL DEFAULT 0,
          profile_id TEXT NOT NULL DEFAULT '',
          directory TEXT NOT NULL DEFAULT '',
          filename TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS subscription_items (
          subscription_id TEXT NOT NULL,
          entry_id TEXT NOT NULL,
          title TEXT NOT NULL DEFAULT '',
          url TEXT NOT NULL DEFAULT '',
          published TEXT NOT NULL DEFAULT '',
          tags_json TEXT NOT NULL DEFAULT '[]',
          state TEXT NOT NULL DEFAULT 'waiting',
          state_reason TEXT NOT NULL DEFAULT '',
          present INTEGER NOT NULL DEFAULT 1,
          missing_count INTEGER NOT NULL DEFAULT 0,
          attempts INTEGER NOT NULL DEFAULT 0,
          last_error TEXT NOT NULL DEFAULT '',
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(subscription_id, entry_id)
        );
        CREATE INDEX IF NOT EXISTS idx_subscription_items_state
          ON subscription_items(subscription_id, state, updated_at);
        CREATE INDEX IF NOT EXISTS idx_subscription_items_url
          ON subscription_items(subscription_id, url);
        CREATE INDEX IF NOT EXISTS idx_subscription_items_present
          ON subscription_items(subscription_id, present, missing_count);
        """
    )
    row = connection.execute("SELECT value FROM subscription_v2_meta WHERE key='schema_version'").fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO subscription_v2_meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
    else:
        try:
            version = int(row["value"])
        except (TypeError, ValueError) as exc:
            raise SubscriptionV2Error("subscription v2 schema version is invalid") from exc
        if version != SCHEMA_VERSION:
            raise SubscriptionV2Error(f"unsupported subscription v2 schema version: {version}")
    connection.commit()
    return connection


def _clean_terms(value: object, *, limit: int = MAX_RULE_TERMS) -> list[str]:
    if isinstance(value, str):
        source: Iterable[object] = value.replace("\r", "\n").replace(",", "\n").split("\n")
    elif isinstance(value, (list, tuple, set)):
        source = value
    else:
        source = ()
    result: list[str] = []
    seen: set[str] = set()
    for raw in source:
        term = _safe_text(raw, MAX_TERM_CHARS)
        folded = term.casefold()
        if term and folded not in seen:
            seen.add(folded)
            result.append(term)
        if len(result) >= limit:
            break
    return result


def _clean_directory(value: object) -> str:
    return str(value or "").replace("\x00", "").strip()[:MAX_DIRECTORY_CHARS]


def _clean_filename(value: object) -> str:
    raw = " ".join(str(value or "").replace("\x00", " ").split()).strip()[:MAX_FILENAME_CHARS]
    if "/" in raw or "\\" in raw or raw in {".", ".."}:
        raise SubscriptionV2Error("subscription filename must be a file template, not a path")
    return raw


def _clean_rules(values: Mapping[str, Any] | None, *, fallback_auto_download: bool) -> dict[str, Any]:
    raw = dict(values or {})
    try:
        latest_n = int(raw.get("latestN") or 0)
    except (TypeError, ValueError):
        latest_n = 0
    return {
        "includeKeywords": _clean_terms(raw.get("includeKeywords")),
        "excludeKeywords": _clean_terms(raw.get("excludeKeywords")),
        "latestN": max(0, min(latest_n, MAX_ITEMS_PER_SYNC)),
        "tags": _clean_terms(raw.get("tags"), limit=MAX_TAGS),
        "manualReview": bool(raw.get("manualReview", False)),
        "autoDownload": bool(raw.get("autoDownload", fallback_auto_download)),
        "profile": _safe_text(raw.get("profile"), 100),
        "directory": _clean_directory(raw.get("directory")),
        "filename": _clean_filename(raw.get("filename")),
    }


def configure_subscription_rules(engine_module, subscription_id: object, values: Mapping[str, Any]) -> dict[str, Any]:
    subscription = _subscription(engine_module, subscription_id)
    clean_id = str(subscription["id"])
    rules = _clean_rules(values, fallback_auto_download=bool(subscription.get("autoDownload", False)))
    with closing(_connect(engine_module)) as connection:
        connection.execute(
            """
            INSERT INTO subscription_rules(
              subscription_id,include_keywords_json,exclude_keywords_json,latest_n,tags_json,
              manual_review,auto_download,profile_id,directory,filename
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(subscription_id) DO UPDATE SET
              include_keywords_json=excluded.include_keywords_json,
              exclude_keywords_json=excluded.exclude_keywords_json,
              latest_n=excluded.latest_n,
              tags_json=excluded.tags_json,
              manual_review=excluded.manual_review,
              auto_download=excluded.auto_download,
              profile_id=excluded.profile_id,
              directory=excluded.directory,
              filename=excluded.filename,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                clean_id,
                json.dumps(rules["includeKeywords"], ensure_ascii=False, separators=(",", ":")),
                json.dumps(rules["excludeKeywords"], ensure_ascii=False, separators=(",", ":")),
                rules["latestN"],
                json.dumps(rules["tags"], ensure_ascii=False, separators=(",", ":")),
                1 if rules["manualReview"] else 0,
                1 if rules["autoDownload"] else 0,
                rules["profile"],
                rules["directory"],
                rules["filename"],
            ),
        )
        connection.commit()
    return rules


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        parsed = []
    return [str(item) for item in parsed if str(item)] if isinstance(parsed, list) else []


def get_subscription_rules(engine_module, subscription_id: object) -> dict[str, Any]:
    subscription = _subscription(engine_module, subscription_id)
    clean_id = str(subscription["id"])
    with closing(_connect(engine_module)) as connection:
        row = connection.execute("SELECT * FROM subscription_rules WHERE subscription_id=?", (clean_id,)).fetchone()
    if row is None:
        return _clean_rules({}, fallback_auto_download=bool(subscription.get("autoDownload", False)))
    return {
        "includeKeywords": _json_list(row["include_keywords_json"]),
        "excludeKeywords": _json_list(row["exclude_keywords_json"]),
        "latestN": max(0, min(int(row["latest_n"] or 0), MAX_ITEMS_PER_SYNC)),
        "tags": _json_list(row["tags_json"]),
        "manualReview": bool(row["manual_review"]),
        "autoDownload": bool(row["auto_download"]),
        "profile": str(row["profile_id"] or ""),
        "directory": str(row["directory"] or ""),
        "filename": str(row["filename"] or ""),
    }


def _rule_decision(rules: Mapping[str, Any], entry: SubscriptionEntry, index: int) -> tuple[str, str]:
    if not entry.url:
        return "skipped", "rule:no_url"
    latest_n = int(rules.get("latestN") or 0)
    if latest_n and index >= latest_n:
        return "skipped", "rule:latest_n"
    haystack = f"{entry.title} {entry.url}".casefold()
    excludes = [str(item).casefold() for item in rules.get("excludeKeywords", [])]
    if excludes and any(term in haystack for term in excludes):
        return "skipped", "rule:excluded_keyword"
    includes = [str(item).casefold() for item in rules.get("includeKeywords", [])]
    if includes and not any(term in haystack for term in includes):
        return "skipped", "rule:include_miss"
    if bool(rules.get("manualReview", False)):
        return "waiting", "rule:manual_review"
    if bool(rules.get("autoDownload", False)):
        return "approved", "rule:auto_download"
    return "waiting", "rule:waiting"


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "subscriptionId": str(row["subscription_id"]),
        "entryId": str(row["entry_id"]),
        "title": str(row["title"] or ""),
        "url": str(row["url"] or ""),
        "published": str(row["published"] or ""),
        "tags": _json_list(row["tags_json"]),
        "state": str(row["state"]),
        "stateReason": str(row["state_reason"] or ""),
        "present": bool(row["present"]),
        "missingCount": max(0, int(row["missing_count"] or 0)),
        "attempts": max(0, int(row["attempts"] or 0)),
        "lastError": str(row["last_error"] or ""),
        "firstSeenAt": str(row["first_seen_at"]),
        "lastSeenAt": str(row["last_seen_at"]),
    }


def ingest_subscription_entries(
    engine_module,
    subscription_id: object,
    entries: Iterable[SubscriptionEntry],
    *,
    observed_at: str | None = None,
) -> list[dict[str, Any]]:
    clean_id = str(_subscription(engine_module, subscription_id)["id"])
    rules = get_subscription_rules(engine_module, clean_id)
    timestamp = _safe_text(observed_at, 48) or _now_iso()
    source = list(entries)[:MAX_ITEMS_PER_SYNC]
    result_ids: list[str] = []
    with closing(_connect(engine_module)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE subscription_items SET present=0,missing_count=missing_count+1,updated_at=CURRENT_TIMESTAMP WHERE subscription_id=?",
            (clean_id,),
        )
        for index, entry in enumerate(source):
            entry_id = _clean_entry_id(entry.entry_id)
            title = _safe_text(entry.title, MAX_ITEM_TEXT)
            url = _safe_text(entry.url, 1200)
            published = _safe_text(entry.published, 80)
            normalized = SubscriptionEntry(entry_id, title, url, published)
            state, reason = _rule_decision(rules, normalized, index)
            if url:
                duplicate = connection.execute(
                    "SELECT entry_id FROM subscription_items WHERE subscription_id=? AND url=? AND entry_id<>? ORDER BY first_seen_at,entry_id LIMIT 1",
                    (clean_id, url, entry_id),
                ).fetchone()
                if duplicate is not None:
                    state, reason = "skipped", f"duplicate:{duplicate['entry_id']}"
            existing = connection.execute(
                "SELECT state,state_reason FROM subscription_items WHERE subscription_id=? AND entry_id=?",
                (clean_id, entry_id),
            ).fetchone()
            if existing is not None:
                current_state = str(existing["state"])
                current_reason = str(existing["state_reason"] or "")
                if current_state in {"completed", "failed", "queued", "downloading"}:
                    state, reason = current_state, current_reason
                elif current_state in {"waiting", "approved", "skipped"} and not (
                    current_reason.startswith("rule:") or current_reason.startswith("duplicate:")
                ):
                    state, reason = current_state, current_reason
                connection.execute(
                    """
                    UPDATE subscription_items
                    SET title=?,url=?,published=?,tags_json=?,state=?,state_reason=?,present=1,missing_count=0,
                        last_seen_at=?,updated_at=CURRENT_TIMESTAMP
                    WHERE subscription_id=? AND entry_id=?
                    """,
                    (
                        title,
                        url,
                        published,
                        json.dumps(rules["tags"], ensure_ascii=False, separators=(",", ":")),
                        state,
                        reason,
                        timestamp,
                        clean_id,
                        entry_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO subscription_items(
                      subscription_id,entry_id,title,url,published,tags_json,state,state_reason,
                      present,missing_count,attempts,last_error,first_seen_at,last_seen_at
                    ) VALUES(?,?,?,?,?,?,?,?,1,0,0,'',?,?)
                    """,
                    (
                        clean_id,
                        entry_id,
                        title,
                        url,
                        published,
                        json.dumps(rules["tags"], ensure_ascii=False, separators=(",", ":")),
                        state,
                        reason,
                        timestamp,
                        timestamp,
                    ),
                )
            result_ids.append(entry_id)
        connection.commit()
        result: list[dict[str, Any]] = []
        for entry_id in result_ids:
            row = connection.execute(
                "SELECT * FROM subscription_items WHERE subscription_id=? AND entry_id=?",
                (clean_id, entry_id),
            ).fetchone()
            if row is not None:
                result.append(_row_payload(row))
    return result


def list_subscription_items(
    engine_module,
    subscription_id: object,
    *,
    state: object = "",
    present: bool | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    clean_id = str(_subscription(engine_module, subscription_id)["id"])
    clean_state = str(state or "").strip().lower()
    if clean_state and clean_state not in ITEM_STATES:
        raise SubscriptionV2Error("invalid subscription item state")
    safe_limit = max(1, min(int(limit), MAX_LIST_ITEMS))
    with closing(_connect(engine_module)) as connection:
        if clean_state and present is not None:
            rows = connection.execute(
                "SELECT * FROM subscription_items WHERE subscription_id=? AND state=? AND present=? ORDER BY first_seen_at DESC,entry_id LIMIT ?",
                (clean_id, clean_state, 1 if present else 0, safe_limit),
            ).fetchall()
        elif clean_state:
            rows = connection.execute(
                "SELECT * FROM subscription_items WHERE subscription_id=? AND state=? ORDER BY first_seen_at DESC,entry_id LIMIT ?",
                (clean_id, clean_state, safe_limit),
            ).fetchall()
        elif present is not None:
            rows = connection.execute(
                "SELECT * FROM subscription_items WHERE subscription_id=? AND present=? ORDER BY first_seen_at DESC,entry_id LIMIT ?",
                (clean_id, 1 if present else 0, safe_limit),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM subscription_items WHERE subscription_id=? ORDER BY first_seen_at DESC,entry_id LIMIT ?",
                (clean_id, safe_limit),
            ).fetchall()
    return [_row_payload(row) for row in rows]


def transition_subscription_item(
    engine_module,
    subscription_id: object,
    entry_id: object,
    new_state: object,
    *,
    reason: object = "",
    error: object = "",
) -> dict[str, Any]:
    clean_id = str(_subscription(engine_module, subscription_id)["id"])
    clean_entry = _clean_entry_id(entry_id)
    target = str(new_state or "").strip().lower()
    if target not in ITEM_STATES:
        raise SubscriptionV2Error("invalid subscription item state")
    with closing(_connect(engine_module)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM subscription_items WHERE subscription_id=? AND entry_id=?",
            (clean_id, clean_entry),
        ).fetchone()
        if row is None:
            raise SubscriptionV2Error("subscription item not found")
        current = str(row["state"])
        if target != current and target not in _TRANSITIONS[current]:
            raise SubscriptionV2Error(f"invalid subscription item transition: {current} -> {target}")
        connection.execute(
            "UPDATE subscription_items SET state=?,state_reason=?,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE subscription_id=? AND entry_id=?",
            (target, _safe_text(reason, 240), _safe_text(error, 1000), clean_id, clean_entry),
        )
        connection.commit()
        updated = connection.execute(
            "SELECT * FROM subscription_items WHERE subscription_id=? AND entry_id=?",
            (clean_id, clean_entry),
        ).fetchone()
    assert updated is not None
    return _row_payload(updated)


def claim_approved_items(engine_module, subscription_id: object, *, limit: int = 5) -> list[dict[str, Any]]:
    subscription = _subscription(engine_module, subscription_id)
    clean_id = str(subscription["id"])
    rules = get_subscription_rules(engine_module, clean_id)
    safe_limit = max(1, min(int(limit), 20))
    claimed: list[dict[str, Any]] = []
    with closing(_connect(engine_module)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            "SELECT * FROM subscription_items WHERE subscription_id=? AND state='approved' ORDER BY first_seen_at,entry_id LIMIT ?",
            (clean_id, safe_limit),
        ).fetchall()
        for row in rows:
            connection.execute(
                "UPDATE subscription_items SET state='queued',state_reason='claim',attempts=attempts+1,last_error='',updated_at=CURRENT_TIMESTAMP WHERE subscription_id=? AND entry_id=? AND state='approved'",
                (clean_id, row["entry_id"]),
            )
        connection.commit()
        for row in rows:
            updated = connection.execute(
                "SELECT * FROM subscription_items WHERE subscription_id=? AND entry_id=?",
                (clean_id, row["entry_id"]),
            ).fetchone()
            if updated is None or updated["state"] != "queued":
                continue
            item = _row_payload(updated)
            entry = SubscriptionEntry(item["entryId"], item["title"], item["url"], item["published"])
            payload = build_subscription_download_payload(subscription, entry)
            if payload is None:
                continue
            payload.update(
                {
                    "subscriptionId": clean_id,
                    "subscriptionEntryId": item["entryId"],
                    "profileId": rules["profile"],
                    "outputDirectory": rules["directory"],
                    "filenameTemplate": rules["filename"],
                    "tags": list(item["tags"]),
                }
            )
            claimed.append({"item": item, "download": payload})
    return claimed


def reconcile_subscription_items(
    engine_module,
    subscription_id: object,
    *,
    task_states: Mapping[str, str] | None = None,
    retry_failed: bool = False,
    max_attempts: int = 3,
) -> ReconcileResult:
    clean_id = str(_subscription(engine_module, subscription_id)["id"])
    rules = get_subscription_rules(engine_module, clean_id)
    retry_limit = max(1, min(int(max_attempts), 20))
    normalized_tasks = {
        _safe_text(key, 240): str(value or "").strip().lower()
        for key, value in (task_states or {}).items()
        if _safe_text(key, 240)
    }
    duplicates = 0
    retried = 0
    recovered = 0
    with closing(_connect(engine_module)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        duplicate_rows = connection.execute(
            "SELECT url FROM subscription_items WHERE subscription_id=? AND url<>'' GROUP BY url HAVING COUNT(*)>1",
            (clean_id,),
        ).fetchall()
        for duplicate_row in duplicate_rows:
            rows = connection.execute(
                "SELECT entry_id,state FROM subscription_items WHERE subscription_id=? AND url=? ORDER BY first_seen_at,entry_id",
                (clean_id, duplicate_row["url"]),
            ).fetchall()
            keeper = str(rows[0]["entry_id"])
            for row in rows[1:]:
                if str(row["state"]) in {"completed", "downloading"}:
                    continue
                connection.execute(
                    "UPDATE subscription_items SET state='skipped',state_reason=?,updated_at=CURRENT_TIMESTAMP WHERE subscription_id=? AND entry_id=?",
                    (f"duplicate:{keeper}", clean_id, row["entry_id"]),
                )
                duplicates += 1

        if retry_failed:
            rows = connection.execute(
                "SELECT entry_id,attempts FROM subscription_items WHERE subscription_id=? AND state='failed'",
                (clean_id,),
            ).fetchall()
            retry_state = "waiting" if rules["manualReview"] or not rules["autoDownload"] else "approved"
            for row in rows:
                if int(row["attempts"] or 0) >= retry_limit:
                    continue
                connection.execute(
                    "UPDATE subscription_items SET state=?,state_reason='reconcile:retry',last_error='',updated_at=CURRENT_TIMESTAMP WHERE subscription_id=? AND entry_id=?",
                    (retry_state, clean_id, row["entry_id"]),
                )
                retried += 1

        if task_states is not None:
            rows = connection.execute(
                "SELECT entry_id,state FROM subscription_items WHERE subscription_id=? AND state IN ('queued','downloading')",
                (clean_id,),
            ).fetchall()
            fallback = "waiting" if rules["manualReview"] or not rules["autoDownload"] else "approved"
            state_map = {
                "queued": "queued",
                "waiting": "queued",
                "running": "downloading",
                "downloading": "downloading",
                "completed": "completed",
                "failed": "failed",
                "cancelled": "failed",
            }
            for row in rows:
                entry_id = str(row["entry_id"])
                if entry_id not in normalized_tasks:
                    connection.execute(
                        "UPDATE subscription_items SET state=?,state_reason='reconcile:missing_task',updated_at=CURRENT_TIMESTAMP WHERE subscription_id=? AND entry_id=?",
                        (fallback, clean_id, entry_id),
                    )
                    recovered += 1
                    continue
                target = state_map.get(normalized_tasks[entry_id])
                if target and target != row["state"]:
                    error = "task cancelled" if normalized_tasks[entry_id] == "cancelled" else ""
                    connection.execute(
                        "UPDATE subscription_items SET state=?,state_reason='reconcile:task',last_error=?,updated_at=CURRENT_TIMESTAMP WHERE subscription_id=? AND entry_id=?",
                        (target, error, clean_id, entry_id),
                    )
        missing = int(
            connection.execute(
                "SELECT COUNT(*) FROM subscription_items WHERE subscription_id=? AND present=0",
                (clean_id,),
            ).fetchone()[0]
        )
        connection.commit()
    return ReconcileResult(clean_id, missing, duplicates, retried, recovered)


def subscription_item_counts(engine_module, subscription_id: object) -> dict[str, int]:
    clean_id = str(_subscription(engine_module, subscription_id)["id"])
    counts = {state: 0 for state in sorted(ITEM_STATES)}
    with closing(_connect(engine_module)) as connection:
        rows = connection.execute(
            "SELECT state,COUNT(*) AS total FROM subscription_items WHERE subscription_id=? GROUP BY state",
            (clean_id,),
        ).fetchall()
    for row in rows:
        counts[str(row["state"])] = int(row["total"])
    return counts


def delete_subscription_v2_state(engine_module, subscription_id: object) -> None:
    clean_id = _clean_subscription_id(subscription_id)
    with closing(_connect(engine_module)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM subscription_items WHERE subscription_id=?", (clean_id,))
        connection.execute("DELETE FROM subscription_rules WHERE subscription_id=?", (clean_id,))
        connection.commit()


def run_subscription_v2_self_test() -> None:
    import tempfile

    from subscriptions import add_subscription

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        state.mkdir()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return state

        subscription = add_subscription(
            Engine,
            {"sourceUrl": "https://example.com/channel", "title": "Demo", "autoDownload": False},
        )
        rules = configure_subscription_rules(
            Engine,
            subscription["id"],
            {
                "includeKeywords": ["Galaxy"],
                "excludeKeywords": ["Trailer"],
                "latestN": 3,
                "tags": ["Tech", "Galaxy", "tech"],
                "manualReview": True,
                "autoDownload": True,
                "profile": "hd-main",
                "directory": str(root / "downloads"),
                "filename": "%(title)s [%(id)s].%(ext)s",
            },
        )
        assert rules["tags"] == ["Tech", "Galaxy"] and rules["latestN"] == 3
        entries = (
            SubscriptionEntry("one", "Galaxy Episode One", "https://example.com/watch/1"),
            SubscriptionEntry("two", "Galaxy Trailer", "https://example.com/watch/2"),
            SubscriptionEntry("three", "Other Episode", "https://example.com/watch/3"),
            SubscriptionEntry("four", "Galaxy Episode Four", "https://example.com/watch/4"),
        )
        ingested = ingest_subscription_entries(Engine, subscription["id"], entries, observed_at="2026-09-03T00:00:00Z")
        assert [item["state"] for item in ingested] == ["waiting", "skipped", "skipped", "skipped"]
        assert ingested[1]["stateReason"] == "rule:excluded_keyword"
        assert ingested[3]["stateReason"] == "rule:latest_n"

        approved = transition_subscription_item(Engine, subscription["id"], "one", "approved", reason="user")
        assert approved["state"] == "approved"
        claimed = claim_approved_items(Engine, subscription["id"])
        assert len(claimed) == 1
        assert claimed[0]["item"]["state"] == "queued" and claimed[0]["item"]["attempts"] == 1
        assert claimed[0]["download"]["profileId"] == "hd-main"
        assert claimed[0]["download"]["filenameTemplate"].startswith("%(title)s")
        transition_subscription_item(Engine, subscription["id"], "one", "downloading", reason="task")
        failed = transition_subscription_item(Engine, subscription["id"], "one", "failed", reason="task", error="network")
        assert failed["lastError"] == "network"
        retried = reconcile_subscription_items(Engine, subscription["id"], retry_failed=True, max_attempts=3)
        assert retried.retried == 1
        one = next(item for item in list_subscription_items(Engine, subscription["id"]) if item["entryId"] == "one")
        assert one["state"] == "waiting"

        configure_subscription_rules(
            Engine,
            subscription["id"],
            {**rules, "manualReview": False, "autoDownload": True, "latestN": 0},
        )
        transition_subscription_item(Engine, subscription["id"], "one", "approved", reason="user")
        claim_approved_items(Engine, subscription["id"])
        recovered = reconcile_subscription_items(Engine, subscription["id"], task_states={})
        assert recovered.recovered == 1
        one = next(item for item in list_subscription_items(Engine, subscription["id"]) if item["entryId"] == "one")
        assert one["state"] == "approved" and one["stateReason"] == "reconcile:missing_task"

        changed = SubscriptionEntry("one", "Galaxy Episode One", "https://example.com/watch/1-new")
        duplicate = SubscriptionEntry("five", "Galaxy Episode Copy", "https://example.com/watch/1-new")
        reingested = ingest_subscription_entries(
            Engine,
            subscription["id"],
            (changed, duplicate),
            observed_at="2026-09-04T00:00:00Z",
        )
        assert reingested[0]["url"].endswith("1-new")
        assert reingested[1]["state"] == "skipped" and reingested[1]["stateReason"].startswith("duplicate:")
        missing = list_subscription_items(Engine, subscription["id"], present=False)
        assert any(item["entryId"] == "two" and item["missingCount"] == 1 for item in missing)
        summary = reconcile_subscription_items(Engine, subscription["id"])
        assert summary.missing >= 1 and summary.duplicates >= 1
        counts = subscription_item_counts(Engine, subscription["id"])
        assert sum(counts.values()) == 5

        try:
            configure_subscription_rules(Engine, subscription["id"], {"filename": "../escape/%(title)s"})
        except SubscriptionV2Error:
            pass
        else:
            raise AssertionError("unsafe subscription filename path was accepted")

        delete_subscription_v2_state(Engine, subscription["id"])
        assert list_subscription_items(Engine, subscription["id"]) == []
