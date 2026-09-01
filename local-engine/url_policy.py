from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class PublicUrlError(ValueError):
    pass


def _ip_is_public(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(address.is_global)


def _host_is_public(hostname: str) -> bool:
    host = hostname.strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False
    if "%" in host:
        # IPv6 zone identifiers are local-interface selectors and must never be
        # accepted by a browser-triggerable localhost bridge.
        return False

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        return bool(address.is_global)

    try:
        resolved = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        # Fail closed. If DNS cannot currently establish that the destination is
        # public, yt-dlp cannot safely be allowed to resolve it a second time.
        return False

    addresses: set[str] = set()
    for entry in resolved:
        try:
            addresses.add(str(entry[4][0]))
        except (IndexError, TypeError):
            continue
    if not addresses:
        return False
    return all(_ip_is_public(value) for value in addresses)


def is_public_http_url(value: str) -> bool:
    candidate = str(value or "").strip()
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    return _host_is_public(parsed.hostname)


def validated_public_http_url(value: str) -> str:
    candidate = str(value or "").strip()
    if not is_public_http_url(candidate):
        raise PublicUrlError("A public http(s) media URL is required")
    return candidate
