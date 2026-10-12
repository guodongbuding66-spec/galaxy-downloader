from __future__ import annotations

"""Bounded local .torrent metadata parsing for selective downloads.

This module intentionally does not fetch remote URLs or Magnet metadata. It only
parses an already-validated local ``.torrent`` file and returns a display-safe
file list with aria2's one-based file indexes.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aria2_source_policy import Aria2SourceError, require_torrent_source

MAX_TORRENT_BYTES = 16 * 1024 * 1024
MAX_BENCODE_DEPTH = 32
MAX_BENCODE_ITEMS = 200_000
MAX_TORRENT_FILES = 20_000
MAX_PATH_COMPONENTS = 128
MAX_PATH_CHARS = 4096
MAX_FILE_SIZE = (1 << 63) - 1


class TorrentMetadataError(ValueError):
    pass


@dataclass(frozen=True)
class TorrentFileEntry:
    index: int
    path: str
    length: int


@dataclass(frozen=True)
class TorrentMetadata:
    name: str
    files: tuple[TorrentFileEntry, ...]
    total_length: int


class _BencodeReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.items = 0

    def _count(self) -> None:
        self.items += 1
        if self.items > MAX_BENCODE_ITEMS:
            raise TorrentMetadataError("Torrent 元数据项目过多")

    def parse(self, depth: int = 0) -> Any:
        if depth > MAX_BENCODE_DEPTH:
            raise TorrentMetadataError("Torrent 元数据嵌套过深")
        if self.pos >= len(self.data):
            raise TorrentMetadataError("Torrent 元数据意外结束")
        self._count()
        token = self.data[self.pos : self.pos + 1]
        if token == b"i":
            return self._integer()
        if token == b"l":
            return self._list(depth + 1)
        if token == b"d":
            return self._dict(depth + 1)
        if b"0" <= token <= b"9":
            return self._bytes()
        raise TorrentMetadataError("Torrent 元数据包含非法 bencode 标记")

    def _integer(self) -> int:
        self.pos += 1
        end = self.data.find(b"e", self.pos)
        if end < 0:
            raise TorrentMetadataError("Torrent 整数字段未结束")
        raw = self.data[self.pos : end]
        if not raw or raw in {b"-0", b"+0"} or raw.startswith(b"+"):
            raise TorrentMetadataError("Torrent 整数字段无效")
        if len(raw) > 1 and raw.startswith(b"0"):
            raise TorrentMetadataError("Torrent 整数字段存在前导零")
        if raw.startswith(b"-") and len(raw) > 2 and raw[1:2] == b"0":
            raise TorrentMetadataError("Torrent 整数字段存在前导零")
        try:
            value = int(raw)
        except ValueError as exc:
            raise TorrentMetadataError("Torrent 整数字段无效") from exc
        self.pos = end + 1
        return value

    def _bytes(self) -> bytes:
        colon = self.data.find(b":", self.pos)
        if colon < 0:
            raise TorrentMetadataError("Torrent 字符串长度字段无效")
        raw_length = self.data[self.pos : colon]
        if not raw_length or (len(raw_length) > 1 and raw_length.startswith(b"0")):
            raise TorrentMetadataError("Torrent 字符串长度字段无效")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise TorrentMetadataError("Torrent 字符串长度字段无效") from exc
        if length < 0 or length > MAX_TORRENT_BYTES:
            raise TorrentMetadataError("Torrent 字符串字段过大")
        start = colon + 1
        end = start + length
        if end > len(self.data):
            raise TorrentMetadataError("Torrent 字符串字段越界")
        self.pos = end
        return self.data[start:end]

    def _list(self, depth: int) -> list[Any]:
        self.pos += 1
        result: list[Any] = []
        while True:
            if self.pos >= len(self.data):
                raise TorrentMetadataError("Torrent 列表字段未结束")
            if self.data[self.pos : self.pos + 1] == b"e":
                self.pos += 1
                return result
            result.append(self.parse(depth))

    def _dict(self, depth: int) -> dict[bytes, Any]:
        self.pos += 1
        result: dict[bytes, Any] = {}
        previous: bytes | None = None
        while True:
            if self.pos >= len(self.data):
                raise TorrentMetadataError("Torrent 字典字段未结束")
            if self.data[self.pos : self.pos + 1] == b"e":
                self.pos += 1
                return result
            key = self._bytes()
            if previous is not None and key < previous:
                raise TorrentMetadataError("Torrent 字典键未按 bencode 规则排序")
            previous = key
            result[key] = self.parse(depth)


def _decode_text(value: object) -> str:
    if not isinstance(value, (bytes, bytearray)):
        return ""
    text = bytes(value).decode("utf-8", errors="replace").strip()
    if not text or any(ord(char) < 0x20 for char in text):
        return ""
    return text[:MAX_PATH_CHARS]


def _name(mapping: dict[bytes, Any]) -> str:
    return _decode_text(mapping.get(b"name.utf-8")) or _decode_text(mapping.get(b"name")) or "Torrent"


def _safe_path(parts: object, fallback: str) -> str:
    if not isinstance(parts, list) or not parts or len(parts) > MAX_PATH_COMPONENTS:
        raise TorrentMetadataError("Torrent 文件路径无效")
    cleaned: list[str] = []
    for part in parts:
        text = _decode_text(part)
        if not text or text in {".", ".."} or "/" in text or "\\" in text or "\x00" in text:
            raise TorrentMetadataError("Torrent 文件路径包含不安全组件")
        cleaned.append(text)
    path = "/".join(cleaned)
    if len(path) > MAX_PATH_CHARS:
        raise TorrentMetadataError("Torrent 文件路径过长")
    return path or fallback


def _safe_length(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > MAX_FILE_SIZE:
        raise TorrentMetadataError("Torrent 文件大小字段无效")
    return value


def parse_torrent_bytes(data: bytes) -> TorrentMetadata:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise TorrentMetadataError("Torrent 文件为空")
    if len(data) > MAX_TORRENT_BYTES:
        raise TorrentMetadataError(f"Torrent 文件过大；最多允许 {MAX_TORRENT_BYTES // (1024 * 1024)} MiB")
    reader = _BencodeReader(bytes(data))
    root = reader.parse()
    if reader.pos != len(data):
        raise TorrentMetadataError("Torrent 文件尾部存在额外数据")
    if not isinstance(root, dict) or not isinstance(root.get(b"info"), dict):
        raise TorrentMetadataError("Torrent 缺少 info 字典")
    info: dict[bytes, Any] = root[b"info"]
    name = _name(info)
    entries: list[TorrentFileEntry] = []

    raw_files = info.get(b"files")
    if raw_files is None:
        length = _safe_length(info.get(b"length"))
        entries.append(TorrentFileEntry(1, name, length))
    else:
        if not isinstance(raw_files, list) or not raw_files:
            raise TorrentMetadataError("Torrent files 列表无效")
        if len(raw_files) > MAX_TORRENT_FILES:
            raise TorrentMetadataError(f"Torrent 文件数量过多；最多允许 {MAX_TORRENT_FILES} 个")
        for index, item in enumerate(raw_files, start=1):
            if not isinstance(item, dict):
                raise TorrentMetadataError("Torrent files 项无效")
            length = _safe_length(item.get(b"length"))
            parts = item.get(b"path.utf-8") or item.get(b"path")
            path = _safe_path(parts, f"file-{index}")
            entries.append(TorrentFileEntry(index, path, length))

    total = sum(item.length for item in entries)
    if total > MAX_FILE_SIZE:
        raise TorrentMetadataError("Torrent 总大小超出支持范围")
    return TorrentMetadata(name=name, files=tuple(entries), total_length=total)


def read_local_torrent_metadata(source: object) -> TorrentMetadata:
    try:
        classified = require_torrent_source(source)
    except Aria2SourceError as exc:
        raise TorrentMetadataError(str(exc)) from exc
    if classified.kind != "torrent_file":
        raise TorrentMetadataError("文件列表预览目前只支持本地 .torrent 文件")
    path = Path(classified.source)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise TorrentMetadataError(f"无法读取 Torrent 文件：{exc}") from exc
    return parse_torrent_bytes(data)


def _b(value: bytes) -> bytes:
    return str(len(value)).encode("ascii") + b":" + value


def _i(value: int) -> bytes:
    return b"i" + str(value).encode("ascii") + b"e"


def run_torrent_metadata_self_test() -> None:
    single_info = b"d6:length" + _i(5) + b"4:name" + _b(b"a.bin") + b"e"
    single = b"d4:info" + single_info + b"e"
    parsed = parse_torrent_bytes(single)
    assert parsed.name == "a.bin"
    assert parsed.files == (TorrentFileEntry(1, "a.bin", 5),)

    file1 = b"d6:length" + _i(3) + b"4:pathl" + _b(b"a.txt") + b"ee"
    file2 = b"d6:length" + _i(7) + b"4:pathl" + _b(b"dir") + _b(b"b.bin") + b"ee"
    multi_info = b"d5:filesl" + file1 + file2 + b"e4:name" + _b(b"bundle") + b"e"
    multi = b"d4:info" + multi_info + b"e"
    parsed_multi = parse_torrent_bytes(multi)
    assert parsed_multi.total_length == 10
    assert [item.index for item in parsed_multi.files] == [1, 2]
    assert [item.path for item in parsed_multi.files] == ["a.txt", "dir/b.bin"]

    unsafe_file = b"d6:length" + _i(1) + b"4:pathl" + _b(b"..") + _b(b"x") + b"ee"
    unsafe_info = b"d5:filesl" + unsafe_file + b"e4:name" + _b(b"bundle") + b"e"
    try:
        parse_torrent_bytes(b"d4:info" + unsafe_info + b"e")
    except TorrentMetadataError:
        pass
    else:
        raise AssertionError("unsafe torrent path was accepted")


if __name__ == "__main__":
    run_torrent_metadata_self_test()
    print("torrent_metadata self-test: OK")
