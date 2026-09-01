from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin, urlparse


def _attrs(tag: str) -> dict[str, str]:
    result: dict[str, str] = {}
    pattern = re.compile(r"([:\w-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))")
    for match in pattern.finditer(tag):
        result[match.group(1).lower()] = html_lib.unescape(match.group(2) or match.group(3) or match.group(4) or "")
    return result


def _absolute_url(raw: str | None, base_url: str) -> str | None:
    value = html_lib.unescape(str(raw or "")).strip().replace("\\/", "/")
    if not value or re.match(r"^(?:data|blob|javascript):", value, re.I):
        return None
    target = urljoin(base_url, value)
    parsed = urlparse(target)
    return target if parsed.scheme in {"http", "https"} and parsed.hostname else None


def _plain(value: str) -> str:
    text = html_lib.unescape(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def _table_markdown(table_html: str) -> str:
    rows: list[list[str]] = []
    for row_match in re.finditer(r"<tr\b[^>]*>([\s\S]*?)</tr>", table_html, re.I):
        cells = [
            _plain(cell.group(1)).replace("|", "\\|").replace("\n", "<br>")
            for cell in re.finditer(r"<(?:th|td)\b[^>]*>([\s\S]*?)</(?:th|td)>", row_match.group(1), re.I)
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return _plain(table_html)
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    lines = [
        "| " + " | ".join(normalized[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
        *("| " + " | ".join(row) + " |" for row in normalized[1:]),
    ]
    return "\n\n" + "\n".join(lines) + "\n\n"


def _wechat_fragment(raw_html: str) -> str:
    marker = re.search(r"\bid=[\"']js_content[\"']", raw_html, re.I)
    if marker is None:
        return ""
    start = raw_html.rfind("<", 0, marker.start())
    if start < 0:
        return ""
    tail = raw_html[start:]
    candidates: list[int] = []
    for pattern in (
        r"\bid=[\"']js_toobar3[\"']",
        r"\bclass=[\"'][^\"']*rich_media_tool",
        r"<script\b",
    ):
        match = re.search(pattern, tail, re.I)
        if match and match.start() > 0:
            candidates.append(match.start())
    end = min(candidates) if candidates else min(len(tail), 2_000_000)
    return tail[:end]


def html_fragment_to_markdown(fragment: str, source_url: str) -> str:
    if not fragment.strip():
        return ""
    value = re.sub(r"<(?:script|style|noscript)\b[^>]*>[\s\S]*?</(?:script|style|noscript)>", "", fragment, flags=re.I)
    value = re.sub(r"<table\b[^>]*>[\s\S]*?</table>", lambda match: _table_markdown(match.group(0)), value, flags=re.I)
    value = re.sub(
        r"<pre\b[^>]*>([\s\S]*?)</pre>",
        lambda match: "\n\n```\n" + html_lib.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip() + "\n```\n\n",
        value,
        flags=re.I,
    )

    def image_replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        values = _attrs(tag)
        raw = values.get("data-src") or values.get("data-original") or values.get("data-lazy-src") or values.get("data-actualsrc") or values.get("src")
        target = _absolute_url(raw, source_url)
        if not target:
            return ""
        alt = _plain(values.get("alt") or values.get("title") or "image").replace("[", "").replace("]", "") or "image"
        return f"\n\n![{alt}]({target})\n\n"

    value = re.sub(r"<img\b[^>]*>", image_replace, value, flags=re.I)

    def link_replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        opening = re.match(r"<a\b[^>]*>", tag, re.I)
        values = _attrs(opening.group(0) if opening else "")
        inner = re.sub(r"^<a\b[^>]*>|</a>$", "", tag, flags=re.I)
        text = _plain(inner) or values.get("title") or values.get("href") or "link"
        target = _absolute_url(values.get("href"), source_url)
        return f"[{text.replace('[', '').replace(']', '')}]({target})" if target else text

    value = re.sub(r"<a\b[^>]*>[\s\S]*?</a>", link_replace, value, flags=re.I)
    for level in range(1, 7):
        prefix = "#" * min(level, 4)
        value = re.sub(
            rf"<h{level}\b[^>]*>([\s\S]*?)</h{level}>",
            lambda match, p=prefix: f"\n\n{p} {_plain(match.group(1))}\n\n",
            value,
            flags=re.I,
        )
    value = re.sub(
        r"<blockquote\b[^>]*>([\s\S]*?)</blockquote>",
        lambda match: "\n\n" + "\n".join(f"> {line}" for line in _plain(match.group(1)).splitlines()) + "\n\n",
        value,
        flags=re.I,
    )
    value = re.sub(r"<li\b[^>]*>([\s\S]*?)</li>", lambda match: "\n- " + _plain(match.group(1)), value, flags=re.I)
    value = re.sub(r"<(?:strong|b)\b[^>]*>([\s\S]*?)</(?:strong|b)>", lambda match: f"**{_plain(match.group(1))}**", value, flags=re.I)
    value = re.sub(r"<(?:em|i)\b[^>]*>([\s\S]*?)</(?:em|i)>", lambda match: f"*{_plain(match.group(1))}*", value, flags=re.I)
    value = re.sub(r"<code\b[^>]*>([\s\S]*?)</code>", lambda match: "`" + _plain(match.group(1)).replace("`", "\\`") + "`", value, flags=re.I)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</(?:p|div|section|article|ul|ol)>", "\n\n", value, flags=re.I)
    value = re.sub(r"<(?:p|div|section|article|ul|ol)\b[^>]*>", "", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    value = html_lib.unescape(value).replace("\r", "")
    value = re.sub(r"[\t\f\v ]+\n", "\n", value)
    value = re.sub(r"\n[\t\f\v ]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    return value + "\n" if value else ""


def extract_document_markdown(source_url: str, raw_html: str, platform: str) -> str:
    if platform != "wechat":
        return ""
    return html_fragment_to_markdown(_wechat_fragment(raw_html), source_url)
