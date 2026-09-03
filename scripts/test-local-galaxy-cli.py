from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from galaxy_cli import (  # noqa: E402
    GalaxyApiClient,
    GalaxyApiError,
    GalaxyCliError,
    GalaxyTransportError,
    normalize_api_url,
    run_cli,
)

JOB_ID = "a" * 32
MEDIA_ID = "b" * 32
TOKEN = "cli-test-token-01234567890123456789"


class FakeApiHandler(BaseHTTPRequestHandler):
    records: list[dict] = []
    job_reads = 0

    def log_message(self, _format: str, *_args) -> None:
        return

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, body: dict | None = None) -> None:
        self.records.append(
            {
                "method": self.command,
                "path": self.path,
                "authorization": self.headers.get("Authorization") or "",
                "body": body or {},
            }
        )

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        self._record()
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://example.com/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/error":
            self._json(401, {"ok": False, "error": "token=abc secret=def"})
            return
        if path == "/v1/status":
            self._json(200, {"ok": True, "protocol": 2, "active": 0})
            return
        if path == f"/v1/jobs/{JOB_ID}":
            type(self).job_reads += 1
            state = "completed" if type(self).job_reads >= 2 else "running"
            self._json(200, {"ok": True, "job": {"id": JOB_ID, "state": state, "progress": 100 if state == "completed" else 50}})
            return
        if path == "/v1/jobs":
            self._json(200, {"ok": True, "jobs": [{"id": JOB_ID, "state": "completed"}] * 3})
            return
        if path == "/v1/media":
            self._json(200, {"ok": True, "items": [], "query": ""})
            return
        if path == "/v1/media/summary":
            self._json(200, {"ok": True, "summary": {"total": 1}})
            return
        if path == f"/v1/transcripts/{MEDIA_ID}":
            self._json(200, {"ok": True, "mediaId": MEDIA_ID, "segments": []})
            return
        if path == "/v1/transcripts/search":
            self._json(200, {"ok": True, "results": []})
            return
        if path == "/v1/subscriptions":
            self._json(200, {"ok": True, "subscriptions": [], "total": 0})
            return
        if path.startswith("/v1/subscriptions/"):
            self._json(200, {"ok": True, "subscription": {"id": "sub"}, "rules": {}, "counts": {}})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        body = self._body()
        path = urlsplit(self.path).path
        self._record(body)
        if path == "/v1/parse":
            self._json(200, {"ok": True, "result": {"title": "Demo", "sourceUrl": body.get("sourceUrl")}})
            return
        if path == "/v1/download":
            self._json(202, {"ok": True, "job": {"id": JOB_ID, "state": "queued"}})
            return
        self._json(200, {"ok": True, "path": path, "payload": body})


def run() -> None:
    for value in (
        "http://example.com:17837",
        "ftp://127.0.0.1:17837",
        "http://user:pass@127.0.0.1:17837",
        "http://127.0.0.1:17837/api",
    ):
        try:
            normalize_api_url(value)
        except GalaxyCliError:
            pass
        else:
            raise AssertionError(f"unsafe CLI API URL was accepted: {value}")
    try:
        normalize_api_url("https://api.example.com")
    except GalaxyCliError:
        pass
    else:
        raise AssertionError("remote HTTPS endpoint without bearer token was accepted")
    assert normalize_api_url("https://api.example.com", token=TOKEN) == "https://api.example.com"

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        client = GalaxyApiClient(base, token=TOKEN, timeout_seconds=2)
        status = client.get("/v1/status")
        assert status["protocol"] == 2
        assert FakeApiHandler.records[-1]["authorization"] == f"Bearer {TOKEN}"

        source_url = "https://example.com/demo"
        parsed = client.post("/v1/parse", payload={"sourceUrl": source_url})
        assert parsed["result"]["title"] == "Demo"
        assert FakeApiHandler.records[-1]["body"]["sourceUrl"] == source_url

        try:
            client.get("/redirect")
        except GalaxyTransportError:
            pass
        else:
            raise AssertionError("CLI followed an API redirect")

        try:
            client.get("/error")
        except GalaxyApiError as exc:
            assert exc.status == 401
            assert "abc" not in exc.detail and "def" not in exc.detail
            assert "REDACTED" in exc.detail
        else:
            raise AssertionError("CLI did not surface API error")

        FakeApiHandler.job_reads = 0
        waited = client.wait_for_job(JOB_ID, poll_seconds=0.2, timeout_seconds=3)
        assert waited["job"]["state"] == "completed" and FakeApiHandler.job_reads == 2

        args, result = run_cli(
            ["--api-url", base, "parse", "https://example.com/from-cli"],
            environ={"GALAXY_HEADLESS_TOKEN": TOKEN},
        )
        assert args.command == "parse" and result["result"]["title"] == "Demo"

        _, queued = run_cli(
            [
                "--api-url",
                base,
                "download",
                "https://example.com/video",
                "--subtitle",
                "--subtitle-language",
                "en,zh-CN",
                "--rate-limit-mbps",
                "8",
            ],
            environ={"GALAXY_HEADLESS_TOKEN": TOKEN},
        )
        assert queued["job"]["id"] == JOB_ID
        download_record = next(record for record in reversed(FakeApiHandler.records) if record["path"] == "/v1/download")
        assert download_record["body"]["subtitleLanguages"] == ["en", "zh-CN"]
        assert download_record["body"]["rateLimitMbps"] == 8

        _, media = run_cli(
            ["--api-url", base, "media", "--query", "demo", "--type", "video", "--limit", "25"],
            environ={"GALAXY_HEADLESS_TOKEN": TOKEN},
        )
        assert media["ok"] is True
        assert "q=demo" in FakeApiHandler.records[-1]["path"] and "type=video" in FakeApiHandler.records[-1]["path"]

        _, transcript = run_cli(
            ["--api-url", base, "transcript", MEDIA_ID, "--limit", "10"],
            environ={"GALAXY_HEADLESS_TOKEN": TOKEN},
        )
        assert transcript["mediaId"] == MEDIA_ID

        _, rules = run_cli(
            [
                "--api-url",
                base,
                "subscription-set-rules",
                "sub-1",
                "--include",
                "Galaxy,Episode",
                "--tag",
                "tech",
                "--manual-review",
            ],
            environ={"GALAXY_HEADLESS_TOKEN": TOKEN},
        )
        assert rules["ok"] is True
        rule_record = FakeApiHandler.records[-1]
        assert rule_record["path"] == "/v1/subscriptions/sub-1/rules"
        assert rule_record["body"]["includeKeywords"] == ["Galaxy", "Episode"]
        assert rule_record["body"]["manualReview"] is True

        try:
            run_cli(
                ["--api-url", base, "subscription-update", "sub-1"],
                environ={"GALAXY_HEADLESS_TOKEN": TOKEN},
            )
        except GalaxyCliError:
            pass
        else:
            raise AssertionError("empty subscription update was accepted")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    run()
    print("Galaxy CLI 2.0 self-test passed")
