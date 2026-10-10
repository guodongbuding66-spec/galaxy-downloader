from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlparse, urlunparse

# Home Depot product galleries commonly expose small derivatives on
# images.thdstatic.com (100/145/300/400/600). The same asset family may expose
# larger public variants. Keep this list deliberately bounded and validate every
# candidate through the existing downloader before accepting it.
HOME_DEPOT_HOSTS = ("images.thdstatic.com",)
HOME_DEPOT_WIDTHS = (4000, 3000, 2500, 2000, 1500, 1200, 1000, 800, 600, 400, 300, 145, 100)
_HOME_DEPOT_SIZE_RE = re.compile(
    r"^(?P<stem>.+?)_(?P<size>\d{2,5})(?P<ext>\.(?:avif|gif|jpe?g|png|webp))$",
    re.I,
)


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith(f".{suffix}")


def is_home_depot_image(value: str) -> bool:
    try:
        host = (urlparse(value).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(_host_matches(host, suffix) for suffix in HOME_DEPOT_HOSTS)


def home_depot_asset_key(value: str) -> str | None:
    if not is_home_depot_image(value):
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    match = _HOME_DEPOT_SIZE_RE.match(parsed.path)
    if not match:
        return urlunparse(parsed._replace(query="", fragment=""))
    path = f"{match.group('stem')}{match.group('ext')}"
    return urlunparse(parsed._replace(path=path, query="", fragment=""))


def home_depot_size_hint(value: str) -> int:
    try:
        match = _HOME_DEPOT_SIZE_RE.match(urlparse(value).path)
    except ValueError:
        return 0
    if not match:
        return 0
    try:
        return int(match.group("size"))
    except (TypeError, ValueError):
        return 0


def home_depot_candidates(value: str) -> list[str]:
    """Return Home Depot candidates in a high-resolution-first download order.

    A previous implementation tried the unsuffixed URL before sized candidates.
    If that object existed but happened to be a small derivative, the downloader
    stopped immediately and never reached _1000/_2000/etc. V1.7 tries all known
    >=1000px variants first, then the unsuffixed source object, then smaller
    fallbacks. The first successful request therefore cannot be a 100px thumbnail
    while a larger known public variant is available.
    """
    if not is_home_depot_image(value):
        return [value]
    try:
        parsed = urlparse(value)
    except ValueError:
        return [value]
    match = _HOME_DEPOT_SIZE_RE.match(parsed.path)
    if not match:
        return [value]

    stem = match.group("stem")
    ext = match.group("ext")
    candidates: list[str] = []

    for width in HOME_DEPOT_WIDTHS:
        if width < 1000:
            continue
        candidate = urlunparse(parsed._replace(path=f"{stem}_{width}{ext}"))
        if candidate not in candidates:
            candidates.append(candidate)

    unsized = urlunparse(parsed._replace(path=f"{stem}{ext}"))
    if unsized not in candidates:
        candidates.append(unsized)

    for width in HOME_DEPOT_WIDTHS:
        if width >= 1000:
            continue
        candidate = urlunparse(parsed._replace(path=f"{stem}_{width}{ext}"))
        if candidate not in candidates:
            candidates.append(candidate)

    if value not in candidates:
        candidates.append(value)
    return candidates


def build_download_candidates(value: str, base_candidates: Iterable[str] = ()) -> list[str]:
    """Return bounded, high-to-low candidates without changing unrelated CDNs."""
    result: list[str] = []
    seeds = [value, *[str(item) for item in base_candidates if str(item).strip()]]
    for seed in seeds:
        expanded = home_depot_candidates(seed) if is_home_depot_image(seed) else [seed]
        for candidate in expanded:
            if candidate and candidate not in result:
                result.append(candidate)
    return result


def dedupe_resolution_variants(values: Iterable[object]) -> list[str]:
    """Collapse multiple thumbnails of the same Home Depot asset to the best input URL."""
    order: list[str] = []
    selected: dict[str, str] = {}
    ranks: dict[str, int] = {}
    seen_other: set[str] = set()

    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        key = home_depot_asset_key(value)
        if key is None:
            if value not in seen_other:
                seen_other.add(value)
                order.append(value)
            continue
        rank = home_depot_size_hint(value)
        if key not in selected:
            order.append(key)
            selected[key] = value
            ranks[key] = rank
        elif rank > ranks[key]:
            selected[key] = value
            ranks[key] = rank

    return [selected.get(item, item) for item in order]


def parse_srcset(value: str) -> list[str]:
    """Return srcset URLs from highest descriptor to lowest."""
    ranked: list[tuple[float, int, str]] = []
    for index, part in enumerate(str(value or "").split(",")):
        item = part.strip()
        if not item:
            continue
        bits = item.split()
        url = bits[0].strip()
        if not url or url.lower().startswith("data:"):
            continue
        rank = 0.0
        if len(bits) > 1:
            descriptor = bits[-1].lower()
            try:
                if descriptor.endswith("w"):
                    rank = float(descriptor[:-1])
                elif descriptor.endswith("x"):
                    rank = float(descriptor[:-1]) * 10_000.0
            except ValueError:
                rank = 0.0
        ranked.append((rank, -index, url))
    ranked.sort(reverse=True)
    result: list[str] = []
    for _rank, _index, url in ranked:
        if url not in result:
            result.append(url)
    return result


def run_self_test() -> None:
    sample = "https://images.thdstatic.com/productImages/demo/svn/item-64_100.jpg"
    candidates = home_depot_candidates(sample)
    assert candidates[0].endswith("item-64_4000.jpg")
    assert candidates.index(next(item for item in candidates if item.endswith("_1000.jpg"))) < candidates.index(next(item for item in candidates if item.endswith("item-64.jpg")))
    assert candidates.index(next(item for item in candidates if item.endswith("item-64.jpg"))) < candidates.index(next(item for item in candidates if item.endswith("_600.jpg")))
    deduped = dedupe_resolution_variants([sample, sample.replace("_100.jpg", "_600.jpg")])
    assert len(deduped) == 1 and deduped[0].endswith("_600.jpg")
    assert parse_srcset("a.jpg 100w, b.jpg 1600w, c.jpg 800w") == ["b.jpg", "c.jpg", "a.jpg"]


if __name__ == "__main__":
    run_self_test()
    print("Image resolution self-test passed")
