from __future__ import annotations

"""Anonymous Home Depot product-media resolver using the storefront GraphQL API.

This calls the same public product operation used by homedepot.com. It needs no
paid proxy, no third-party browser service and no user credentials. The browser
interceptor remains the fallback because this internal storefront API can drift.
"""

import json
import urllib.error
import urllib.request
from typing import Any

import dynamic_document as dynamic
from home_depot_graphql import _product_payload, is_home_depot_product_url, item_id_from_url

_ENDPOINTS = (
    "https://www.homedepot.com/federation-gateway/graphql?opname=productClientOnlyProduct",
    "https://apionline.homedepot.com/federation-gateway/graphql?opname=productClientOnlyProduct",
)
_MAX_RESPONSE_BYTES = 12 * 1024 * 1024
_QUERY = """
query productClientOnlyProduct($itemId: String!) {
  product(itemId: $itemId) {
    itemId
    identifiers { itemId productLabel modelNumber }
    media {
      images { url sizes type subType }
      video { shortDescription thumbnail url title type videoId }
    }
  }
}
""".strip()


def _request_payload(source_url: str, item_id: str) -> bytes:
    return json.dumps(
        {
            "operationName": "productClientOnlyProduct",
            "variables": {"itemId": item_id},
            "query": _QUERY,
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _headers(source_url: str) -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://www.homedepot.com",
        "Referer": source_url,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
        ),
        "X-Experience-Name": "general-merchandise",
        "X-Hd-Dc": "origin",
        "X-Current-Url": source_url,
    }


def parse_home_depot_direct(source_url: str, browser: str = "none") -> dict[str, Any]:
    item_id = item_id_from_url(source_url)
    if not item_id or not is_home_depot_product_url(source_url):
        return {"success": False, "code": "UNSUPPORTED_PLATFORM", "status": 422, "error": "Not a Home Depot product URL"}
    if not dynamic.base._safe_http_url(source_url):
        return {"success": False, "code": "BAD_REQUEST", "status": 400, "error": "URL is not allowed"}

    request_body = _request_payload(source_url, item_id)
    failures: list[str] = []
    for endpoint in _ENDPOINTS:
        try:
            request = urllib.request.Request(
                endpoint,
                data=request_body,
                headers=_headers(source_url),
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=18) as response:
                content_type = str(response.headers.get("Content-Type") or "")
                if "json" not in content_type.lower():
                    failures.append(f"{endpoint}: unexpected content type {content_type}")
                    continue
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(raw) > _MAX_RESPONSE_BYTES:
                    failures.append(f"{endpoint}: response too large")
                    continue
            payload = json.loads(raw.decode("utf-8", errors="replace"))
            result = _product_payload(source_url, item_id, payload, browser)
            if result is not None:
                details = result.setdefault("details", {})
                if isinstance(details, dict):
                    details["resolver"] = "homedepot-direct-graphql"
                    details["endpoint"] = endpoint.split("/federation-gateway", 1)[0]
                return result
            failures.append(f"{endpoint}: product response contained no THD product images")
        except urllib.error.HTTPError as exc:
            failures.append(f"{endpoint}: HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"{endpoint}: {exc}")

    return {
        "success": False,
        "code": "DIRECT_GRAPHQL_FAILED",
        "status": 502,
        "error": "; ".join(failures)[-1000:] or "Home Depot direct GraphQL request failed",
        "details": {"resolver": "homedepot-direct-graphql", "itemId": item_id},
    }


def run_self_test() -> None:
    source = "https://www.homedepot.com/p/Example-hh-816/700380885#overlay"
    assert is_home_depot_product_url(source)
    assert item_id_from_url(source) == "700380885"
    payload = json.loads(_request_payload(source, "700380885"))
    assert payload["operationName"] == "productClientOnlyProduct"
    assert payload["variables"]["itemId"] == "700380885"
    assert "media" in payload["query"] and "images" in payload["query"]
    headers = _headers(source)
    assert headers["Origin"] == "https://www.homedepot.com"
    assert headers["X-Hd-Dc"] == "origin"


if __name__ == "__main__":
    run_self_test()
    print("Home Depot direct GraphQL self-test passed")
