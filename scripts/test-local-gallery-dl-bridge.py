from __future__ import annotations

import http.client
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import bridge as base_bridge  # noqa: E402
from gallery_dl_bridge import (  # noqa: E402
    GALLERY_DL_BRIDGE_PROTOCOL_VERSION,
    GalleryDlLocalBridge,
)


class Owner:
    def __init__(self) -> None:
        self.running = True
        self.gallery_calls: list[tuple[str, int]] = []
        self.pause_calls = 0

    def after(self, _delay: int, callback) -> None:
        callback()

    def status(self) -> dict[str, Any]:
        return {
            "version": "test",
            "state": "downloading" if self.running else "ready",
            "busy": self.running,
            "canPause": self.running,
            "activeJobId": "active" if self.running else None,
            "resumeJobs": [],
        }

    def pause_active_job(self) -> bool:
        self.pause_calls += 1
        self.running = False
        return True

    def submit_gallery_dl_task(self, source_url: str, *, max_files: int = 500) -> str:
        self.gallery_calls.append((source_url, max_files))
        return "gdl-fedcba9876543210"


def request(
    port: int,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    origin: str | None = None,
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers: dict[str, str] = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    if origin:
        headers["Origin"] = origin
    connection = http.client.HTTPConnection(base_bridge.BRIDGE_HOST, port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
        assert isinstance(parsed, dict)
        return response.status, parsed
    finally:
        connection.close()


def main() -> int:
    owner = Owner()
    normal_calls: list[dict[str, Any]] = []

    def submit_normal(payload: dict[str, Any]):
        normal_calls.append(dict(payload))
        return True, "normal accepted"

    local_bridge = GalleryDlLocalBridge(
        status_provider=owner.status,
        submit_job=submit_normal,
        cancel_job=lambda: None,
        open_folder=lambda: None,
    )

    original_port = base_bridge.BRIDGE_PORT
    base_bridge.BRIDGE_PORT = 0
    try:
        local_bridge.start()
        assert local_bridge._server is not None
        port = int(local_bridge._server.server_address[1])

        status_code, status = request(port, "GET", "/status")
        assert status_code == 200
        assert status["bridgeProtocol"] == GALLERY_DL_BRIDGE_PROTOCOL_VERSION
        assert status["galleryDlBridgeReady"] is True
        assert status["galleryDlMaxFiles"] == 500
        assert status["batchDownloadReady"] is False

        status_code, accepted = request(
            port,
            "POST",
            "/gallery-dl/download",
            {"sourceUrl": "https://1.1.1.1/gallery", "maxFiles": 17},
        )
        assert status_code == 202
        assert accepted["ok"] is True
        assert accepted["accepted"] is True
        assert accepted["code"] == "GALLERY_DL_ACCEPTED"
        assert accepted["taskId"] == "gdl-fedcba9876543210"
        assert owner.gallery_calls == [("https://1.1.1.1/gallery", 17)]

        status_code, rejected = request(
            port,
            "POST",
            "/gallery-dl/download",
            {"sourceUrl": "https://1.1.1.1/gallery", "headers": {"Cookie": "secret"}},
        )
        assert status_code == 400
        assert rejected["code"] == "BAD_REQUEST"
        assert len(owner.gallery_calls) == 1

        status_code, private = request(
            port,
            "POST",
            "/gallery-dl/download",
            {"sourceUrl": "http://127.0.0.1/private", "maxFiles": 2},
        )
        assert status_code == 400
        assert private["code"] == "BAD_SOURCE_URL"
        assert len(owner.gallery_calls) == 1

        status_code, forbidden = request(
            port,
            "POST",
            "/gallery-dl/download",
            {"sourceUrl": "https://1.1.1.1/gallery", "maxFiles": 2},
            origin="https://evil.example",
        )
        assert status_code == 403
        assert forbidden["code"] == "ORIGIN_NOT_ALLOWED"
        assert len(owner.gallery_calls) == 1

        status_code, normal = request(
            port,
            "POST",
            "/download",
            {"sourceUrl": "https://example.com/video"},
        )
        assert status_code == 202
        assert normal["accepted"] is True
        assert normal_calls == [{"sourceUrl": "https://example.com/video"}]

        status_code, paused = request(port, "POST", "/pause", {})
        assert status_code == 202
        assert paused["code"] == "PAUSE_REQUESTED"
        assert owner.pause_calls == 1

        status_code, bad_queue = request(port, "POST", "/queue/cancel", {"jobId": "!"})
        assert status_code == 400
        assert bad_queue["code"] == "BAD_REQUEST"

        status_code, missing = request(port, "POST", "/gallery-dl/unknown", {})
        assert status_code == 404
        assert missing["code"] == "NOT_FOUND"
    finally:
        local_bridge.stop()
        base_bridge.BRIDGE_PORT = original_port

    print("local gallery-dl bridge live regression OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
