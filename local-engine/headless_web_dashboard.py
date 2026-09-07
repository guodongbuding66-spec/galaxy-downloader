from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit


_DASHBOARD_ROOT = Path(__file__).with_name("web-dashboard")
_DASHBOARD_ASSETS = {
    "/dashboard/": ("index.html", "text/html; charset=utf-8"),
    "/dashboard/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/dashboard/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/dashboard/ai-subscriptions.js": ("ai-subscriptions.js", "text/javascript; charset=utf-8"),
    "/dashboard/ai-subscriptions.css": ("ai-subscriptions.css", "text/css; charset=utf-8"),
    "/dashboard/plugins.js": ("plugins.js", "text/javascript; charset=utf-8"),
    "/dashboard/plugins.css": ("plugins.css", "text/css; charset=utf-8"),
    "/dashboard/settings.js": ("settings.js", "text/javascript; charset=utf-8"),
    "/dashboard/settings.css": ("settings.css", "text/css; charset=utf-8"),
    "/dashboard/learning.js": ("learning.js", "text/javascript; charset=utf-8"),
    "/dashboard/learning.css": ("learning.css", "text/css; charset=utf-8"),
    "/dashboard/learning-attachments.js": ("learning-attachments.js", "text/javascript; charset=utf-8"),
    "/dashboard/learning-attachments.css": ("learning-attachments.css", "text/css; charset=utf-8"),
    "/dashboard/learning-navigation.js": ("learning-navigation.js", "text/javascript; charset=utf-8"),
    "/dashboard/learning-navigation.css": ("learning-navigation.css", "text/css; charset=utf-8"),
    "/dashboard/learning-player.js": ("learning-player.js", "text/javascript; charset=utf-8"),
    "/dashboard/learning-player.css": ("learning-player.css", "text/css; charset=utf-8"),
    "/dashboard/learning-notes.js": ("learning-notes.js", "text/javascript; charset=utf-8"),
    "/dashboard/learning-notes.css": ("learning-notes.css", "text/css; charset=utf-8"),
    "/dashboard/learning-search.js": ("learning-search.js", "text/javascript; charset=utf-8"),
    "/dashboard/learning-search.css": ("learning-search.css", "text/css; charset=utf-8"),
}
_LEARNING_STYLE_TAG = '<link rel="stylesheet" href="/dashboard/learning.css">'
_LEARNING_SCRIPT_TAG = '<script src="/dashboard/learning.js" defer></script>'
_ATTACHMENT_STYLE_TAG = '<link rel="stylesheet" href="/dashboard/learning-attachments.css">'
_ATTACHMENT_SCRIPT_TAG = '<script src="/dashboard/learning-attachments.js" defer></script>'
_NAVIGATION_STYLE_TAG = '<link rel="stylesheet" href="/dashboard/learning-navigation.css">'
_NAVIGATION_SCRIPT_TAG = '<script src="/dashboard/learning-navigation.js" defer></script>'
_PLAYER_STYLE_TAG = '<link rel="stylesheet" href="/dashboard/learning-player.css">'
_PLAYER_SCRIPT_TAG = '<script src="/dashboard/learning-player.js" defer></script>'
_NOTES_STYLE_TAG = '<link rel="stylesheet" href="/dashboard/learning-notes.css">'
_NOTES_SCRIPT_TAG = '<script src="/dashboard/learning-notes.js" defer></script>'
_SEARCH_STYLE_TAG = '<link rel="stylesheet" href="/dashboard/learning-search.css">'
_SEARCH_SCRIPT_TAG = '<script src="/dashboard/learning-search.js" defer></script>'


def _with_learning_assets(body: bytes, file_name: str) -> bytes:
    if file_name != "index.html":
        return body
    try:
        html = body.decode("utf-8")
    except UnicodeDecodeError:
        return body
    for style_tag in (_LEARNING_STYLE_TAG, _ATTACHMENT_STYLE_TAG, _NAVIGATION_STYLE_TAG, _PLAYER_STYLE_TAG, _NOTES_STYLE_TAG, _SEARCH_STYLE_TAG):
        if style_tag not in html:
            html = html.replace("</head>", f"  {style_tag}\n</head>", 1)
    for script_tag in (_LEARNING_SCRIPT_TAG, _ATTACHMENT_SCRIPT_TAG, _NAVIGATION_SCRIPT_TAG, _PLAYER_SCRIPT_TAG, _NOTES_SCRIPT_TAG, _SEARCH_SCRIPT_TAG):
        if script_tag not in html:
            html = html.replace("</body>", f"  {script_tag}\n</body>", 1)
    return html.encode("utf-8")


class HeadlessWebDashboardMixin:
    """Serve the NAS/Home Server dashboard without widening API trust."""

    def _browser_origin_allowed(self) -> bool:
        origin = str(self.headers.get("Origin") or "").strip()
        if not origin:
            return super()._browser_origin_allowed()
        if not self._valid_host_header():
            return False

        raw_host = str(self.headers.get("Host") or "").strip()
        if not raw_host:
            return False
        try:
            parsed = urlsplit(origin)
            _ = parsed.port
        except ValueError:
            return False
        return (
            parsed.scheme.lower() == "http"
            and parsed.netloc.lower() == raw_host.lower()
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
        )

    def _dashboard_redirect(self) -> None:
        self.send_response(302)
        self.send_header("Location", "/dashboard/")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _dashboard_asset(self, path: str) -> bool:
        asset = _DASHBOARD_ASSETS.get(path)
        if asset is None:
            return False
        file_name, content_type = asset
        try:
            body = _with_learning_assets((_DASHBOARD_ROOT / file_name).read_bytes(), file_name)
        except OSError:
            self._json(503, {"ok": False, "error": "web dashboard asset is unavailable"})
            return True

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path in {"/", "/dashboard"}:
            self._dashboard_redirect()
            return
        if self._dashboard_asset(path):
            return
        super().do_GET()
