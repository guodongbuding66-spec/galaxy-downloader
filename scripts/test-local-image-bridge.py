from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

# image_bridge only needs bridge.allowed_origins. Stub the large media bridge so
# this contract test stays lightweight and does not require yt-dlp imports.
fake_bridge = types.ModuleType("bridge")
fake_bridge.allowed_origins = lambda: {"https://galaxy.example.test"}
sys.modules["bridge"] = fake_bridge

import image_bridge  # noqa: E402


class LocalImageBridgeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        image_bridge.IMAGE_BRIDGE_PORT = 0
        cls.bridge = image_bridge.ImageBridge("0.7.0")
        if not cls.bridge.start() or cls.bridge._server is None:
            raise RuntimeError("Could not start local image bridge test server")
        cls.port = int(cls.bridge._server.server_address[1])
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.bridge.stop()

    def request_json(self, path: str, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base + path,
            data=body,
            method="GET" if payload is None else "POST",
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            response = urlopen(request, timeout=3)
            return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_status_advertises_image_download_capability(self):
        status, payload = self.request_json("/status")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "0.7.0")
        self.assertTrue(payload["imageDownloads"])

    def test_empty_image_job_is_bad_request_not_busy(self):
        status, payload = self.request_json("/download-images", {})
        self.assertEqual(status, 400)
        self.assertFalse(payload["accepted"])
        self.assertIn("At least one image URL", payload["message"])

    def test_oversized_image_list_is_bad_request_not_busy(self):
        images = [f"https://example.com/{index}.jpg" for index in range(image_bridge.MAX_IMAGES_PER_JOB + 1)]
        status, payload = self.request_json("/download-images", {"images": images})
        self.assertEqual(status, 400)
        self.assertFalse(payload["accepted"])
        self.assertIn("maximum", payload["message"].lower())

    def test_cancel_without_job_reports_conflict(self):
        status, payload = self.request_json("/cancel-images", {})
        self.assertEqual(status, 409)
        self.assertFalse(payload["cancelled"])
        self.assertIn("No image download job", payload["message"])

    def test_unknown_route_is_not_found(self):
        status, payload = self.request_json("/not-a-route", {})
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "Not found")


if __name__ == "__main__":
    unittest.main(verbosity=2)
