from __future__ import annotations

import argparse
import os
import signal
import threading
from contextlib import suppress
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from headless_media_api import HeadlessMediaApi, HeadlessMediaApiError
from headless_service import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    GalaxyHeadlessServer,
    HeadlessRequestHandler,
    HeadlessRuntime,
    HeadlessServiceError,
    _bounded_int,
    _download_root,
    _loopback_host,
    _safe_detail,
)


def _first_query_value(values: dict[str, list[str]], *names: str) -> str:
    for name in names:
        candidates = values.get(name)
        if candidates:
            return str(candidates[0])
    return ""


class GalaxyApiRequestHandler(HeadlessRequestHandler):
    @property
    def media_api(self) -> HeadlessMediaApi:
        return self.server.media_api  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        if not path.startswith("/v1/media"):
            super().do_GET()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            if path == "/v1/media/summary":
                self._json(200, {"ok": True, "summary": self.media_api.summary()})
                return
            if path == "/v1/media":
                values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=20)
                result = self.media_api.list_items(
                    query=_first_query_value(values, "q", "query"),
                    limit=_first_query_value(values, "limit") or 100,
                    offset=_first_query_value(values, "offset") or 0,
                    media_type=_first_query_value(values, "type", "mediaType"),
                )
                self._json(200, {"ok": True, **result})
                return
            self._json(404, {"ok": False, "error": "not found"})
        except (HeadlessMediaApiError, ValueError) as exc:
            self._json(400, {"ok": False, "error": _safe_detail(exc)})
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        if path != "/v1/media/sync":
            super().do_POST()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            result = self.media_api.sync()
            self._json(200, {"ok": True, **result})
        except HeadlessMediaApiError as exc:
            self._json(400, {"ok": False, "error": _safe_detail(exc)})
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})


class GalaxyApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address,
        runtime: HeadlessRuntime,
        auth_token: str,
        bound_host: str,
        media_api: HeadlessMediaApi,
    ) -> None:
        self.runtime = runtime
        self.auth_token = auth_token
        self.bound_host = bound_host
        self.media_api = media_api
        super().__init__(address, GalaxyApiRequestHandler)


def run_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    download_root: Path | None = None,
    auth_token: str = "",
    media_api: HeadlessMediaApi | None = None,
) -> int:
    clean_host = str(host or DEFAULT_HOST).strip()
    clean_port = _bounded_int(port, DEFAULT_PORT, 1, 65535)
    token = str(auth_token or "").strip()
    if not _loopback_host(clean_host) and len(token) < 24:
        raise HeadlessServiceError("a bearer token with at least 24 characters is required for non-loopback binding")
    root = Path(download_root or _download_root()).expanduser().resolve(strict=False)
    runtime = HeadlessRuntime(root)
    media = media_api or HeadlessMediaApi(root)
    server = GalaxyApiServer((clean_host, clean_port), runtime, token, clean_host, media)
    stopping = threading.Event()

    def stop_handler(_signum, _frame) -> None:
        if stopping.is_set():
            return
        stopping.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    for signal_name in ("SIGINT", "SIGTERM"):
        value = getattr(signal, signal_name, None)
        if value is not None:
            with suppress(OSError, RuntimeError, ValueError):
                signal.signal(value, stop_handler)
    try:
        print(f"Galaxy Headless API listening on {clean_host}:{clean_port}", flush=True)
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        runtime.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="galaxy-headless", description="Galaxy Local Engine headless API")
    parser.add_argument("--host", default=os.getenv("GALAXY_HEADLESS_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("GALAXY_HEADLESS_PORT", str(DEFAULT_PORT))))
    parser.add_argument("--download-dir", default=os.getenv("GALAXY_DOWNLOAD_DIR", ""))
    args = parser.parse_args(argv)
    token = os.getenv("GALAXY_HEADLESS_TOKEN", "")
    root = _download_root(args.download_dir)
    return run_server(host=args.host, port=args.port, download_root=root, auth_token=token)


if __name__ == "__main__":
    raise SystemExit(main())
