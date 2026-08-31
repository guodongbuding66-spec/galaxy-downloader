from __future__ import annotations

import bridge
from web_document import parse_web_document, should_try_web_document

_original_media_parse = bridge.parse_with_bundled_ytdlp


def _hybrid_parse(source_url: str, browser: str = "none"):
    """Prefer rich page metadata, then preserve the existing yt-dlp path.

    The browser calls /parse once anonymously and only retries with browser
    cookies after AUTH_REQUIRED. Returning the document parser's auth signal
    here therefore reuses the bridge's existing explicit-cookie fallback flow.
    """
    if should_try_web_document(source_url):
        document = parse_web_document(source_url, browser)
        if document.get("success"):
            return document
        if document.get("code") == "AUTH_REQUIRED":
            return document

    return _original_media_parse(source_url, browser)


# LocalBridge resolves this function from the bridge module at request time, so
# assigning it before engine.main() starts the HTTP server is sufficient and
# avoids duplicating the stable bridge implementation.
bridge.parse_with_bundled_ytdlp = _hybrid_parse

from engine import main  # noqa: E402  import after bridge policy installation


if __name__ == "__main__":
    raise SystemExit(main())
