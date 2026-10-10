from __future__ import annotations

"""Home Depot product-page image recovery policy.

The public product page often renders a small images.thdstatic.com derivative
(e.g. `_100.jpg` / `_600.jpg`) while higher public CDN variants are available.
This policy keeps the generic document parser but teaches it to classify Home
Depot product pages, read high-density srcset/data attributes, and collapse
multiple size variants to one asset identity. Actual HTTP validation and
high-resolution fallback remain in image_download/image_resolution.
"""

from typing import Any
from urllib.parse import urlparse

import web_document as base
from image_resolution import dedupe_resolution_variants, parse_srcset

_HOME_DEPOT_HOSTS = ("homedepot.com", "thdstatic.com")
_INSTALLED = False


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith(f".{suffix}")


def _is_home_depot_url(value: object) -> bool:
    try:
        host = (urlparse(str(value or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(_host_matches(host, suffix) for suffix in _HOME_DEPOT_HOSTS)


def install_home_depot_document_policy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    original_classify = base._classify
    original_starttag = base._DocumentParser.handle_starttag
    original_payload = base._document_payload

    def classify(source_url: str, raw_html: str) -> tuple[str, str]:
        try:
            host = (urlparse(source_url).hostname or "").lower().rstrip(".")
        except ValueError:
            host = ""
        if _host_matches(host, "homedepot.com"):
            return "homedepot", "product"
        return original_classify(source_url, raw_html)

    def handle_starttag(parser, tag: str, attrs):  # noqa: ANN001
        original_starttag(parser, tag, attrs)
        if tag not in {"img", "source", "picture", "a", "div"}:
            return
        values = parser._attrs(attrs)
        # Home Depot and other commerce galleries frequently store the useful
        # source outside `src`; read only image-like attributes and keep the
        # shared URL/image safety checks in parser._add_image.
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
        if not result or not result.get("success") or not _is_home_depot_url(final_url):
            return result
        data = result.get("data")
        if not isinstance(data, dict):
            return result
        data["platform"] = "homedepot"
        data["documentType"] = "product"
        raw_images = data.get("images") if isinstance(data.get("images"), list) else []
        urls: list[str] = []
        for item in raw_images:
            if isinstance(item, dict):
                value = str(item.get("downloadUrl") or item.get("url") or "").strip()
            else:
                value = str(item or "").strip()
            if value:
                urls.append(value)
        deduped = dedupe_resolution_variants(urls)
        data["images"] = [
            {"index": index + 1, "url": url, "downloadUrl": url}
            for index, url in enumerate(deduped[: base.MAX_IMAGES])
        ]
        if deduped:
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
    assert parse_srcset("small.jpg 100w, large.jpg 1600w")[0] == "large.jpg"


if __name__ == "__main__":
    run_self_test()
    print("Home Depot policy self-test passed")
