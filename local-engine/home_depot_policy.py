from __future__ import annotations

"""Home Depot product-page image recovery policy.

The public product page often renders a small images.thdstatic.com derivative
(e.g. `_100.jpg` / `_600.jpg`) while higher public CDN variants are available.
This policy keeps the generic document parser but teaches it to classify Home
Depot product pages, read high-density srcset/data attributes, collapse multiple
size variants to one asset identity, and reject Akamai/challenge-page chrome.
Actual HTTP validation and high-resolution fallback remain in
image_download/image_resolution.
"""

import re
from typing import Any
from urllib.parse import urlparse

import web_document as base
from image_resolution import dedupe_resolution_variants, parse_srcset

_HOME_DEPOT_HOSTS = ("homedepot.com", "thdstatic.com")
_HOME_DEPOT_IMAGE_HOST = "images.thdstatic.com"
_CHALLENGE_RE = re.compile(
    r"(?:akamai(?:hd)?|akamai-logo|reference\s*#\s*\d+|access\s+denied|"
    r"request\s+rejected|bot\s+(?:manager|detection)|automated\s+access|"
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
            "Home Depot 阻止了匿名页面解析。请在“登录环境”选择 Microsoft Edge 或 Google Chrome 后重试；"
            "Galaxy 只在本机读取所选浏览器 Cookie，不会上传 Cookie。"
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

        # Never turn CDN/challenge page decoration into a successful product
        # gallery. This was the concrete failure observed in Windows CI where an
        # Akamai logo was incorrectly returned as the Home Depot product image.
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
            # A Home Depot page without a genuine thdstatic product asset is not
            # a successful product-gallery parse. Returning None lets the normal
            # dynamic renderer get a chance to load the real gallery.
            return None

        data["platform"] = "homedepot"
        data["documentType"] = "product"
        data["images"] = [
            {"index": index + 1, "url": url, "downloadUrl": url}
            for index, url in enumerate(deduped[: base.MAX_IMAGES])
        ]
        data["cover"] = deduped[0]
        return result

    base._classify = classify
    base._DocumentParser.handle_starttag = handle_starttag
    base._document_payload = document_payload
    _INSTALLED = True


def run_self_test() -> None:
    assert _is_home_depot_url("https://www.homedepot.com/p/700380885")
    assert _is_home_depot_url("https://images.thdstatic.com/productImages/a.jpg")
    assert not _is_home_depot_url("https://example.com/a.jpg")
    assert _is_home_depot_product_image("https://images.thdstatic.com/productImages/a/item_600.jpg")
    assert not _is_home_depot_product_image("https://www.akamai.com/site/images/logo.svg")
    assert _looks_like_home_depot_challenge(
        "<html><img src='https://www.akamai.com/site/images/logo.svg'>Access Denied</html>",
        "https://www.homedepot.com/p/700380885",
    )
    assert parse_srcset("small.jpg 100w, large.jpg 1600w")[0] == "large.jpg"


if __name__ == "__main__":
    run_self_test()
    print("Home Depot policy self-test passed")
