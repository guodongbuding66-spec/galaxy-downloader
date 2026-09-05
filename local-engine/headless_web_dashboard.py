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
}


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
            body = (_DASHBOARD_ROOT / file_name).read_bytes()
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
