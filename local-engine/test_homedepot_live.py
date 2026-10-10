from __future__ import annotations

import io
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from image_resolution import home_depot_candidates, is_home_depot_image

PRODUCT_URL = (
    "https://www.homedepot.com/p/Unbranded-Gray-9-ft-x-6-ft-Weatherproof-Metal-Garden-Storage-Shed-with-Windows-Flower-Rack-Lockable-Double-Doors-for-Backyard-hh-816/700380885"
)
KNOWN_MAIN = (
    "https://images.thdstatic.com/productImages/3c58f1501a4d4ec0801de07367105b70/svn/"
    "gray-unbranded-metal-sheds-hh-816-64_600.jpg"
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
)
PARTIAL_BYTES = 2 * 1024 * 1024
FULL_LIMIT = 32 * 1024 * 1024
IMAGE_RE = re.compile(
    r"https?://images\.thdstatic\.com/productImages/[^\"'<>\\\s]+?\.(?:jpe?g|png|webp|avif)(?:\?[^\"'<>\\\s]*)?",
    re.I,
)


def _request(url: str, *, range_probe: bool = False):
    headers = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": PRODUCT_URL,
        "Accept-Encoding": "identity",
    }
    if range_probe:
        headers["Range"] = f"bytes=0-{PARTIAL_BYTES - 1}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=25)


def _dimensions(payload: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(payload)) as image:
        width, height = image.size
    return int(width), int(height)


def _image_size(url: str) -> tuple[int, int, int]:
    status = 200
    content_type = ""
    with _request(url, range_probe=True) as response:
        status = int(getattr(response, "status", 200) or 200)
        content_type = str(response.headers.get("Content-Type") or "")
        if "image/" not in content_type.lower():
            raise ValueError(f"not an image response: {content_type}")
        payload = response.read(PARTIAL_BYTES)
    try:
        width, height = _dimensions(payload)
        return width, height, status
    except (UnidentifiedImageError, OSError):
        # A few image formats keep essential metadata beyond the first range.
        # Retry once without Range, with a strict byte cap.
        with _request(url, range_probe=False) as response:
            status = int(getattr(response, "status", 200) or 200)
            content_type = str(response.headers.get("Content-Type") or "")
            if "image/" not in content_type.lower():
                raise ValueError(f"not an image response: {content_type}")
            payload = response.read(FULL_LIMIT + 1)
        if len(payload) > FULL_LIMIT:
            raise ValueError("image exceeds live-test byte cap")
        width, height = _dimensions(payload)
        return width, height, status


def _page_images() -> list[str]:
    request = urllib.request.Request(
        PRODUCT_URL,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read(12 * 1024 * 1024).decode("utf-8", errors="replace")
    except Exception:
        return []
    html = html.replace("\\/", "/").replace("\\u002F", "/").replace("\\u0026", "&")
    result: list[str] = []
    for match in IMAGE_RE.findall(html):
        value = match.replace("&amp;", "&")
        if value not in result:
            result.append(value)
    return result


def _best_variant(seed: str) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    attempts: list[dict[str, object]] = []
    best: dict[str, object] | None = None
    for candidate in home_depot_candidates(seed):
        try:
            width, height, status = _image_size(candidate)
        except urllib.error.HTTPError as exc:
            attempts.append({"url": candidate, "status": exc.code, "ok": False})
            continue
        except Exception as exc:
            attempts.append({"url": candidate, "ok": False, "error": str(exc)[:180]})
            continue
        item: dict[str, object] = {
            "url": candidate,
            "status": status,
            "ok": True,
            "width": width,
            "height": height,
            "pixels": width * height,
        }
        attempts.append(item)
        if best is None or int(item["pixels"]) > int(best["pixels"]):
            best = item
    return best, attempts


def main() -> int:
    page_images = [url for url in _page_images() if is_home_depot_image(url)]
    seeds = [KNOWN_MAIN]
    for item in page_images:
        if item not in seeds:
            seeds.append(item)

    results = []
    for seed in seeds[:12]:
        best, attempts = _best_variant(seed)
        results.append({"seed": seed, "best": best, "attempts": attempts})

    first = results[0]["best"] if results else None
    summary = {
        "productUrl": PRODUCT_URL,
        "pageImageCount": len(page_images),
        "seedCount": len(seeds),
        "mainSeed": KNOWN_MAIN,
        "mainBest": first,
        "results": results,
    }
    Path("homedepot-live-result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))

    if not isinstance(first, dict):
        print("FAIL: no downloadable Home Depot image candidate", file=sys.stderr)
        return 2
    width = int(first.get("width") or 0)
    height = int(first.get("height") or 0)
    if min(width, height) <= 100:
        print(f"FAIL: resolver is still returning thumbnail dimensions {width}x{height}", file=sys.stderr)
        return 3
    if max(width, height) <= 600:
        print(f"FAIL: live resolver did not improve beyond the public 600px derivative ({width}x{height})", file=sys.stderr)
        return 4

    print(f"PASS: Home Depot main asset resolves beyond thumbnail/600px: {width}x{height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
