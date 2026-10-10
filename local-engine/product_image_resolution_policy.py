from __future__ import annotations

"""Product-image parsing policy for high-resolution gallery assets.

This module deliberately does not hard-code a single Home Depot SKU. It fixes
three generic parser problems that made product pages collapse to thumbnails:

* ``srcset`` was treated like one URL, so the first/smallest entry won.
* multiple CDN derivatives of the same asset were returned as separate images.
* Home Depot product images were not classified/prioritized as a product gallery.

The downloader still validates every final URL over HTTP before saving it. This
policy only improves discovery and ordering; it never invents image bytes.
"""

from typing import Any
from urllib.parse import urlparse

import web_document as base
from image_resolution import dedupe_resolution_variants, is_home_depot_image, parse_srcset

_INSTALLED = False


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith(f".{suffix}")


def _is_home_depot_page(value: str) -> bool:
    try:
        host = (urlparse(value).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return _host_matches(host, "homedepot.com")


def _product_image_url(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("downloadUrl") or item.get("url") or "").strip()
    return str(item or "").strip()


def _normalize_images(images: list[object], *, home_depot: bool) -> list[dict[str, Any]]:
    urls = [_product_image_url(item) for item in images]
    urls = [value for value in urls if value]

    # If Home Depot product images were discovered, discard page chrome/assets
    # from unrelated hosts before de-duplicating resolution derivatives.
    if home_depot:
        product_urls = [
            value
            for value in urls
            if is_home_depot_image(value) and "/productImages/" in urlparse(value).path
        ]
        if product_urls:
            urls = product_urls

    urls = dedupe_resolution_variants(urls)
    return [
        {"index": index + 1, "url": value, "downloadUrl": value}
        for index, value in enumerate(urls[: int(getattr(base, "MAX_IMAGES", 120))])
    ]


def install_product_image_resolution_policy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    parser_cls = base._DocumentParser
    original_starttag = parser_cls.handle_starttag
    original_payload = base._document_payload
    original_classify = base._classify

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in {"img", "source"}:
            values = self._attrs(attrs)
            for key in ("srcset", "data-srcset", "data-lazy-srcset"):
                raw = values.get(key)
                if not raw:
                    continue
                # Highest descriptor first. ``_add_image`` still owns absolute
                # URL resolution, tracking-asset filtering and global limits.
                for candidate in parse_srcset(raw):
                    self._add_image(candidate, key)
        return original_starttag(self, tag, attrs)

    def classify(source_url: str, raw_html: str):
        if _is_home_depot_page(source_url):
            return "homedepot", "product"
        return original_classify(source_url, raw_html)

    def document_payload(source_url: str, raw_html: str, final_url: str, browser: str):
        result = original_payload(source_url, raw_html, final_url, browser)
        if not isinstance(result, dict) or not result.get("success"):
            return result
        data = result.get("data")
        if not isinstance(data, dict):
            return result

        home_depot = _is_home_depot_page(final_url) or str(data.get("platform") or "").lower() == "homedepot"
        images = data.get("images") if isinstance(data.get("images"), list) else []
        normalized = _normalize_images(images, home_depot=home_depot)
        if normalized:
            data["images"] = normalized
            data["cover"] = normalized[0]["url"]
        if home_depot:
            data["platform"] = "homedepot"
            data["documentType"] = "product"
            data["kind"] = "image"
            data["noteType"] = "image"
            details = result.setdefault("details", {})
            if isinstance(details, dict):
                details["resolutionPolicy"] = "home-depot-highest-public-variant"
        return result

    parser_cls.handle_starttag = handle_starttag
    base._classify = classify
    base._document_payload = document_payload
    _INSTALLED = True


def run_self_test() -> None:
    sample = (
        "https://images.thdstatic.com/productImages/demo/svn/item-64_100.jpg 100w, "
        "https://images.thdstatic.com/productImages/demo/svn/item-64_600.jpg 600w, "
        "https://images.thdstatic.com/productImages/demo/svn/item-64_1000.jpg 1000w"
    )
    assert parse_srcset(sample)[0].endswith("_1000.jpg")
    normalized = _normalize_images(
        [
            {"url": "https://images.thdstatic.com/productImages/demo/svn/item-64_100.jpg"},
            {"url": "https://images.thdstatic.com/productImages/demo/svn/item-64_600.jpg"},
        ],
        home_depot=True,
    )
    assert len(normalized) == 1
    assert normalized[0]["url"].endswith("_600.jpg")
    assert _is_home_depot_page("https://www.homedepot.com/p/example/123")


if __name__ == "__main__":
    run_self_test()
    print("Product image resolution policy self-test passed")
