from __future__ import annotations

"""Resolve Home Depot product media from the storefront's own browser traffic.

This is deliberately local and free: Edge/Chrome loads the public product page,
and Galaxy observes the product GraphQL response that the page itself requests.
No proxy, paid scraper, captcha bypass, or private Home Depot credential is used.
"""

import base64
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import dynamic_document as dynamic
from image_resolution import dedupe_resolution_variants

_GRAPHQL_MARKERS = ("opname=productClientOnlyProduct", "opname=mediaPriceInventory")
_ITEM_ID_RE = re.compile(r"(?:^|/)(\d{8,12})(?:/|$)")
_PRODUCT_IMAGE_HOST = "images.thdstatic.com"


def is_home_depot_product_url(value: object) -> bool:
    try:
        parsed = urlparse(str(value or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not (host == "homedepot.com" or host.endswith(".homedepot.com")):
        return False
    return bool(_ITEM_ID_RE.search(parsed.path.rstrip("/") + "/"))


def item_id_from_url(value: object) -> str | None:
    try:
        parsed = urlparse(str(value or ""))
    except ValueError:
        return None
    matches = _ITEM_ID_RE.findall(parsed.path.rstrip("/") + "/")
    return matches[-1] if matches else None


def _is_product_image(value: object) -> bool:
    try:
        host = (urlparse(str(value or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return host == _PRODUCT_IMAGE_HOST or host.endswith(f".{_PRODUCT_IMAGE_HOST}")


class _HomeDepotClient(dynamic._CdpClient):
    def __init__(self, ws_url: str):
        super().__init__(ws_url)
        self.product_responses: list[str] = []

    def _handle_event(self, payload: dict[str, Any]) -> None:
        super()._handle_event(payload)
        if payload.get("method") != "Network.responseReceived":
            return
        params = payload.get("params")
        if not isinstance(params, dict):
            return
        response = params.get("response")
        if not isinstance(response, dict):
            return
        url = str(response.get("url") or "")
        request_id = str(params.get("requestId") or "")
        if request_id and "federation-gateway/graphql" in url and any(marker in url for marker in _GRAPHQL_MARKERS):
            if request_id not in self.product_responses:
                self.product_responses.append(request_id)


def _iter_dicts(value: Any):
    stack = [value]
    visited = 0
    while stack and visited < 40_000:
        current = stack.pop()
        visited += 1
        if isinstance(current, dict):
            yield current
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))


def _product_payload(source_url: str, item_id: str, payload: Any, browser: str) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for node in _iter_dicts(payload):
        media = node.get("media")
        if not isinstance(media, dict) or not isinstance(media.get("images"), list):
            continue
        node_item = str(node.get("itemId") or "")
        identifiers = node.get("identifiers") if isinstance(node.get("identifiers"), dict) else {}
        identifier_item = str(identifiers.get("itemId") or "") if isinstance(identifiers, dict) else ""
        if node_item and node_item != item_id and identifier_item and identifier_item != item_id:
            continue
        best = node
        if node_item == item_id or identifier_item == item_id:
            break
    if best is None:
        return None

    media = best.get("media") if isinstance(best.get("media"), dict) else {}
    raw_images = media.get("images") if isinstance(media, dict) and isinstance(media.get("images"), list) else []
    urls: list[str] = []
    for image in raw_images:
        if not isinstance(image, dict):
            continue
        value = str(image.get("url") or "").strip()
        if value and _is_product_image(value):
            urls.append(value)
    urls = dedupe_resolution_variants(urls)
    if not urls:
        return None

    identifiers = best.get("identifiers") if isinstance(best.get("identifiers"), dict) else {}
    title = str(identifiers.get("productLabel") or best.get("title") or f"Home Depot {item_id}").strip()
    videos: list[dict[str, Any]] = []
    raw_video = media.get("video") if isinstance(media, dict) else None
    if isinstance(raw_video, list):
        for index, video in enumerate(raw_video[:30]):
            if not isinstance(video, dict):
                continue
            url = str(video.get("url") or "").strip()
            if url.startswith(("http://", "https://")):
                videos.append({
                    "id": f"homedepot-video-{index + 1}",
                    "title": str(video.get("title") or f"{title} · video {index + 1}"),
                    "downloadVideoUrl": url,
                    "originDownloadVideoUrl": url,
                    "downloadAudioUrl": None,
                    "originDownloadAudioUrl": None,
                    "videoAudioMode": "muxed",
                    "mediaActions": {"video": "direct-download", "audio": "extract-audio"},
                })

    return {
        "success": True,
        "data": {
            "title": title,
            "desc": "",
            "textContent": "",
            "author": None,
            "publishedAt": None,
            "siteName": "The Home Depot",
            "documentType": "product",
            "cover": urls[0],
            "platform": "homedepot",
            "downloadAudioUrl": None,
            "downloadVideoUrl": None,
            "originDownloadAudioUrl": None,
            "originDownloadVideoUrl": None,
            "videoAudioMode": "not_applicable",
            "mediaActions": {"video": "hide", "audio": "hide"},
            "url": source_url,
            "kind": "image",
            "noteType": "image",
            "images": [
                {"index": index + 1, "url": url, "downloadUrl": url}
                for index, url in enumerate(urls)
            ],
            "videos": videos,
            "localAuthBrowser": None if browser == "none" else browser,
        },
        "details": {"resolver": "homedepot-browser-graphql", "itemId": item_id},
    }


def _response_json(client: _HomeDepotClient, request_id: str) -> Any | None:
    try:
        result = client.call("Network.getResponseBody", {"requestId": request_id}, timeout=2.0)
    except Exception:
        return None
    body = str(result.get("body") or "")
    if not body:
        return None
    if result.get("base64Encoded"):
        try:
            body = base64.b64decode(body).decode("utf-8", errors="replace")
        except Exception:
            return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def parse_home_depot_graphql(source_url: str, browser: str = "none") -> dict[str, Any]:
    item_id = item_id_from_url(source_url)
    if not item_id or not is_home_depot_product_url(source_url):
        return {"success": False, "code": "UNSUPPORTED_PLATFORM", "status": 422, "error": "Not a Home Depot product URL"}
    if not dynamic.base._safe_http_url(source_url):
        return {"success": False, "code": "BAD_REQUEST", "status": 400, "error": "URL is not allowed"}

    candidates = dynamic._browser_candidates(browser)
    if not candidates:
        return {
            "success": False,
            "code": "DYNAMIC_RENDER_FAILED",
            "status": 502,
            "error": "Home Depot 原图解析需要本机 Edge 或 Chrome。",
            "details": {"resolver": "homedepot-browser-graphql"},
        }

    last_error: Exception | None = None
    for browser_name, executable in candidates:
        profile_dir = tempfile.mkdtemp(prefix="galaxy-homedepot-")
        port = dynamic._free_port()
        args = [
            str(executable),
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile_dir}",
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-component-update",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-extensions",
            "--window-size=1365,900",
            "about:blank",
        ]
        process: subprocess.Popen[Any] | None = None
        client: _HomeDepotClient | None = None
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=dynamic._creation_flags(),
            )
            ws_url = dynamic._wait_page_ws(port, process)
            client = _HomeDepotClient(ws_url)
            client.call("Network.enable")
            client.call("Page.enable")
            client.call("Runtime.enable")
            client.call("Fetch.enable", {"patterns": [{"urlPattern": "http://*"}, {"urlPattern": "https://*"}]})
            client.call("Network.setExtraHTTPHeaders", {"headers": {"Accept-Language": "en-US,en;q=0.9"}})
            dynamic._install_browser_cookies(client, source_url, browser)
            client.call("Page.navigate", {"url": source_url}, timeout=5.0)

            deadline = time.monotonic() + dynamic.CDP_NAVIGATION_TIMEOUT_SECONDS
            tried: set[str] = set()
            while time.monotonic() < deadline:
                if client.blocked_document_url:
                    raise dynamic.DynamicDocumentError(
                        f"Home Depot attempted blocked navigation: {client.blocked_document_url}"
                    )
                try:
                    dynamic._evaluate_value(client, "document.readyState", timeout=1.5)
                except Exception:
                    pass
                for request_id in list(client.product_responses):
                    if request_id in tried:
                        continue
                    response_payload = _response_json(client, request_id)
                    if response_payload is None:
                        continue
                    tried.add(request_id)
                    result = _product_payload(source_url, item_id, response_payload, browser)
                    if result is not None:
                        details = result.setdefault("details", {})
                        if isinstance(details, dict):
                            details["browser"] = browser_name
                        return result
                time.sleep(0.2)
            last_error = dynamic.DynamicDocumentError("Home Depot product GraphQL response was not observed")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        finally:
            if client is not None:
                client.close()
            if process is not None:
                try:
                    process.terminate()
                    process.wait(timeout=3.0)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
            shutil.rmtree(profile_dir, ignore_errors=True)

    return {
        "success": False,
        "code": "DYNAMIC_RENDER_FAILED",
        "status": 502,
        "error": str(last_error or "Home Depot browser GraphQL resolver failed"),
        "details": {"resolver": "homedepot-browser-graphql"},
    }


def run_self_test() -> None:
    sample = "https://www.homedepot.com/p/Example-hh-816/700380885#overlay"
    assert is_home_depot_product_url(sample)
    assert item_id_from_url(sample) == "700380885"
    payload = {
        "data": {
            "product": {
                "itemId": "700380885",
                "identifiers": {"itemId": "700380885", "productLabel": "Example Shed"},
                "media": {
                    "images": [
                        {"url": "https://images.thdstatic.com/productImages/a/svn/example-64_100.jpg"},
                        {"url": "https://images.thdstatic.com/productImages/a/svn/example-64_600.jpg"},
                    ]
                },
            }
        }
    }
    result = _product_payload(sample, "700380885", payload, "none")
    assert result and result["success"]
    assert result["data"]["platform"] == "homedepot"
    assert len(result["data"]["images"]) == 1
    assert result["data"]["images"][0]["url"].endswith("_600.jpg")


if __name__ == "__main__":
    run_self_test()
    print("Home Depot browser GraphQL self-test passed")
