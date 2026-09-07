from __future__ import annotations

import html
import re
import sqlite3
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from reader_workspace import ReaderWorkspaceError, reader_database_path

MAX_EPUB_XML_BYTES = 8 * 1024 * 1024
MAX_EPUB_CHAPTER_BYTES = 32 * 1024 * 1024
MAX_EPUB_CHAPTER_CHARS = 2_000_000
MAX_EPUB_CHAPTERS = 5_000
MAX_EPUB_TOC_ITEMS = 10_000
_EPUB_CHAPTER_ID_RE = re.compile(r"^epub-chapter:(\d{1,5})$")
_BOOK_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_HTML_EXTENSIONS = frozenset({".xhtml", ".html", ".htm"})
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "blockquote",
        "pre",
        "tr",
    }
)
_IGNORED_TAGS = frozenset({"script", "style", "svg", "noscript", "template"})


class EpubDocumentError(RuntimeError):
    pass


@dataclass(frozen=True)
class _EpubChapter:
    chapter_id: str
    index: int
    path: Path
    title: str


@dataclass(frozen=True)
class _EpubModel:
    book_id: str
    root: Path
    opf_path: Path
    chapters: tuple[_EpubChapter, ...]
    toc: tuple[dict[str, Any], ...]


class _ChapterTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self._ignored_depth = 0
        self._title_depth = 0
        self._heading_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        clean = tag.lower()
        if clean in _IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if clean == "title":
            self._title_depth += 1
        if clean in {"h1", "h2", "h3"} and not self.heading_parts:
            self._heading_depth += 1
        if clean in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        clean = tag.lower()
        if clean in _IGNORED_TAGS:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if clean == "title" and self._title_depth:
            self._title_depth -= 1
        if clean in {"h1", "h2", "h3"} and self._heading_depth:
            self._heading_depth -= 1
        if clean in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        self.parts.append(data)
        if self._title_depth:
            self.title_parts.append(data)
        if self._heading_depth and not self.heading_parts:
            self.heading_parts.append(data)

    @staticmethod
    def _clean(value: str, limit: int) -> str:
        return " ".join(html.unescape(value).replace("\x00", " ").split()).strip()[:limit]

    def title(self, fallback: str) -> str:
        title = self._clean("".join(self.title_parts), 240)
        if title:
            return title
        heading = self._clean("".join(self.heading_parts), 240)
        return heading or fallback

    def text(self) -> str:
        raw = html.unescape("".join(self.parts)).replace("\x00", " ")
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line).strip()[:MAX_EPUB_CHAPTER_CHARS]


def _clean_book_id(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _BOOK_ID_RE.fullmatch(clean):
        raise EpubDocumentError("invalid EPUB book id")
    return clean


def _chapter_id(index: int) -> str:
    return f"epub-chapter:{index + 1}"


def _chapter_index(value: object, total: int) -> int:
    clean = str(value or "").strip().lower()
    match = _EPUB_CHAPTER_ID_RE.fullmatch(clean)
    if match is None:
        raise EpubDocumentError("invalid EPUB chapter id")
    index = int(match.group(1)) - 1
    if index < 0 or index >= total:
        raise EpubDocumentError("EPUB chapter not found")
    return index


def _managed_content_root(engine_module, book_id: object) -> tuple[str, Path]:
    clean = _clean_book_id(book_id)
    try:
        with sqlite3.connect(reader_database_path(engine_module), timeout=5.0) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT format, content_root FROM books WHERE id=?",
                (clean,),
            ).fetchone()
    except (sqlite3.Error, ReaderWorkspaceError) as exc:
        raise EpubDocumentError("EPUB metadata is unavailable") from exc
    if row is None:
        raise EpubDocumentError("EPUB book not found")
    if str(row["format"] or "").strip().lower() != "epub":
        raise EpubDocumentError("book is not EPUB")

    accessor = getattr(engine_module, "data_dir", None)
    if not callable(accessor):
        raise EpubDocumentError("Reader data directory is unavailable")
    expected = Path(accessor()) / "reader" / "books" / clean / "content"
    stored = Path(str(row["content_root"] or ""))
    try:
        resolved = stored.resolve(strict=True)
        expected_resolved = expected.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise EpubDocumentError("EPUB content root is unavailable") from exc
    if stored.is_symlink() or not resolved.is_dir() or resolved != expected_resolved:
        raise EpubDocumentError("EPUB content root failed Reader boundary validation")
    return clean, resolved


def _read_bounded(path: Path, limit: int, *, label: str) -> bytes:
    if path.is_symlink():
        raise EpubDocumentError(f"{label} cannot be a symbolic link")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise EpubDocumentError(f"{label} is unavailable") from exc
    if size <= 0 or size > limit:
        raise EpubDocumentError(f"{label} exceeds the safe size limit")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise EpubDocumentError(f"{label} is unavailable") from exc
    if len(payload) > limit:
        raise EpubDocumentError(f"{label} exceeds the safe size limit")
    return payload


def _parse_xml(path: Path, *, label: str) -> ElementTree.Element:
    payload = _read_bounded(path, MAX_EPUB_XML_BYTES, label=label)
    upper = payload[: min(len(payload), 256 * 1024)].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise EpubDocumentError(f"{label} contains unsupported XML declarations")
    try:
        return ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise EpubDocumentError(f"{label} is malformed") from exc


def _resolve_reference(root: Path, base_dir: Path, reference: object, *, require_html: bool = False) -> Path:
    raw = str(reference or "").strip()
    if not raw or "\x00" in raw:
        raise EpubDocumentError("EPUB reference is empty")
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        raise EpubDocumentError("external EPUB reference is not allowed")
    decoded = unquote(parsed.path).replace("\\", "/")
    if not decoded or decoded.startswith("/"):
        raise EpubDocumentError("absolute EPUB reference is not allowed")
    rel = PurePosixPath(decoded)
    if rel.parts and re.match(r"^[A-Za-z]:", rel.parts[0]):
        raise EpubDocumentError("drive EPUB reference is not allowed")
    try:
        candidate = base_dir.joinpath(*rel.parts).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise EpubDocumentError("EPUB reference escaped the managed root") from exc
    if candidate.is_symlink() or not candidate.is_file():
        raise EpubDocumentError("EPUB reference is unavailable")
    if require_html and candidate.suffix.lower() not in _HTML_EXTENSIONS:
        raise EpubDocumentError("EPUB chapter reference is not HTML")
    return candidate


def _container_opf(root: Path) -> Path:
    container = root / "META-INF" / "container.xml"
    tree = _parse_xml(container, label="EPUB container")
    rootfile = next((node for node in tree.iter() if node.tag.endswith("rootfile")), None)
    if rootfile is None or not rootfile.attrib.get("full-path"):
        raise EpubDocumentError("EPUB container has no rootfile")
    return _resolve_reference(root, root, rootfile.attrib["full-path"])


def _manifest_and_spine(root: Path, opf: Path) -> tuple[dict[str, dict[str, str]], list[Path], ElementTree.Element]:
    package = _parse_xml(opf, label="EPUB package")
    manifest: dict[str, dict[str, str]] = {}
    for node in package.iter():
        if not node.tag.endswith("item"):
            continue
        item_id = str(node.attrib.get("id") or "").strip()
        href = str(node.attrib.get("href") or "").strip()
        if not item_id or not href:
            continue
        manifest[item_id] = {
            "href": href,
            "mediaType": str(node.attrib.get("media-type") or "").strip(),
            "properties": str(node.attrib.get("properties") or "").strip(),
        }
    spine: list[Path] = []
    for node in package.iter():
        if not node.tag.endswith("itemref"):
            continue
        item = manifest.get(str(node.attrib.get("idref") or "").strip())
        if not item:
            continue
        try:
            path = _resolve_reference(root, opf.parent, item["href"], require_html=True)
        except EpubDocumentError:
            continue
        if path not in spine:
            spine.append(path)
        if len(spine) >= MAX_EPUB_CHAPTERS:
            break
    if not spine:
        raise EpubDocumentError("EPUB spine contains no readable chapters")
    return manifest, spine, package


def _parse_chapter(path: Path) -> tuple[str, str, bool]:
    payload = _read_bounded(path, MAX_EPUB_CHAPTER_BYTES, label="EPUB chapter")
    truncated = False
    if len(payload) >= MAX_EPUB_CHAPTER_BYTES:
        truncated = True
    value = payload.decode("utf-8", errors="replace")
    parser = _ChapterTextParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception as exc:
        raise EpubDocumentError("EPUB chapter HTML is malformed") from exc
    fallback = "Chapter"
    title = parser.title(fallback)
    text = parser.text()
    if len(text) >= MAX_EPUB_CHAPTER_CHARS:
        truncated = True
    return title, text, truncated


def _safe_toc_title(value: object, fallback: str) -> str:
    clean = " ".join(html.unescape(str(value or "")).replace("\x00", " ").split()).strip()[:240]
    return clean or fallback


def _chapter_lookup(spine: list[Path]) -> dict[Path, int]:
    return {path: index for index, path in enumerate(spine)}


def _nav_toc(root: Path, opf: Path, manifest: dict[str, dict[str, str]], spine: list[Path]) -> list[dict[str, Any]]:
    nav_item = next(
        (
            item
            for item in manifest.values()
            if "nav" in set(item.get("properties", "").split())
        ),
        None,
    )
    if nav_item is None:
        return []
    try:
        nav_path = _resolve_reference(root, opf.parent, nav_item["href"], require_html=True)
        nav_root = _parse_xml(nav_path, label="EPUB navigation")
    except EpubDocumentError:
        return []

    toc_nav = None
    for node in nav_root.iter():
        if not node.tag.endswith("nav"):
            continue
        attrs = {str(key).split("}")[-1].lower(): str(value).lower() for key, value in node.attrib.items()}
        if attrs.get("type") == "toc" or attrs.get("role") == "doc-toc":
            toc_nav = node
            break
    if toc_nav is None:
        toc_nav = next((node for node in nav_root.iter() if node.tag.endswith("nav")), None)
    if toc_nav is None:
        return []

    lookup = _chapter_lookup(spine)
    result: list[dict[str, Any]] = []

    def walk_list(node: ElementTree.Element, depth: int) -> None:
        for child in list(node):
            if not child.tag.endswith("li"):
                if child.tag.endswith("ol"):
                    walk_list(child, depth)
                continue
            anchor = next((item for item in list(child) if item.tag.endswith("a") and item.attrib.get("href")), None)
            if anchor is not None:
                try:
                    target = _resolve_reference(root, nav_path.parent, anchor.attrib["href"], require_html=True)
                except EpubDocumentError:
                    target = None
                index = lookup.get(target) if target is not None else None
                if index is not None:
                    title = _safe_toc_title("".join(anchor.itertext()), f"Chapter {index + 1}")
                    result.append({"chapterId": _chapter_id(index), "title": title, "depth": max(0, min(depth, 32))})
            for nested in list(child):
                if nested.tag.endswith("ol") and len(result) < MAX_EPUB_TOC_ITEMS:
                    walk_list(nested, depth + 1)
            if len(result) >= MAX_EPUB_TOC_ITEMS:
                return

    first_list = next((node for node in list(toc_nav) if node.tag.endswith("ol")), None)
    if first_list is not None:
        walk_list(first_list, 0)
    return result[:MAX_EPUB_TOC_ITEMS]


def _ncx_toc(root: Path, opf: Path, manifest: dict[str, dict[str, str]], spine: list[Path]) -> list[dict[str, Any]]:
    ncx_item = next(
        (item for item in manifest.values() if item.get("mediaType") == "application/x-dtbncx+xml"),
        None,
    )
    if ncx_item is None:
        return []
    try:
        ncx_path = _resolve_reference(root, opf.parent, ncx_item["href"])
        ncx_root = _parse_xml(ncx_path, label="EPUB NCX")
    except EpubDocumentError:
        return []
    lookup = _chapter_lookup(spine)
    result: list[dict[str, Any]] = []

    def label(node: ElementTree.Element, fallback: str) -> str:
        nav_label = next((item for item in list(node) if item.tag.endswith("navLabel")), None)
        if nav_label is None:
            return fallback
        return _safe_toc_title("".join(nav_label.itertext()), fallback)

    def walk(node: ElementTree.Element, depth: int) -> None:
        for point in list(node):
            if not point.tag.endswith("navPoint"):
                continue
            content = next((item for item in list(point) if item.tag.endswith("content") and item.attrib.get("src")), None)
            if content is not None:
                try:
                    target = _resolve_reference(root, ncx_path.parent, content.attrib["src"], require_html=True)
                except EpubDocumentError:
                    target = None
                index = lookup.get(target) if target is not None else None
                if index is not None:
                    result.append(
                        {
                            "chapterId": _chapter_id(index),
                            "title": label(point, f"Chapter {index + 1}"),
                            "depth": max(0, min(depth, 32)),
                        }
                    )
            if len(result) >= MAX_EPUB_TOC_ITEMS:
                return
            walk(point, depth + 1)
            if len(result) >= MAX_EPUB_TOC_ITEMS:
                return

    nav_map = next((node for node in ncx_root.iter() if node.tag.endswith("navMap")), None)
    if nav_map is not None:
        walk(nav_map, 0)
    return result[:MAX_EPUB_TOC_ITEMS]


def _dedupe_toc(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for row in rows:
        key = (str(row.get("chapterId") or ""), str(row.get("title") or ""), int(row.get("depth") or 0))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        result.append({"chapterId": key[0], "title": key[1], "depth": key[2]})
        if len(result) >= MAX_EPUB_TOC_ITEMS:
            break
    return result


def _load_model(engine_module, book_id: object) -> _EpubModel:
    clean, root = _managed_content_root(engine_module, book_id)
    opf = _container_opf(root)
    manifest, spine, _package = _manifest_and_spine(root, opf)

    toc = _nav_toc(root, opf, manifest, spine)
    if not toc:
        toc = _ncx_toc(root, opf, manifest, spine)

    toc_titles: dict[str, str] = {}
    for row in toc:
        chapter = str(row.get("chapterId") or "")
        if chapter and chapter not in toc_titles:
            toc_titles[chapter] = _safe_toc_title(row.get("title"), chapter)

    chapters: list[_EpubChapter] = []
    for index, path in enumerate(spine):
        chapter_id = _chapter_id(index)
        title = toc_titles.get(chapter_id)
        if not title:
            try:
                parsed_title, _text, _truncated = _parse_chapter(path)
            except EpubDocumentError:
                parsed_title = ""
            title = _safe_toc_title(parsed_title, f"Chapter {index + 1}")
        chapters.append(_EpubChapter(chapter_id, index, path, title))

    if not toc:
        toc = [
            {"chapterId": chapter.chapter_id, "title": chapter.title, "depth": 0}
            for chapter in chapters
        ]
    return _EpubModel(clean, root, opf, tuple(chapters), tuple(_dedupe_toc(toc)))


def epub_document(engine_module, book_id: object) -> dict[str, Any]:
    model = _load_model(engine_module, book_id)
    return {
        "bookId": model.book_id,
        "chapterCount": len(model.chapters),
        "chapters": [
            {"id": chapter.chapter_id, "index": chapter.index, "title": chapter.title}
            for chapter in model.chapters
        ],
        "toc": [dict(row) for row in model.toc],
    }


def epub_chapter(engine_module, book_id: object, chapter_id: object) -> dict[str, Any]:
    model = _load_model(engine_module, book_id)
    index = _chapter_index(chapter_id, len(model.chapters))
    chapter = model.chapters[index]
    parsed_title, text, truncated = _parse_chapter(chapter.path)
    title = chapter.title or _safe_toc_title(parsed_title, f"Chapter {index + 1}")
    return {
        "bookId": model.book_id,
        "chapterId": chapter.chapter_id,
        "index": chapter.index,
        "title": title,
        "text": text,
        "truncated": bool(truncated),
        "previousChapterId": _chapter_id(index - 1) if index > 0 else None,
        "nextChapterId": _chapter_id(index + 1) if index + 1 < len(model.chapters) else None,
    }


def run_reader_epub_self_test() -> None:
    assert _chapter_id(0) == "epub-chapter:1"
    assert _chapter_index("epub-chapter:2", 3) == 1
    assert _safe_toc_title("  Chapter   One  ", "Fallback") == "Chapter One"
    assert _dedupe_toc(
        [
            {"chapterId": "epub-chapter:1", "title": "One", "depth": 0},
            {"chapterId": "epub-chapter:1", "title": "One", "depth": 0},
        ]
    ) == [{"chapterId": "epub-chapter:1", "title": "One", "depth": 0}]
