from __future__ import annotations

import bridge
import web_document
from document_policy import install_document_policy, parse_web_document, should_try_web_document
from dynamic_document import parse_dynamic_web_document
from url_policy import is_public_http_url, validated_public_http_url

# Static document redirects and CDP request interception resolve this helper from
# the shared web_document module at request time. Install the fail-closed public
# URL boundary before either parser begins serving requests.
web_document._safe_http_url = is_public_http_url
install_document_policy()
_original_media_parse = bridge.parse_with_bundled_ytdlp


def _bad_source_url() -> dict[str, object]:
    return {
        "success": False,
        "code": "BAD_REQUEST",
        "status": 400,
        "error": "仅允许解析公网 HTTP(S) 链接，localhost、私网、保留地址和带凭据的 URL 已被阻止。",
    }


def _hybrid_parse(source_url: str, browser: str = "none"):
    """Prefer rich document parsing, then dynamic CDP, then yt-dlp.

    Static HTML remains the cheap first choice. When modern commerce/social pages
    return only a JS shell, the local engine renders the page with Edge/Chrome
    and feeds the resulting DOM back through the same document normalizer.
    """
    if not is_public_http_url(source_url):
        return _bad_source_url()

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
bridge._valid_source_url = is_public_http_url
bridge.parse_with_bundled_ytdlp = _hybrid_parse

# parse_job() and job_from_payload() resolve this global when a protocol/HTTP
# download request is received. Patching it once at process start keeps parse,
# bridge downloads, and galaxy-downloader:// launches on the same public-URL
# boundary without duplicating the engine's stable job normalization logic.
import engine  # noqa: E402  import after bridge/document policy installation

engine._validated_source_url = validated_public_http_url
main = engine.main


if __name__ == "__main__":
    raise SystemExit(main())
