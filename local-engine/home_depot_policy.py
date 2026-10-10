from __future__ import annotations

"""Home Depot product-page image recovery policy.

Resolution order is deliberately local/free:
1. Home Depot's public storefront GraphQL operation (no browser, no credentials).
2. Observe the same GraphQL response from a local Edge/Chrome page load.
3. Generic HTML/dynamic-document fallback.

No paid scraper, proxy service, captcha bypass, or remote browser is required.
"""

import re
from typing import Any
from urllib.parse import urlparse

import web_document as base
from home_depot_direct import parse_home_depot_direct
from home_depot_graphql import is_home_depot_product_url, parse_home_depot_graphql
from image_resolution import dedupe_resolution_variants, parse_srcset

_HOME_DEPOT_HOSTS = ("homedepot.com", "thdstatic.com")
_HOME_DEPOT_IMAGE_HOST = "images.thdstatic.com"
_CHALLENGE_RE = re.compile(
    r"(?:akamai(?:hd)?-logo|www\.akamai\.com/site/[^\s\"']*logo|"
    r"reference\s*#\s*[0-9a-f.:-]+|access\s+denied|request\s+rejected|"
    r"bot\s+(?:manager|detection)|automated\s+access|"
    r"verify\s+(?:you\s+are|your)\s+(?:a\s+)?human|captcha|security\s+check)",
    re.I,
)
_INSTALLED = False


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith(f".{suffix}")


def _hostname(value: object) -> str:
    try:
        return (urlparse(str(value or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _is_home_depot_url(value: object) -> bool:
    host = _hostname(value)
    return any(_host_matches(host, suffix) for suffix in _HOME_DEPOT_HOSTS)


def _is_home_depot_product_image(value: object) -> bool:
    host = _hostname(value)
    return host == _HOME_DEPOT_IMAGE_HOST or host.endswith(f".{_HOME_DEPOT_IMAGE_HOST}")


def _looks_like_home_depot_challenge(raw_html: str, final_url: str) -> bool:
    final_host = _hostname(final_url)
    if final_host and not _host_matches(final_host, "homedepot.com"):
        return True
    sample = f"{final_url}\n{raw_html[:2_000_000]}"
    return bool(_CHALLENGE_RE.search(sample))


def _challenge_result(browser: str) -> dict[str, Any]:
    requested = (browser or "none").strip().lower()
    if requested == "none":
        error = (
            "Home Depot 阻止了匿名 HTML 页面解析。Galaxy 已先尝试公开商品数据接口和本机 Edge/Chrome 商品数据流；"
            "如仍失败，请在“登录环境”选择 Microsoft Edge 或 Google Chrome 后重试。Cookie 只在本机读取，不会上传。"
        )
    else:
        error = (
            f"Home Depot 仍然返回了验证页，未发现真实商品图片。请先在 {requested.title()} 中正常打开该商品页，"
            "通过站点验证后再重试。Galaxy 不会绕过验证码或反机器人验证。"
        )
    return {
        "success": False,
        "code": "AUTH_REQUIRED",
        "status": 401,
        "error": error,
        "details": {"platform": "homedepot", "challenge": True},
    }


def install_home_depot_document_policy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    original_classify = base._classify
    original_starttag = base._DocumentParser.handle_starttag
    original_payload = base._document_payload
    original_parse_web_document = base.parse_web_document

    def classify(source_url: str, raw_html: str) -> tuple[str, str]:
        host = _hostname(source_url)
        if _host_matches(host, "homedepot.com"):
            return "homedepot", "product"
        return original_classify(source_url, raw_html)

    def handle_starttag(parser, tag: str, attrs):  # noqa: ANN001
        original_starttag(parser, tag, attrs)
        if tag not in {"img", "source", "picture", "a", "div"}:
            return
        values = parser._attrs(attrs)
        for key in (
            "data-srcset",
            "data-src-set",
            "data-lazy-srcset",
            "data-zoom-image",
            "data-zoom-src",
            "data-hires",
            "data-hi-res",
            "data-high-res",
            "data-large-image",
            "data-image",
            "data-src",
            "srcset",
        ):
            raw = values.get(key)
            if not raw:
                continue
            if "srcset" in key or "src-set" in key:
                for candidate in parse_srcset(raw):
                    parser._add_image(candidate, key)
            else:
                parser._add_image(raw, key)

    def document_payload(source_url: str, raw_html: str, final_url: str, browser: str) -> dict[str, Any] | None:
        result = original_payload(source_url, raw_html, final_url, browser)
        if not _is_home_depot_url(source_url) and not _is_home_depot_url(final_url):
            return result

        if _looks_like_home_depot_challenge(raw_html, final_url):
            return _challenge_result(browser)

        if not result or not result.get("success"):
            return result
        data = result.get("data")
        if not isinstance(data, dict):
            return result

        raw_images = data.get("images") if isinstance(data.get("images"), list) else []
        urls: list[str] = []
        for item in raw_images:
            if isinstance(item, dict):
                value = str(item.get("downloadUrl") or item.get("url") or "").strip()
            else:
                value = str(item or "").strip()
            if value and _is_home_depot_product_image(value):
                urls.append(value)

        cover = str(data.get("cover") or "").strip()
        if cover and _is_home_depot_product_image(cover):
            urls.insert(0, cover)

        deduped = dedupe_resolution_variants(urls)
        if not deduped:
            return None

        data["platform"] = "homedepot"
        data["documentType"] = "product"
        data["images"] = [
            {"index": index + 1, "url": url, "downloadUrl": url}
            for index, url in enumerate(deduped[: base.MAX_IMAGES])
        ]
        data["cover"] = deduped[0]
        return result

    def parse_web_document(source_url: str, browser: str = "none") -> dict[str, Any]:
        if is_home_depot_product_url(source_url):
            direct = parse_home_depot_direct(source_url, browser)
            if direct.get("success"):
                return direct

            product = parse_home_depot_graphql(source_url, browser)
            if product.get("success"):
                return product
            if product.get("code") == "BROWSER_COOKIE_UNAVAILABLE":
                return product

        return original_parse_web_document(source_url, browser)

    base._classify = classify
    base._DocumentParser.handle_starttag = handle_starttag
    base._document_payload = document_payload
    base.parse_web_document = parse_web_document
    _INSTALLED = True


def run_self_test() -> None:
    assert _is_home_depot_url("https://www.homedepot.com/p/700380885")
    assert _is_home_depot_url("https://images.thdstatic.com/productImages/a.jpg")
    assert not _is_home_depot_url("https://example.com/a.jpg")
    assert is_home_depot_product_url("https://www.homedepot.com/p/Example-hh-816/700380885#overlay")
    assert _is_home_depot_product_image("https://images.thdstatic.com/productImages/a/item_600.jpg")
    assert not _is_home_depot_product_image("https://www.akamai.com/site/images/logo.svg")
    assert _looks_like_home_depot_challenge(
        "<html><img src='https://www.akamai.com/site/images/akamai-logo1.svg'>Access Denied</html>",
        "https://www.homedepot.com/p/700380885",
    )
    assert not _looks_like_home_depot_challenge(
        "<html><script src='https://example.akamaihd.net/app.js'></script><img src='https://images.thdstatic.com/productImages/a/item_600.jpg'></html>",
        "https://www.homedepot.com/p/700380885",
    )
    assert parse_srcset("small.jpg 100w, large.jpg 1600w")[0] == "large.jpg"


if __name__ == "__main__":
    run_self_test()
    print("Home Depot policy self-test passed")
