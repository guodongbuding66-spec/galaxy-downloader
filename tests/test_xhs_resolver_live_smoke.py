from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "xhs-resolver-live-smoke.py"
TOKEN = "integration-test-token"
SOURCE_URL = "https://www.xiaohongshu.com/explore/integration-test"


class ResolverFixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A003, ANN001
        return

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if self.path != "/xhs/detail":
            self._json(404, {"message": "not found"})
            return

        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._json(401, {"message": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if payload != {"url": SOURCE_URL, "download": False}:
            self._json(400, {"message": "unexpected request"})
            return

        port = self.server.server_address[1]
        media_url = f"http://127.0.0.1:{port}/media/video.mp4"

        schema = self.headers.get("X-Test-Schema", "structured")
        if schema == "legacy":
            detail = {
                "作品ID": "integration-test",
                "作品标题": "Legacy fixture",
                "作品类型": "视频",
                "作者昵称": "Fixture author",
                "下载地址": [media_url],
                "动图地址": [None],
            }
        elif schema == "evil":
            detail = {
                "作品ID": "integration-test",
                "作品标题": "Blocked fixture",
                "作品类型": "视频",
                "下载地址": ["https://evil.example.invalid/video.mp4"],
            }
        else:
            detail = {
                "作品ID": "integration-test",
                "作品标题": "Structured fixture",
                "作品类型": "视频",
                "作者": {"作者昵称": "Fixture author"},
                "媒体": [
                    {
                        "序号": 1,
                        "类型": "视频",
                        "地址": media_url,
                        "扩展名": "mp4",
                    }
                ],
            }

        self._json(200, {"message": "ok", "data": detail})

    def do_GET(self):  # noqa: N802
        if self.path != "/media/video.mp4":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if self.headers.get("Range") != "bytes=0-1023":
            self.send_response(416)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.headers.get("Referer") != SOURCE_URL:
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        body = b"fixture-video-bytes"
        self.send_response(206)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes 0-{len(body) - 1}/{len(body)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class SchemaHeaderProxyHandler(ResolverFixtureHandler):
    schema = "structured"

    def do_POST(self):  # noqa: N802
        self.headers["X-Test-Schema"] = self.schema
        super().do_POST()


class XhsResolverLiveSmokeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), SchemaHeaderProxyHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def run_smoke(self, schema: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        SchemaHeaderProxyHandler.schema = schema
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "report.json"
            env = os.environ.copy()
            env.update(
                {
                    "XHS_RESOLVER_URL": self.base_url,
                    "XHS_RESOLVER_TOKEN": TOKEN,
                    "XHS_SMOKE_URL": SOURCE_URL,
                    "XHS_MEDIA_HOST_SUFFIXES": "127.0.0.1",
                    "XHS_SMOKE_FETCH_MEDIA": "1",
                    "XHS_SMOKE_TIMEOUT": "5",
                    "XHS_SMOKE_OUTPUT": str(report_path),
                }
            )
            result = subprocess.run(
                [sys.executable, str(SMOKE_SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            return result, report

    def test_structured_schema_and_range_probe(self) -> None:
        result, report = self.run_smoke("structured")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["schema"], "structured-media")
        self.assertEqual(report["mediaCount"], 1)
        self.assertEqual(report["mediaHosts"], ["127.0.0.1"])
        self.assertEqual(report["mediaProbe"]["status"], 206)
        self.assertGreater(report["mediaProbe"]["bytesRead"], 0)
        self.assertEqual(report["mediaProbe"]["contentType"], "video/mp4")

    def test_legacy_schema_and_range_probe(self) -> None:
        result, report = self.run_smoke("legacy")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["schema"], "legacy-download-address")
        self.assertEqual(report["workType"], "视频")
        self.assertEqual(report["mediaProbe"]["status"], 206)

    def test_untrusted_media_host_is_rejected(self) -> None:
        result, report = self.run_smoke("evil")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("outside XHS_MEDIA_HOST_SUFFIXES", report["error"])
        self.assertIsNone(report["mediaProbe"])


if __name__ == "__main__":
    unittest.main()
