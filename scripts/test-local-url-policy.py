from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
sys.path.insert(0, str(LOCAL_ENGINE))

import url_policy  # noqa: E402


class LocalPublicUrlPolicyTests(unittest.TestCase):
    def test_literal_local_private_and_credentialed_urls_are_blocked(self):
        blocked = (
            "http://localhost:8080/video.mp4",
            "http://127.0.0.1/video.mp4",
            "http://10.0.0.5/video.mp4",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.20/video.mp4",
            "http://[::1]/video.mp4",
            "http://[fe80::1%25Ethernet]/video.mp4",
            "https://user:secret@example.com/video.mp4",
            "file:///tmp/video.mp4",
        )
        for value in blocked:
            with self.subTest(value=value):
                self.assertFalse(url_policy.is_public_http_url(value))

    def test_dns_must_resolve_only_to_public_addresses(self):
        public_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0)),
        ]
        with mock.patch.object(url_policy.socket, "getaddrinfo", return_value=public_answer):
            self.assertTrue(url_policy.is_public_http_url("https://media.example/video.mp4"))
            self.assertEqual(
                url_policy.validated_public_http_url("  https://media.example/video.mp4  "),
                "https://media.example/video.mp4",
            )

        mixed_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 443)),
        ]
        with mock.patch.object(url_policy.socket, "getaddrinfo", return_value=mixed_answer):
            self.assertFalse(url_policy.is_public_http_url("https://mixed.example/video.mp4"))

    def test_dns_resolution_failure_is_fail_closed(self):
        with mock.patch.object(url_policy.socket, "getaddrinfo", side_effect=socket.gaierror("no dns")):
            self.assertFalse(url_policy.is_public_http_url("https://unresolved.example/video.mp4"))
            with self.assertRaises(url_policy.PublicUrlError):
                url_policy.validated_public_http_url("https://unresolved.example/video.mp4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
