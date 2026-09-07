from __future__ import annotations

import re
from typing import Any

from reader_epub import EpubDocumentError, _load_model, _parse_chapter

MAX_EPUB_SEARCH_QUERY_CHARS = 200
MAX_EPUB_SEARCH_RESULTS = 500
MAX_EPUB_SEARCH_SCAN_CHARS = 20_000_000
MAX_EPUB_SEARCH_SNIPPET_CHARS = 320


class EpubSearchError(RuntimeError):
    pass


def _clean_query(value: object) -> str:
    clean = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    if not clean:
        raise EpubSearchError("EPUB search query is required")
    return clean[:MAX_EPUB_SEARCH_QUERY_CHARS]


def _bounded_limit(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 100
    return max(1, min(parsed, MAX_EPUB_SEARCH_RESULTS))


def _snippet(text: str, start: int, length: int) -> tuple[str, int]:
    if not text:
        return "", 0
    before = 110
    after = MAX_EPUB_SEARCH_SNIPPET_CHARS - before
    left = max(0, start - before)
    right = min(len(text), start + max(1, length) + after)
    value = text[left:right].replace("\x00", " ").strip()
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return (prefix + value + suffix)[: MAX_EPUB_SEARCH_SNIPPET_CHARS + 2], left


def epub_search(
    engine_module,
    book_id: object,
    query: object,
    *,
    limit: object = 100,
) -> dict[str, Any]:
    clean_query = _clean_query(query)
    safe_limit = _bounded_limit(limit)
    try:
        model = _load_model(engine_module, book_id)
    except EpubDocumentError as exc:
        raise EpubSearchError(str(exc)) from exc

    matcher = re.compile(re.escape(clean_query), re.IGNORECASE)
    results: list[dict[str, Any]] = []
    scanned = 0
    truncated = False

    for chapter in model.chapters:
        try:
            _parsed_title, text, chapter_truncated = _parse_chapter(chapter.path)
        except EpubDocumentError:
            continue
        remaining = MAX_EPUB_SEARCH_SCAN_CHARS - scanned
        if remaining <= 0:
            truncated = True
            break
        if len(text) > remaining:
            text = text[:remaining]
            truncated = True
        scanned += len(text)
        for match in matcher.finditer(text):
            offset = match.start()
            match_length = max(1, match.end() - match.start())
            snippet, snippet_start = _snippet(text, offset, match_length)
            results.append(
                {
                    "chapterId": chapter.chapter_id,
                    "chapterTitle": chapter.title,
                    "offset": offset,
                    "length": match_length,
                    "snippet": snippet,
                    "snippetStart": snippet_start,
                }
            )
            if len(results) >= safe_limit:
                return {
                    "bookId": model.book_id,
                    "query": clean_query,
                    "results": results,
                    "limit": safe_limit,
                    "scannedChars": scanned,
                    "truncated": True,
                }
        if chapter_truncated:
            truncated = True

    return {
        "bookId": model.book_id,
        "query": clean_query,
        "results": results,
        "limit": safe_limit,
        "scannedChars": scanned,
        "truncated": truncated,
    }


def run_reader_epub_search_self_test() -> None:
    assert _clean_query("  galaxy   reader ") == "galaxy reader"
    assert _bounded_limit(0) == 1
    assert _bounded_limit(9999) == MAX_EPUB_SEARCH_RESULTS
    preview, start = _snippet("0123456789", 4, 2)
    assert preview == "0123456789" and start == 0
    unicode_match = re.compile(re.escape("istanbul"), re.IGNORECASE).search("İstanbul")
    assert unicode_match is not None and unicode_match.start() == 0
