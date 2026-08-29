import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_wrangler_config() -> dict:
    return json.loads((ROOT / "wrangler.jsonc").read_text(encoding="utf-8"))


def test_api_rate_limit_bindings_are_distinct_and_bounded() -> None:
    config = load_wrangler_config()
    bindings = {item["name"]: item for item in config["ratelimits"]}

    parse = bindings["PARSE_RATE_LIMITER"]
    download = bindings["DOWNLOAD_RATE_LIMITER"]

    assert parse["simple"] == {"limit": 30, "period": 60}
    assert download["simple"] == {"limit": 10, "period": 60}
    assert parse["namespace_id"] != download["namespace_id"]
    assert int(parse["namespace_id"]) > 0
    assert int(download["namespace_id"]) > 0


def test_worker_router_uses_both_rate_limit_bindings() -> None:
    source = (ROOT / "src" / "index.ts").read_text(encoding="utf-8")

    assert "env.PARSE_RATE_LIMITER" in source
    assert "env.DOWNLOAD_RATE_LIMITER" in source
    assert "code: 'RATE_LIMITED'" in source
    assert "'Retry-After': '60'" in source
