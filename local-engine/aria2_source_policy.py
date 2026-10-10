from __future__ import annotations

"""Strict source recognition for Galaxy Torrent / Magnet transfers.

This module intentionally keeps torrent recognition separate from Galaxy's normal
HTTP(S) media URL policy. Ordinary HTTP/HTTPS URLs remain on the existing media
pipeline unless they are explicitly HTTPS URLs whose path ends in ``.torrent``.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

MAX_ARIA2_SOURCE_LENGTH = 8192
TORRENT_FILE_MAX_BYTES = 10 * 1024 * 1024
_BTIH_HEX_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_BTIH_BASE32_RE = re.compile(r"^[a-z2-7]{32}$", re.IGNORECASE)
_WINDOWS_DRIVE_RE = re.compile(r"^[a-zA-Z]:[\\/]")


class Aria2SourceError(ValueError):
    pass


@dataclass(frozen=True)
class Aria2Source:
    source: str
    kind: str


def _has_control_chars(value: str) -> bool:
    return any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in value)


def _clean_source(value: object) -> str:
    text = str(value or "")
    if len(text) > MAX_ARIA2_SOURCE_LENGTH:
        raise Aria2SourceError(f"下载来源过长；最多允许 {MAX_ARIA2_SOURCE_LENGTH} 个字符")
    if _has_control_chars(text):
        raise Aria2SourceError("下载来源包含控制字符")
    text = text.strip()
    if not text:
        raise Aria2SourceError("请输入 Magnet 链接、HTTPS .torrent 地址或本地 .torrent 文件")
    return text


def _valid_btih(value: str) -> bool:
    return bool(_BTIH_HEX_RE.fullmatch(value) or _BTIH_BASE32_RE.fullmatch(value))


def validate_magnet_uri(value: object) -> str:
    text = _clean_source(value)
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise Aria2SourceError("Magnet 链接格式无效") from exc
    if parsed.scheme.lower() != "magnet" or parsed.netloc or parsed.path:
        raise Aria2SourceError("Magnet 链接格式无效")
    valid_xt = False
    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=False)
    except ValueError as exc:
        raise Aria2SourceError("Magnet 查询参数无效") from exc
    for key, raw_value in pairs:
        if _has_control_chars(key) or _has_control_chars(raw_value):
            raise Aria2SourceError("Magnet 链接包含控制字符")
        if key.lower() != "xt":
            continue
        prefix = "urn:btih:"
        if raw_value[: len(prefix)].lower() != prefix:
            continue
        info_hash = raw_value[len(prefix) :]
        if _valid_btih(info_hash):
            valid_xt = True
            break
    if not valid_xt:
        raise Aria2SourceError("Magnet 必须包含有效的 xt=urn:btih:，支持 40 位 Hex 或 32 位 Base32")
    return text


def _https_torrent_url(text: str) -> Aria2Source | None:
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise Aria2SourceError("Torrent URL 格式无效") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    if parsed.username or parsed.password:
        raise Aria2SourceError("Torrent URL 不能包含用户名或密码")
    if not parsed.hostname:
        raise Aria2SourceError("Torrent URL 缺少有效主机名")
    if scheme == "https" and parsed.path.lower().endswith(".torrent"):
        return Aria2Source(text, "torrent_url")
    return None


def _local_torrent_file(text: str) -> Aria2Source:
    raw = Path(text).expanduser()
    if raw.is_symlink():
        raise Aria2SourceError("torrent 文件不能是符号链接")
    try:
        path = raw.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise Aria2SourceError("请选择存在的 .torrent 文件") from exc
    if not path.is_file() or path.suffix.lower() != ".torrent":
        raise Aria2SourceError("请选择存在的 .torrent 文件")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise Aria2SourceError(str(exc)) from exc
    if size <= 0 or size > TORRENT_FILE_MAX_BYTES:
        raise Aria2SourceError("torrent 文件为空或超过 10 MB")
    return Aria2Source(str(path), "torrent_file")


def classify_torrent_source(value: object) -> Aria2Source | None:
    """Classify an aria2 torrent source without hijacking ordinary HTTP(S).

    ``None`` means the value is an ordinary HTTP/HTTPS URL and must stay on the
    existing non-torrent pipeline. Invalid Magnet/custom/local inputs raise.
    """

    text = _clean_source(value)
    lower = text.lower()
    if lower.startswith("magnet:"):
        return Aria2Source(validate_magnet_uri(text), "magnet")

    remote = _https_torrent_url(text)
    if remote is not None:
        return remote

    # HTTP .torrent is intentionally not promoted: only HTTPS remote torrent
    # sources are accepted by the V2 boundary. All other ordinary HTTP(S) URLs
    # remain untouched by the existing downloader.
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise Aria2SourceError("下载来源格式无效") from exc
    if parsed.scheme.lower() in {"http", "https"}:
        return None

    # Windows drive paths look like a URI scheme to urlsplit(). Treat only that
    # exact shape as a local path; all other explicit schemes fail closed.
    if parsed.scheme and not _WINDOWS_DRIVE_RE.match(text):
        raise Aria2SourceError("Torrent 仅支持 Magnet、HTTPS .torrent 地址或本地 .torrent 文件")
    return _local_torrent_file(text)


def require_torrent_source(value: object) -> Aria2Source:
    source = classify_torrent_source(value)
    if source is None:
        raise Aria2SourceError("Torrent 模式仅接受 Magnet、HTTPS .torrent 地址或本地 .torrent 文件")
    return source


def run_aria2_source_policy_self_test() -> None:
    import tempfile

    valid_hex = "0123456789abcdef0123456789abcdef01234567"
    valid_base32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    magnet_hex = require_torrent_source(f"magnet:?xt=urn:btih:{valid_hex}&dn=Galaxy")
    assert magnet_hex.kind == "magnet"
    magnet_b32 = require_torrent_source(f"magnet:?dn=Galaxy&xt=urn%3Abtih%3A{valid_base32}")
    assert magnet_b32.kind == "magnet"

    for invalid in (
        "magnet:?dn=no-hash",
        "magnet:?xt=urn:btih:1234",
        "magnet:?xt=urn:sha1:0123456789abcdef0123456789abcdef01234567",
        "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567\nInjected",
    ):
        try:
            require_torrent_source(invalid)
        except Aria2SourceError:
            pass
        else:
            raise AssertionError(f"invalid magnet accepted: {invalid!r}")

    remote = require_torrent_source("https://downloads.example.com/demo.TORRENT?token=abc#fragment")
    assert remote.kind == "torrent_url"
    assert remote.source.endswith("?token=abc#fragment")
    assert classify_torrent_source("https://example.com/file.zip") is None
    assert classify_torrent_source("http://example.com/file.torrent") is None

    try:
        require_torrent_source("ftp://example.com/file.torrent")
    except Aria2SourceError:
        pass
    else:
        raise AssertionError("custom/ftp scheme was accepted")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "demo.torrent"
        path.write_bytes(b"d4:infod4:name4:demoe")
        local = require_torrent_source(path)
        assert local.kind == "torrent_file"
        assert Path(local.source) == path.resolve()


if __name__ == "__main__":
    run_aria2_source_policy_self_test()
    print("aria2_source_policy self-test: OK")
