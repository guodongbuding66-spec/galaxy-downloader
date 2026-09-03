from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from runtime_storage import state_dir as runtime_state_dir

SUBSCRIPTIONS_FILENAME = "subscriptions.json"
SCHEMA_VERSION = 1
MAX_SUBSCRIPTIONS = 200
MAX_SEEN_ENTRY_IDS = 800
MAX_DISCOVERED_ENTRIES = 50
ALLOWED_INTERVALS = (15, 30, 60, 180, 360, 720, 1440)
_SECRET_QUERY_TOKENS = (
    "token", "auth", "authorization", "cookie", "session", "secret",
    "signature", "sig", "credential", "password", "passwd", "x-amz-",
)
_TRACKING_QUERY_KEYS = {"si", "feature", "ref", "referrer", "source", "fbclid", "gclid"}
_LOCK = threading.RLock()


@dataclass(frozen=True)
class SubscriptionEntry:
    entry_id: str
    title: str
    url: str
    published: str = ""

    def public_payload(self) -> dict[str, str]:
        return {
            "id": self.entry_id,
            "title": self.title,
            "url": self.url,
            "published": self.published,
        }


@dataclass(frozen=True)
class SubscriptionCheckResult:
    subscription_id: str
    title: str
    baseline: bool
    entries: tuple[SubscriptionEntry, ...]
    new_entries: tuple[SubscriptionEntry, ...]


def subscriptions_path(engine_module) -> Path:
    target = runtime_state_dir(engine_module)
    target.mkdir(parents=True, exist_ok=True)
    return target / SUBSCRIPTIONS_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _normalize_subscription_url(value: object) -> str:
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise ValueError("A valid http(s) subscription URL is required") from exc
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        raise ValueError("A valid http(s) subscription URL is required")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Credential-bearing subscription URLs are not allowed")
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise ValueError("Local subscription URLs are not allowed")
    host = hostname
    try:
        if parsed.port:
            host = f"{host}:{parsed.port}"
    except ValueError as exc:
        raise ValueError("Invalid subscription URL port") from exc

    clean_pairs: list[tuple[str, str]] = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=False):
        lowered = key.lower().strip()
        if not lowered or lowered.startswith("utm_") or lowered in _TRACKING_QUERY_KEYS:
            continue
        if any(token in lowered for token in _SECRET_QUERY_TOKENS):
            continue
        clean_pairs.append((key[:80], item[:300]))
        if len(clean_pairs) >= 20:
            break
    return urlunsplit((parsed.scheme.lower(), host, parsed.path or "/", urlencode(clean_pairs), ""))[:1200]


def _default_state() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "subscriptions": []}


def _clean_seen_ids(value: object) -> list[str]:
    result: list[str] = []
    for raw in value if isinstance(value, (list, tuple)) else ():
        text = _safe_text(raw, 200)
        if text and text not in result:
            result.append(text)
        if len(result) >= MAX_SEEN_ENTRY_IDS:
            break
    return result


def _clean_subscription(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    try:
        source_url = _normalize_subscription_url(value.get("sourceUrl"))
    except ValueError:
        return None
    subscription_id = _safe_text(value.get("id"), 80) or uuid.uuid4().hex
    browser = _safe_text(value.get("browser"), 24).lower() or "none"
    if browser not in {"none", "edge", "chrome", "firefox", "brave", "chromium", "opera", "vivaldi"}:
        browser = "none"
    try:
        interval = int(value.get("intervalMinutes") or 60)
    except (TypeError, ValueError):
        interval = 60
    interval = min(ALLOWED_INTERVALS, key=lambda candidate: abs(candidate - interval))
    return {
        "id": subscription_id,
        "sourceUrl": source_url,
        "title": _safe_text(value.get("title"), 180),
        "browser": browser,
        "enabled": bool(value.get("enabled", True)),
        "autoDownload": bool(value.get("autoDownload", False)),
        "intervalMinutes": interval,
        "videoQuality": _safe_text(value.get("videoQuality"), 40) or "best",
        "audioQuality": _safe_text(value.get("audioQuality"), 40) or "best",
        "includeAudio": bool(value.get("includeAudio", True)),
        "seenEntryIds": _clean_seen_ids(value.get("seenEntryIds")),
        "lastCheckedAt": _safe_text(value.get("lastCheckedAt"), 48),
        "lastError": _safe_text(value.get("lastError"), 400),
        "createdAt": _safe_text(value.get("createdAt"), 48) or _now_iso(),
    }


def _load_state(engine_module) -> dict[str, Any]:
    path = subscriptions_path(engine_module)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _default_state()
    if not isinstance(raw, dict) or int(raw.get("version") or 0) != SCHEMA_VERSION:
        return _default_state()
    cleaned: list[dict[str, Any]] = []
    for value in raw.get("subscriptions") if isinstance(raw.get("subscriptions"), list) else []:
        item = _clean_subscription(value)
        if item is not None and not any(existing["id"] == item["id"] for existing in cleaned):
            cleaned.append(item)
        if len(cleaned) >= MAX_SUBSCRIPTIONS:
            break
    return {"version": SCHEMA_VERSION, "subscriptions": cleaned}


def _write_state(engine_module, state: dict[str, Any]) -> None:
    path = subscriptions_path(engine_module)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_subscriptions(engine_module) -> list[dict[str, Any]]:
    with _LOCK:
        return [dict(item) for item in _load_state(engine_module)["subscriptions"]]


def add_subscription(engine_module, values: dict[str, Any]) -> dict[str, Any]:
    candidate = _clean_subscription({**values, "id": uuid.uuid4().hex, "createdAt": _now_iso()})
    if candidate is None:
        raise ValueError("Invalid subscription settings")
    with _LOCK:
        state = _load_state(engine_module)
        subscriptions = state["subscriptions"]
        if len(subscriptions) >= MAX_SUBSCRIPTIONS:
            raise ValueError("Subscription limit reached")
        if any(item["sourceUrl"] == candidate["sourceUrl"] for item in subscriptions):
            raise ValueError("This source is already subscribed")
        subscriptions.append(candidate)
        _write_state(engine_module, state)
    return dict(candidate)


def update_subscription(engine_module, subscription_id: object, changes: dict[str, Any]) -> dict[str, Any]:
    clean_id = _safe_text(subscription_id, 80)
    with _LOCK:
        state = _load_state(engine_module)
        for index, current in enumerate(state["subscriptions"]):
            if current["id"] != clean_id:
                continue
            candidate = _clean_subscription({**current, **changes, "id": current["id"], "createdAt": current["createdAt"]})
            if candidate is None:
                raise ValueError("Invalid subscription settings")
            if any(item["id"] != clean_id and item["sourceUrl"] == candidate["sourceUrl"] for item in state["subscriptions"]):
                raise ValueError("This source is already subscribed")
            state["subscriptions"][index] = candidate
            _write_state(engine_module, state)
            return dict(candidate)
    raise KeyError("Subscription not found")


def delete_subscription(engine_module, subscription_id: object) -> bool:
    clean_id = _safe_text(subscription_id, 80)
    with _LOCK:
        state = _load_state(engine_module)
        before = len(state["subscriptions"])
        state["subscriptions"] = [item for item in state["subscriptions"] if item["id"] != clean_id]
        if len(state["subscriptions"]) == before:
            return False
        _write_state(engine_module, state)
        return True


def _entry_url(entry: dict[str, Any]) -> str:
    for key in ("webpage_url", "original_url", "url"):
        value = str(entry.get(key) or "").strip()
        try:
            parsed = urlsplit(value)
        except ValueError:
            continue
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
            return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))[:1200]
    entry_id = _safe_text(entry.get("id"), 200)
    extractor = _safe_text(entry.get("extractor_key") or entry.get("ie_key") or entry.get("extractor"), 80).lower()
    if entry_id and "youtube" in extractor:
        return f"https://www.youtube.com/watch?v={entry_id}"
    return ""


def parse_subscription_payload(payload: object) -> tuple[str, tuple[SubscriptionEntry, ...]]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid subscription metadata")
    title = _safe_text(payload.get("title") or payload.get("channel") or payload.get("uploader"), 180)
    rows = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    entries: list[SubscriptionEntry] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        raw_id = _safe_text(row.get("id"), 200)
        extractor = _safe_text(row.get("extractor_key") or row.get("ie_key") or row.get("extractor"), 80).lower()
        url = _entry_url(row)
        entry_id = f"{extractor}:{raw_id}" if extractor and raw_id else raw_id or url
        if not entry_id:
            continue
        if any(item.entry_id == entry_id for item in entries):
            continue
        published = _safe_text(row.get("upload_date") or row.get("release_date") or row.get("timestamp"), 40)
        entries.append(
            SubscriptionEntry(
                entry_id=entry_id,
                title=_safe_text(row.get("title"), 220) or f"Item {index + 1}",
                url=url,
                published=published,
            )
        )
        if len(entries) >= MAX_DISCOVERED_ENTRIES:
            break
    return title, tuple(entries)


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def inspect_subscription_source(engine_module, subscription: dict[str, Any], *, max_entries: int = 20) -> tuple[str, tuple[SubscriptionEntry, ...]]:
    source_url = engine_module._validated_source_url(str(subscription.get("sourceUrl") or ""))
    executable = engine_module.external_ytdlp_path(engine_module.app_dir())
    if executable is None:
        raise RuntimeError("yt-dlp is unavailable")
    limit = max(1, min(int(max_entries), MAX_DISCOVERED_ENTRIES))
    command = [
        str(executable),
        "--ignore-config",
        "--flat-playlist",
        "--playlist-end", str(limit),
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
    ]
    browser = str(subscription.get("browser") or "none")
    if browser != "none":
        command.extend(["--cookies-from-browser", browser])
    command.extend(["--", source_url])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        creationflags=_creation_flags(),
        check=False,
    )
    if result.returncode != 0:
        detail = _safe_text(result.stderr or result.stdout or "yt-dlp subscription check failed", 400)
        raise RuntimeError(detail)
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("yt-dlp returned invalid subscription metadata") from exc
    return parse_subscription_payload(payload)


def _acknowledge_ids_in_state(state: dict[str, Any], subscription_id: str, entry_ids: Iterable[object]) -> None:
    new_ids = _clean_seen_ids(list(entry_ids))
    if not new_ids:
        return
    for item in state["subscriptions"]:
        if item["id"] != subscription_id:
            continue
        merged: list[str] = []
        for value in [*new_ids, *item.get("seenEntryIds", [])]:
            if value and value not in merged:
                merged.append(value)
            if len(merged) >= MAX_SEEN_ENTRY_IDS:
                break
        item["seenEntryIds"] = merged
        return


def acknowledge_subscription_entries(engine_module, subscription_id: object, entry_ids: Iterable[object]) -> None:
    clean_id = _safe_text(subscription_id, 80)
    with _LOCK:
        state = _load_state(engine_module)
        _acknowledge_ids_in_state(state, clean_id, entry_ids)
        _write_state(engine_module, state)


def check_subscription(
    engine_module,
    subscription_id: object,
    *,
    mark_seen: bool = True,
    max_entries: int = 20,
) -> SubscriptionCheckResult:
    clean_id = _safe_text(subscription_id, 80)
    with _LOCK:
        current = next((dict(item) for item in _load_state(engine_module)["subscriptions"] if item["id"] == clean_id), None)
    if current is None:
        raise KeyError("Subscription not found")

    checked_at = _now_iso()
    try:
        discovered_title, entries = inspect_subscription_source(engine_module, current, max_entries=max_entries)
    except Exception as exc:
        with _LOCK:
            state = _load_state(engine_module)
            for item in state["subscriptions"]:
                if item["id"] == clean_id:
                    item["lastCheckedAt"] = checked_at
                    item["lastError"] = _safe_text(exc, 400)
                    break
            _write_state(engine_module, state)
        raise

    seen = set(current.get("seenEntryIds") or [])
    baseline = not bool(seen)
    new_entries = tuple(entry for entry in entries if entry.entry_id not in seen)
    if baseline:
        new_entries = ()

    with _LOCK:
        state = _load_state(engine_module)
        for item in state["subscriptions"]:
            if item["id"] != clean_id:
                continue
            if discovered_title and not item.get("title"):
                item["title"] = discovered_title
            item["lastCheckedAt"] = checked_at
            item["lastError"] = ""
            if baseline:
                _acknowledge_ids_in_state(state, clean_id, [entry.entry_id for entry in entries])
            elif mark_seen:
                _acknowledge_ids_in_state(state, clean_id, [entry.entry_id for entry in new_entries])
            break
        _write_state(engine_module, state)

    title = current.get("title") or discovered_title or current.get("sourceUrl") or "Subscription"
    return SubscriptionCheckResult(
        subscription_id=clean_id,
        title=str(title),
        baseline=baseline,
        entries=entries,
        new_entries=new_entries,
    )


def build_subscription_download_payload(subscription: dict[str, Any], entry: SubscriptionEntry) -> dict[str, Any] | None:
    if not entry.url:
        return None
    return {
        "sourceUrl": entry.url,
        "videoQuality": str(subscription.get("videoQuality") or "best"),
        "audioQuality": str(subscription.get("audioQuality") or "best"),
        "includeAudio": bool(subscription.get("includeAudio", True)),
        "browser": str(subscription.get("browser") or "none"),
        "collectionMode": "single",
        "playlist": False,
        "skipPreviouslyDownloaded": False,
        "displayTitle": entry.title[:120],
    }


def run_subscriptions_self_test() -> None:
    import tempfile

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

        item = add_subscription(
            Engine,
            {
                "sourceUrl": "https://www.youtube.com/playlist?list=PL123&utm_source=test&token=secret",
                "title": "Demo",
                "intervalMinutes": 70,
            },
        )
        assert "token=" not in item["sourceUrl"]
        assert "utm_" not in item["sourceUrl"]
        assert "list=PL123" in item["sourceUrl"]
        assert item["intervalMinutes"] == 60
        assert len(load_subscriptions(Engine)) == 1
        updated = update_subscription(Engine, item["id"], {"autoDownload": True, "intervalMinutes": 15})
        assert updated["autoDownload"] is True and updated["intervalMinutes"] == 15

        title, entries = parse_subscription_payload(
            {
                "title": "Channel",
                "entries": [
                    {"id": "abc", "title": "One", "ie_key": "Youtube", "url": "abc"},
                    {"id": "def", "title": "Two", "webpage_url": "https://example.com/watch/def"},
                ],
            }
        )
        assert title == "Channel"
        assert entries[0].url == "https://www.youtube.com/watch?v=abc"
        assert entries[1].url == "https://example.com/watch/def"
        payload = build_subscription_download_payload(updated, entries[0])
        assert payload and payload["sourceUrl"].startswith("https://www.youtube.com/watch")
        acknowledge_subscription_entries(Engine, item["id"], [entries[0].entry_id, entries[0].entry_id])
        assert load_subscriptions(Engine)[0]["seenEntryIds"] == [entries[0].entry_id]
        assert delete_subscription(Engine, item["id"]) is True
        assert load_subscriptions(Engine) == []
