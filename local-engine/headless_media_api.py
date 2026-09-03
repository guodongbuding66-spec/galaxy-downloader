from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from media_library import (
    list_media_items,
    media_library_summary,
    search_media_items,
    sync_media_library,
)
from platform_paths import resolve_platform_paths

_ALLOWED_MEDIA_TYPES = frozenset({"video", "audio", "image", "other"})


class HeadlessMediaApiError(RuntimeError):
    pass


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def _safe_query(value: object) -> str:
    return " ".join(str(value or "").split()).strip()[:160]


def _safe_media_type(value: object) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw not in _ALLOWED_MEDIA_TYPES:
        raise HeadlessMediaApiError("media type must be video, audio, image, or other")
    return raw


@dataclass(frozen=True)
class HeadlessMediaContext:
    program_dir: Path
    state_path: Path
    downloads_path: Path

    def app_dir(self) -> Path:
        return self.program_dir

    def state_dir(self) -> Path:
        self.state_path.mkdir(parents=True, exist_ok=True)
        return self.state_path

    def default_download_dir(self) -> Path:
        self.downloads_path.mkdir(parents=True, exist_ok=True)
        return self.downloads_path


def build_headless_media_context(
    download_root: Path,
    *,
    program_dir: Path | None = None,
    state_dir: Path | None = None,
) -> HeadlessMediaContext:
    program = Path(program_dir or Path(__file__).resolve().parent).expanduser().resolve(strict=False)
    downloads = Path(download_root).expanduser().resolve(strict=False)
    if downloads.exists() and downloads.is_symlink():
        raise HeadlessMediaApiError("media download root cannot be a symbolic link")
    paths = resolve_platform_paths(program_dir=program)
    state = Path(state_dir or paths.state_dir).expanduser().resolve(strict=False)
    if state.exists() and state.is_symlink():
        raise HeadlessMediaApiError("media state directory cannot be a symbolic link")
    state.mkdir(parents=True, exist_ok=True)
    downloads.mkdir(parents=True, exist_ok=True)
    return HeadlessMediaContext(program, state, downloads)


class HeadlessMediaApi:
    def __init__(
        self,
        download_root: Path,
        *,
        context: HeadlessMediaContext | None = None,
        program_dir: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.context = context or build_headless_media_context(
            download_root,
            program_dir=program_dir,
            state_dir=state_dir,
        )

    def summary(self) -> dict[str, int]:
        return media_library_summary(self.context).public_payload()

    def list_items(
        self,
        *,
        query: object = "",
        limit: object = 100,
        offset: object = 0,
        media_type: object = "",
    ) -> dict[str, Any]:
        safe_limit = _bounded_int(limit, 100, 1, 100)
        safe_offset = _bounded_int(offset, 0, 0, 10_000)
        safe_type = _safe_media_type(media_type)
        text = _safe_query(query)

        if text:
            # Search has an intentional 200-row ceiling. Fetch only the bounded
            # window needed for pagination, then apply media-type filtering.
            fetch_limit = min(200, safe_limit + min(safe_offset, 199))
            rows = search_media_items(self.context, text, limit=fetch_limit)
            if safe_type is not None:
                rows = [item for item in rows if item.get("mediaType") == safe_type]
            items = rows[safe_offset : safe_offset + safe_limit]
        else:
            items = list_media_items(
                self.context,
                limit=safe_limit,
                offset=safe_offset,
                media_type=safe_type,
            )

        return {
            "items": items,
            "limit": safe_limit,
            "offset": safe_offset,
            "query": text,
            "mediaType": safe_type or "",
        }

    def sync(self) -> dict[str, Any]:
        accepted = sync_media_library(self.context)
        return {
            "accepted": accepted,
            "summary": self.summary(),
        }


def run_headless_media_api_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        downloads = root / "downloads"
        state = root / "state"
        downloads.mkdir()
        state.mkdir()
        media = downloads / "Demo.mp4"
        media.write_bytes(b"demo")
        context = HeadlessMediaContext(root / "program", state, downloads)
        api = HeadlessMediaApi(downloads, context=context)

        history = [
            {
                "state": "completed",
                "filePath": str(media),
                "fileName": media.name,
                "label": "Demo",
                "durationSeconds": 10,
                "sourceUrl": "https://example.com/watch?v=demo",
                "finishedAt": "2026-09-03T00:00:00Z",
            }
        ]
        assert sync_media_library(context, history) == 1
        summary = api.summary()
        assert summary["total"] == 1 and summary["video"] == 1
        listed = api.list_items(limit=10)
        assert listed["items"][0]["title"] == "Demo"
        assert "filePath" not in listed["items"][0]
        searched = api.list_items(query="Demo", media_type="video")
        assert len(searched["items"]) == 1

        try:
            api.list_items(media_type="document")
        except HeadlessMediaApiError:
            pass
        else:
            raise AssertionError("unsupported media type was accepted")
