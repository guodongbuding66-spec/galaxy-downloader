from __future__ import annotations

import bridge
from document_policy import install_document_policy, parse_web_document, should_try_web_document
from dynamic_document import parse_dynamic_web_document

install_document_policy()
_original_media_parse = bridge.parse_with_bundled_ytdlp


def _hybrid_parse(source_url: str, browser: str = "none"):
    """Prefer rich document parsing, then dynamic CDP, then yt-dlp.

    Static HTML remains the cheap first choice. When modern commerce/social pages
    return only a JS shell, the local engine renders the page with Edge/Chrome
    and feeds the resulting DOM back through the same document normalizer.
    """
    if should_try_web_document(source_url):
        document = parse_web_document(source_url, browser)
        if document.get("success"):
            return document

        static_auth_required = document.get("code") == "AUTH_REQUIRED"
        dynamic = parse_dynamic_web_document(source_url, browser)
        if dynamic.get("success"):
            return dynamic
        if dynamic.get("code") == "BROWSER_COOKIE_UNAVAILABLE":
            return dynamic

        # Anonymous 401/403 must survive the dynamic attempt so the browser-side
        # bridge knows to retry explicitly with a logged-in browser profile.
        if static_auth_required and browser == "none":
            return document

    return _original_media_parse(source_url, browser)


# LocalBridge resolves this function from the bridge module at request time, so
# assigning it before engine.main() starts the HTTP server is sufficient and
# avoids duplicating the stable bridge implementation.
bridge.parse_with_bundled_ytdlp = _hybrid_parse

from engine import main  # noqa: E402  import after bridge policy installation


if __name__ == "__main__":
    raise SystemExit(main())
