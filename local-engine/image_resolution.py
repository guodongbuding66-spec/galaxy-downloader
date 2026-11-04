from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlparse, urlunparse

# Home Depot product galleries commonly expose small derivatives on
# images.thdstatic.com (100/145/300/400/600). The same asset family may expose
# larger public variants. Keep this list deliberately bounded and validate every
# candidate through the existing downloader before accepting it.
HOME_DEPOT_HOSTS = ("images.thdstatic.com",)
# Probe only the public zoom convention. Larger values must be explicitly
# advertised by the page; a filename is never evidence of real pixel size.
HOME_DEPOT_WIDTHS = (1000,)
_HOME_DEPOT_SIZE_RE = re.compile(
    r"^(?P<stem>.+?)_(?P<size>\d{2,5})(?P<ext>\.(?:avif|gif|jpe?g|png|webp))$",
    re.I,
)
_SIZE_PLACEHOLDER_RE = re.compile(r"(?:<size>|\{size\}|%3csize%3e)", re.I)


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
        return urlunparse(parsed._replace(fragment=""))
    path = f"{match.group('stem')}{match.group('ext')}"
    # A query may identify a crop or carry a signature. Preserve it exactly.
    return urlunparse(parsed._replace(path=path, fragment=""))


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
    """Bounded zoom/source family; the downloader must compare real pixels."""
    if not is_home_depot_image(value):
        return [value]
    try:
        parsed = urlparse(value)
    except ValueError:
        return [value]
    match = _HOME_DEPOT_SIZE_RE.match(parsed.path)
    if not match or "/productImages/" not in parsed.path:
        return [value]
    stem, ext = match.group("stem"), match.group("ext")
    candidates: list[str] = []
    if home_depot_size_hint(value) > 1000:
        candidates.append(value)
    for width in HOME_DEPOT_WIDTHS:
        candidate = urlunparse(parsed._replace(path=f"{stem}_{width}{ext}"))
        if candidate not in candidates:
            candidates.append(candidate)
    unsized = urlunparse(parsed._replace(path=f"{stem}{ext}"))
    if unsized not in candidates:
        candidates.append(unsized)
    if value not in candidates:
        candidates.append(value)
    return candidates


def home_depot_advertised_urls(value: str, sizes: Iterable[object]) -> list[str]:
    """Resolve only sizes explicitly present beside a product image URL."""
    if not is_home_depot_image(value) or "/productImages/" not in urlparse(value).path:
        return []
    advertised: set[int] = set()
    for raw in sizes:
        if len(advertised) >= 30:
            break
        text = str(raw).strip()
        if text.isdigit() and 0 < int(text) <= 20_000:
            advertised.add(int(text))
    parsed = urlparse(value)
    match = _HOME_DEPOT_SIZE_RE.match(parsed.path)
    result: list[str] = []
    for size in sorted(advertised, reverse=True):
        if _SIZE_PLACEHOLDER_RE.search(value):
            candidate = _SIZE_PLACEHOLDER_RE.sub(str(size), value)
        elif match:
            candidate = urlunparse(parsed._replace(path=f"{match.group('stem')}_{size}{match.group('ext')}"))
        else:
            continue
        if candidate not in result:
            result.append(candidate)
    return result


def build_download_candidates(value: str, base_candidates: Iterable[str] = ()) -> list[str]:
    """Return bounded, high-to-low candidates without changing unrelated CDNs."""
    result: list[str] = []
    # Existing CDN-specific policies (e.g. WeChat /0) already carry an order.
    seeds = [*[str(item) for item in base_candidates if str(item).strip()], value]
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
    """Rank srcset tokens without corrupting commas in CDN/signed URLs."""
    ranked: list[tuple[float, int, str]] = []
    source = str(value or "")
    position = index = 0
    while position < len(source):
        while position < len(source) and (source[position].isspace() or source[position] == ","):
            position += 1
        start = position
        while position < len(source) and not source[position].isspace():
            position += 1
        url = source[start:position]
        descriptors = ""
        if url.endswith(","):
            url = url.rstrip(",")
        else:
            start = position
            while position < len(source) and source[position] != ",":
                position += 1
            descriptors = source[start:position].strip()
        if not url or url.lower().startswith("data:"):
            continue
        rank = 0.0
        if descriptors:
            bits = descriptors.split()
            if len(bits) != 1:
                continue
            descriptor = bits[0].lower()
            try:
                if re.fullmatch(r"[1-9]\d*w", descriptor):
                    rank = float(descriptor[:-1])
                elif re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)x", descriptor) and float(descriptor[:-1]) > 0:
                    rank = float(descriptor[:-1]) * 10_000.0
                else:
                    continue
            except ValueError:
                continue
        ranked.append((rank, -index, url))
        index += 1
    ranked.sort(reverse=True)
    result: list[str] = []
    for _rank, _index, url in ranked:
        if url not in result:
            result.append(url)
    return result


def run_self_test() -> None:
    sample = "https://images.thdstatic.com/productImages/demo/svn/item-64_100.jpg"
    candidates = home_depot_candidates(sample)
    assert candidates[0].endswith("item-64_1000.jpg")
    assert candidates.index(next(item for item in candidates if item.endswith("_1000.jpg"))) < candidates.index(next(item for item in candidates if item.endswith("item-64.jpg")))
    assert candidates[-1] == sample
    assert len(candidates) == 3
    deduped = dedupe_resolution_variants([sample, sample.replace("_100.jpg", "_600.jpg")])
    assert len(deduped) == 1 and deduped[0].endswith("_600.jpg")
    assert parse_srcset("a.jpg 100w, b.jpg 1600w, c.jpg 800w") == ["b.jpg", "c.jpg", "a.jpg"]


if __name__ == "__main__":
    run_self_test()
    print("Image resolution self-test passed")
