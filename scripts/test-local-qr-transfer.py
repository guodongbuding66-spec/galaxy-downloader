from __future__ import annotations

import hashlib
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from qr_transfer import QRTransferSession, run_qr_transfer_self_test  # noqa: E402
from transfer_center import TransferError  # noqa: E402


def _request(url: str, *, method: str = "GET"):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, method=method, headers={"User-Agent": "GalaxyQRContract/1"})
    try:
        with opener.open(request, timeout=5) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def test_round_trip(root: Path) -> None:
    source = root / "测试 transfer file.bin"
    payload = (b"galaxy-qr-transfer\x00" * 4096) + b"done"
    source.write_bytes(payload)

    session = QRTransferSession(source, ttl_seconds=60).start()
    try:
        assert session.active is True
        assert session.url.startswith("http://")
        assert str(source) not in session.url
        assert source.as_posix() not in session.url
        public = session.public_payload()
        assert public["fileName"] == source.name
        assert public["sizeBytes"] == len(payload)
        assert public["served"] is False
        assert 1 <= public["ttlSeconds"] <= 60
        assert str(source.parent) not in str(public)

        png = session.qr_png_bytes()
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(png) > 100

        bad_url = session.url.rsplit("/", 1)[0] + "/wrong-token"
        code, headers, body = _request(bad_url)
        assert code == 404
        assert body == b"Not found"
        assert headers.get("Cache-Control") == "no-store"
        assert session.served is False

        code, headers, body = _request(session.url, method="HEAD")
        assert code == 200
        assert body == b""
        assert int(headers["Content-Length"]) == len(payload)
        assert "attachment" in headers.get("Content-Disposition", "")
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert session.served is False

        code, headers, body = _request(session.url)
        assert code == 200
        assert hashlib.sha256(body).digest() == hashlib.sha256(payload).digest()
        assert int(headers["Content-Length"]) == len(payload)
        for _ in range(50):
            if session.served:
                break
            time.sleep(0.02)
        assert session.served is True
        assert session.active is False
    finally:
        session.stop()


def test_method_and_input_bounds(root: Path) -> None:
    source = root / "file.txt"
    source.write_text("hello", encoding="utf-8")
    session = QRTransferSession(source, ttl_seconds=1).start()
    try:
        assert session.ttl_seconds == 60
        code, _, body = _request(session.url, method="POST")
        assert code == 405 and body == b"Method not allowed"
        assert session.served is False
    finally:
        session.stop()

    try:
        QRTransferSession(root / "missing.bin")
    except TransferError:
        pass
    else:
        raise AssertionError("missing QR source file was accepted")


def test_qr_requires_started_session(root: Path) -> None:
    source = root / "file.bin"
    source.write_bytes(b"x")
    session = QRTransferSession(source)
    try:
        session.qr_png_bytes()
    except TransferError as exc:
        assert "尚未启动" in str(exc)
    else:
        raise AssertionError("QR generated before session start")


def run_test() -> None:
    run_qr_transfer_self_test()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        test_round_trip(root)
        test_method_and_input_bounds(root)
        test_qr_requires_started_session(root)


if __name__ == "__main__":
    run_test()
    print("QR Transfer core tests passed")
