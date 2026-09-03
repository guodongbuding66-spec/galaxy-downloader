from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from runtime_storage import state_dir as runtime_state_dir

API_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17837
MAX_REQUEST_BYTES = 64 * 1024
TOKEN_FILENAME = "api-token.txt"


def _engine_module():
    import engine

    return engine


def api_token_path(engine_module) -> Path:
    root = runtime_state_dir(engine_module)
    root.mkdir(parents=True, exist_ok=True)
    return root / TOKEN_FILENAME


def load_or_create_api_token(engine_module) -> str:
    path = api_token_path(engine_module)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if len(value) >= 32 and len(value) <= 256 and all(ch.isalnum() or ch in "-_" for ch in value):
        return value
    value = secrets.token_urlsafe(36)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(value + "\n", encoding="utf-8")
    try:
        if os.name != "nt":
            temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)
    return value


def _authorized(header: object, token: str) -> bool:
    raw = str(header or "")
    prefix = "Bearer "
    if not raw.startswith(prefix):
        return False
    candidate = raw[len(prefix) :].strip()
    return bool(candidate) and hmac.compare_digest(candidate, token)


def _safe_limit(value: object, default: int = 100, maximum: int = 500) -> int:
    try:
        number = int(str(value or default))
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, maximum))


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _download(engine_module, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from bridge import post_job_to_running_engine

    try:
        job = engine_module.job_from_payload(payload)
    except (TypeError, ValueError):
        return 400, {"ok": False, "code": "BAD_REQUEST"}
    accepted = post_job_to_running_engine(engine_module.job_to_payload(job), timeout=1.5)
    return (
        (202, {"ok": True, "code": "ACCEPTED"})
        if accepted
        else (503, {"ok": False, "code": "ENGINE_UNAVAILABLE"})
    )


def build_handler(engine_module, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "GalaxyLocalAPI/1"

        def log_message(self, _format: str, *_args) -> None:
            return

        def _send(self, status: int, payload: object) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _require_auth(self) -> bool:
            if _authorized(self.headers.get("Authorization"), token):
                return True
            self._send(401, {"ok": False, "code": "UNAUTHORIZED"})
            return False

        def _read_json(self) -> dict[str, Any] | None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length <= 0 or length > MAX_REQUEST_BYTES:
                return None
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return None
            return payload if isinstance(payload, dict) else None

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send(
                    200,
                    {
                        "ok": True,
                        "service": "galaxy-local-api",
                        "apiVersion": API_VERSION,
                        "engineVersion": getattr(engine_module, "VERSION", "unknown"),
                    },
                )
                return
            if not self._require_auth():
                return
            query = parse_qs(parsed.query)
            if parsed.path == "/api/v1/history":
                from job_history import load_history

                limit = _safe_limit(query.get("limit", [100])[0])
                self._send(200, {"ok": True, "items": load_history(engine_module)[:limit]})
                return
            if parsed.path == "/api/v1/library":
                from media_library import list_media_items, search_media_items

                limit = _safe_limit(query.get("limit", [100])[0])
                term = str(query.get("q", [""])[0]).strip()
                media_type = str(query.get("type", [""])[0]).strip() or None
                rows = (
                    search_media_items(engine_module, term, limit=limit)
                    if term
                    else list_media_items(engine_module, limit=limit, media_type=media_type)
                )
                self._send(200, {"ok": True, "items": rows})
                return
            if parsed.path == "/api/v1/subscriptions":
                from subscriptions import load_subscriptions

                self._send(200, {"ok": True, "items": load_subscriptions(engine_module)})
                return
            self._send(404, {"ok": False, "code": "NOT_FOUND"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._require_auth():
                return
            parsed = urlparse(self.path)
            if parsed.path != "/api/v1/download":
                self._send(404, {"ok": False, "code": "NOT_FOUND"})
                return
            payload = self._read_json()
            if payload is None:
                self._send(400, {"ok": False, "code": "BAD_REQUEST"})
                return
            status, result = _download(engine_module, payload)
            self._send(status, result)

    return Handler


def run_server(*, host: str, port: int, allow_remote: bool = False) -> None:
    engine = _engine_module()
    selected_host = str(host or DEFAULT_HOST).strip()
    if not allow_remote and selected_host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("remote API binding requires --allow-remote")
    token = load_or_create_api_token(engine)
    server = ThreadingHTTPServer((selected_host, int(port)), build_handler(engine, token))
    print(f"Galaxy Local API listening on {selected_host}:{int(port)}")
    print(f"Bearer token file: {api_token_path(engine)}")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Galaxy Local Engine authenticated API")
    parser.add_argument("--host", default=os.getenv("GALAXY_API_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("GALAXY_API_PORT", str(DEFAULT_PORT))))
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        default=os.getenv("GALAXY_API_ALLOW_REMOTE", "0") == "1",
        help="allow binding to a non-loopback host; Bearer authentication remains mandatory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_server(host=args.host, port=args.port, allow_remote=args.allow_remote)
    return 0


def run_api_server_self_test() -> None:
    import tempfile

    assert _authorized("Bearer abc", "abc") is True
    assert _authorized("Bearer abc", "abcd") is False
    assert _authorized("Basic abc", "abc") is False
    assert _safe_limit("9999") == 500
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        class Engine:
            VERSION = "test"

            @staticmethod
            def state_dir() -> Path:
                target = root / "state"
                target.mkdir(parents=True, exist_ok=True)
                return target

            @staticmethod
            def app_dir() -> Path:
                return root

        first = load_or_create_api_token(Engine)
        second = load_or_create_api_token(Engine)
        assert first == second
        assert len(first) >= 32


if __name__ == "__main__":
    raise SystemExit(main())
