from __future__ import annotations

import csv
import io
import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

MAX_BATCH_INPUT_CHARS = 1_000_000
MAX_BATCH_INPUT_ROWS = 2_000
MAX_BATCH_ITEMS = 500
MAX_BATCH_TITLE_CHARS = 180

_URL_HEADERS = {"url", "sourceurl", "link", "网址", "链接"}
_TITLE_HEADERS = {"title", "displaytitle", "name", "标题", "名称"}


@dataclass(frozen=True)
class BatchInputItem:
    row: int
    source_url: str
    display_title: str = ""


@dataclass(frozen=True)
class BatchInputIssue:
    row: int
    code: str
    message: str


@dataclass(frozen=True)
class BatchInputResult:
    format: str
    items: tuple[BatchInputItem, ...]
    issues: tuple[BatchInputIssue, ...]

    @property
    def accepted_count(self) -> int:
        return len(self.items)

    @property
    def issue_count(self) -> int:
        return len(self.issues)


def _header_key(value: object) -> str:
    text = str(value or "").strip().lower()
    return "".join(character for character in text if character not in {"_", "-", " "})


def _clean_title(value: object) -> str:
    return " ".join(str(value or "").split()).strip()[:MAX_BATCH_TITLE_CHARS]


def _looks_like_safe_http_url(value: object) -> str | None:
    """Cheap local preflight only; final public-host validation happens later.

    Batch preview must not resolve hundreds of hostnames synchronously. Reject
    malformed URLs, credentials, localhost/local hostnames and explicit private
    IP literals here. `engine.job_from_payload()` still performs the authoritative
    DNS-aware public URL validation when an item is actually submitted.
    """
    candidate = str(value or "").strip()
    if not candidate:
        return None
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None

    host = parsed.hostname.strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or "%" in host:
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return None
    return candidate


def _first_nonempty_line(text: str) -> str:
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if line:
            return line
    return ""


def _detect_format(text: str) -> str:
    first = _first_nonempty_line(text)
    if not first:
        return "txt"
    try:
        cells = next(csv.reader([first]))
    except (csv.Error, StopIteration):
        return "txt"
    keys = {_header_key(cell) for cell in cells}
    return "csv" if keys & _URL_HEADERS else "txt"


def _issue(row: int, code: str, message: str) -> BatchInputIssue:
    # Deliberately never include the raw source URL. Signed URLs and query tokens
    # must not leak into diagnostics merely because an input row is invalid.
    return BatchInputIssue(row=max(0, int(row)), code=code, message=message)


def _parse_txt(text: str, *, max_items: int, max_rows: int) -> BatchInputResult:
    items: list[BatchInputItem] = []
    issues: list[BatchInputIssue] = []
    row_count = 0
    for row, raw in enumerate(text.splitlines(), start=1):
        row_count += 1
        if row_count > max_rows:
            issues.append(_issue(row, "ROW_LIMIT", f"批量输入最多处理 {max_rows} 行。"))
            break
        candidate = raw.strip().lstrip("\ufeff")
        if not candidate or candidate.startswith("#"):
            continue
        source_url = _looks_like_safe_http_url(candidate)
        if source_url is None:
            issues.append(_issue(row, "INVALID_URL", "这一行不是可提交的 HTTP(S) 公网链接。"))
            continue
        if len(items) >= max_items:
            issues.append(_issue(row, "ITEM_LIMIT", f"单批最多接受 {max_items} 个有效链接。"))
            break
        items.append(BatchInputItem(row=row, source_url=source_url))
    return BatchInputResult(format="txt", items=tuple(items), issues=tuple(issues))


def _find_header(fieldnames: list[str], accepted: set[str]) -> str | None:
    for field in fieldnames:
        if _header_key(field) in accepted:
            return field
    return None


def _parse_csv(text: str, *, max_items: int, max_rows: int) -> BatchInputResult:
    items: list[BatchInputItem] = []
    issues: list[BatchInputIssue] = []
    stream = io.StringIO(text.lstrip("\ufeff"), newline="")
    try:
        reader = csv.DictReader(stream)
        fieldnames = [str(field or "") for field in (reader.fieldnames or [])]
    except csv.Error:
        return BatchInputResult(
            format="csv",
            items=(),
            issues=(_issue(1, "INVALID_CSV", "CSV 表头无法解析。"),),
        )

    url_field = _find_header(fieldnames, _URL_HEADERS)
    if url_field is None:
        return BatchInputResult(
            format="csv",
            items=(),
            issues=(_issue(1, "MISSING_URL_COLUMN", "CSV 必须包含 url/sourceUrl/link/网址/链接 列。"),),
        )
    title_field = _find_header(fieldnames, _TITLE_HEADERS)

    try:
        for data_index, record in enumerate(reader, start=1):
            source_row = data_index + 1
            if data_index > max_rows:
                issues.append(_issue(source_row, "ROW_LIMIT", f"批量输入最多处理 {max_rows} 个数据行。"))
                break
            if not isinstance(record, dict):
                issues.append(_issue(source_row, "INVALID_CSV_ROW", "这一行 CSV 数据无法解析。"))
                continue
            raw_url = str(record.get(url_field) or "").strip()
            if not raw_url and not any(str(value or "").strip() for value in record.values()):
                continue
            source_url = _looks_like_safe_http_url(raw_url)
            if source_url is None:
                issues.append(_issue(source_row, "INVALID_URL", "这一行的 URL 不是可提交的 HTTP(S) 公网链接。"))
                continue
            if len(items) >= max_items:
                issues.append(_issue(source_row, "ITEM_LIMIT", f"单批最多接受 {max_items} 个有效链接。"))
                break
            title = _clean_title(record.get(title_field)) if title_field else ""
            items.append(BatchInputItem(row=source_row, source_url=source_url, display_title=title))
    except csv.Error:
        issues.append(_issue(max(2, reader.line_num), "INVALID_CSV", "CSV 数据中存在无法解析的行。"))

    return BatchInputResult(format="csv", items=tuple(items), issues=tuple(issues))


def parse_batch_input(
    text: object,
    *,
    format_hint: str = "auto",
    max_items: int = MAX_BATCH_ITEMS,
    max_rows: int = MAX_BATCH_INPUT_ROWS,
) -> BatchInputResult:
    raw = str(text or "")
    if len(raw) > MAX_BATCH_INPUT_CHARS:
        return BatchInputResult(
            format="txt" if format_hint == "txt" else "csv" if format_hint == "csv" else "auto",
            items=(),
            issues=(_issue(0, "INPUT_TOO_LARGE", f"批量输入不能超过 {MAX_BATCH_INPUT_CHARS} 个字符。"),),
        )

    hint = str(format_hint or "auto").strip().lower()
    if hint not in {"auto", "txt", "csv"}:
        raise ValueError("format_hint must be auto, txt or csv")
    item_limit = int(max_items)
    row_limit = int(max_rows)
    if item_limit <= 0 or row_limit <= 0:
        raise ValueError("max_items and max_rows must be greater than zero")

    resolved = _detect_format(raw) if hint == "auto" else hint
    return _parse_csv(raw, max_items=item_limit, max_rows=row_limit) if resolved == "csv" else _parse_txt(raw, max_items=item_limit, max_rows=row_limit)


def run_batch_input_self_test() -> None:
    plain = parse_batch_input(
        "# demo\nhttps://example.com/a\n\nhttps://example.com/a\nnot-a-url\n",
        format_hint="txt",
    )
    assert plain.format == "txt"
    assert [item.source_url for item in plain.items] == ["https://example.com/a", "https://example.com/a"]
    assert [issue.code for issue in plain.issues] == ["INVALID_URL"]

    csv_result = parse_batch_input(
        "sourceUrl,displayTitle\nhttps://example.com/1,  Demo   One  \nhttps://example.com/2,Two\n"
    )
    assert csv_result.format == "csv"
    assert [item.display_title for item in csv_result.items] == ["Demo One", "Two"]

    unsafe = parse_batch_input("http://127.0.0.1/private?token=secret-token\n", format_hint="txt")
    assert unsafe.accepted_count == 0
    assert unsafe.issues[0].code == "INVALID_URL"
    assert "secret-token" not in repr(unsafe.issues)

    limited = parse_batch_input(
        "https://example.com/1\nhttps://example.com/2\n",
        format_hint="txt",
        max_items=1,
    )
    assert limited.accepted_count == 1
    assert limited.issues[-1].code == "ITEM_LIMIT"
