from __future__ import annotations

"""Strict source recognition and canonical BTIH normalization for Galaxy.

Torrent recognition remains separate from Galaxy's normal HTTP(S) media URL
policy. Ordinary HTTP/HTTPS URLs stay on the existing media pipeline unless they
are explicitly HTTPS URLs whose path ends in ``.torrent``. Valid v1 Magnet BTIH
values are canonicalized to lowercase 40-character hexadecimal form so 40-hex
and 32-base32 representations of the same info-hash share one stable identity.
"""

import base64
import binascii
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

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


def normalize_btih(value: object) -> str:
    """Return one canonical lowercase 40-hex representation of a v1 BTIH."""
    text = str(value or "").strip()
    if _has_control_chars(text):
        raise Aria2SourceError("BTIH 包含控制字符")
    if _BTIH_HEX_RE.fullmatch(text):
        return text.lower()
    if not _BTIH_BASE32_RE.fullmatch(text):
        raise Aria2SourceError("BTIH 必须是 40 位 Hex 或 32 位 Base32")
    try:
        raw = base64.b32decode(text.upper(), casefold=True)
    except (binascii.Error, ValueError) as exc:
        raise Aria2SourceError("BTIH Base32 编码无效") from exc
    if len(raw) != 20:
        raise Aria2SourceError("BTIH 必须解码为 20 字节 info-hash")
    return raw.hex()


def _valid_btih(value: str) -> bool:
    try:
        normalize_btih(value)
    except Aria2SourceError:
        return False
    return True


def validate_magnet_uri(value: object) -> str:
    """Validate and canonicalize the v1 BTIH exact-topic inside a Magnet URI."""
    text = _clean_source(value)
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise Aria2SourceError("Magnet 链接格式无效") from exc
    if parsed.scheme.lower() != "magnet" or parsed.netloc or parsed.path:
        raise Aria2SourceError("Magnet 链接格式无效")
    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=False)
    except ValueError as exc:
        raise Aria2SourceError("Magnet 查询参数无效") from exc

    canonical_btih: str | None = None
    normalized_pairs: list[tuple[str, str]] = []
    btih_emitted = False
    for key, raw_value in pairs:
        if _has_control_chars(key) or _has_control_chars(raw_value):
            raise Aria2SourceError("Magnet 链接包含控制字符")
        if key.lower() != "xt":
            normalized_pairs.append((key, raw_value))
            continue
        prefix = "urn:btih:"
        if raw_value[: len(prefix)].lower() != prefix:
            normalized_pairs.append((key, raw_value))
            continue
        info_hash = raw_value[len(prefix) :]
        normalized_hash = normalize_btih(info_hash)
        if canonical_btih is None:
            canonical_btih = normalized_hash
        elif canonical_btih != normalized_hash:
            raise Aria2SourceError("Magnet 包含相互冲突的 BTIH info-hash")
        if not btih_emitted:
            normalized_pairs.append(("xt", f"urn:btih:{normalized_hash}"))
            btih_emitted = True

    if canonical_btih is None:
        raise Aria2SourceError("Magnet 必须包含有效的 xt=urn:btih:，支持 40 位 Hex 或 32 位 Base32")

    canonical = "magnet:?" + urlencode(normalized_pairs, doseq=True, safe=":/")
    if len(canonical) > MAX_ARIA2_SOURCE_LENGTH:
        raise Aria2SourceError(f"规范化后的 Magnet 过长；最多允许 {MAX_ARIA2_SOURCE_LENGTH} 个字符")
    return canonical


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
    valid_hex_upper = valid_hex.upper()
    valid_base32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    base32_hex = "00443214c74254b635cf84653a56d7c675be77df"

    assert normalize_btih(valid_hex_upper) == valid_hex
    assert normalize_btih(valid_base32) == base32_hex

    magnet_hex = require_torrent_source(f"magnet:?xt=urn:btih:{valid_hex_upper}&dn=Galaxy")
    assert magnet_hex.kind == "magnet"
    assert f"xt=urn:btih:{valid_hex}" in magnet_hex.source
    assert valid_hex_upper not in magnet_hex.source

    magnet_b32 = require_torrent_source(f"magnet:?dn=Galaxy&xt=urn%3Abtih%3A{valid_base32}")
    assert magnet_b32.kind == "magnet"
    assert f"xt=urn:btih:{base32_hex}" in magnet_b32.source
    assert valid_base32 not in magnet_b32.source

    same_b32 = base64.b32encode(bytes.fromhex(valid_hex)).decode("ascii")
    duplicate = require_torrent_source(
        f"magnet:?xt=urn:btih:{valid_hex_upper}&xt=urn:btih:{same_b32}&dn=Galaxy"
    )
    assert duplicate.source.count("urn:btih:") == 1
    assert f"xt=urn:btih:{valid_hex}" in duplicate.source

    conflicting = "89abcdef0123456789abcdef0123456789abcdef"
    try:
        require_torrent_source(f"magnet:?xt=urn:btih:{valid_hex}&xt=urn:btih:{conflicting}")
    except Aria2SourceError:
        pass
    else:
        raise AssertionError("conflicting BTIH values were accepted")

    for invalid in (
        "magnet:?dn=no-hash",
        "magnet:?xt=urn:btih:1234",
        "magnet:?xt=urn:sha1:0123456789abcdef0123456789abcdef01234567",
        "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567\nInjected",
        f"magnet:?xt=urn:btih:{valid_hex}\x80",
        "x" * (MAX_ARIA2_SOURCE_LENGTH + 1),
    ):
        try:
            require_torrent_source(invalid)
        except Aria2SourceError:
            pass
        else:
            raise AssertionError(f"invalid torrent source accepted: {invalid[:80]!r}")

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
