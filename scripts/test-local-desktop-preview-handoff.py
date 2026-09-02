from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import desktop_download_workbench as workbench  # noqa: E402
from desktop_preview_handoff import install_desktop_preview_handoff  # noqa: E402


class Var:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


class PreviewHandoffTests(unittest.TestCase):
    def make_engine(self):
        @dataclass(frozen=True)
        class BaseJob:
            source_url: str

        engine = SimpleNamespace()
        engine.Job = BaseJob

        def parse_job(raw: str):
            query = parse_qs(urlparse(raw).query)
            return engine.Job(unquote(query.get("url", [""])[0]))

        def job_from_payload(payload):
            source = str(payload.get("sourceUrl") or "")
            if not source.startswith(("http://", "https://")):
                raise ValueError("invalid source")
            return engine.Job(source)

        def job_to_payload(job):
            return {"sourceUrl": job.source_url}

        engine.parse_job = parse_job
        engine.job_from_payload = job_from_payload
        engine.job_to_payload = job_to_payload

        class Window:
            def __init__(self, job):
                self.job = job
                self._galaxy_close_pending = False
                self._quick_url_var = Var()
                self._quick_state_var = Var()
                self.focused = False

            def after(self, _delay, fn):
                fn()

            def deiconify(self):
                self.focused = True

            def lift(self):
                self.focused = True

            def focus_force(self):
                self.focused = True

            def submit_bridge_job(self, payload):
                return (False, "legacy submit")

            def bridge_status(self):
                return {"ok": True}

        engine.EngineWindow = Window
        return engine

    def test_protocol_and_payload_round_trip_preview_only(self):
        engine = self.make_engine()
        install_desktop_preview_handoff(engine)
        job = engine.parse_job(
            "galaxy-downloader://download?url=https%3A%2F%2Fexample.test%2Fwatch&preview=1"
        )
        self.assertTrue(job.preview_only)
        payload = engine.job_to_payload(job)
        self.assertTrue(payload["previewOnly"])
        rebuilt = engine.job_from_payload(payload)
        self.assertTrue(rebuilt.preview_only)
        self.assertEqual(rebuilt.source_url, "https://example.test/watch")

    def test_protocol_without_preview_preserves_download_behavior(self):
        engine = self.make_engine()
        install_desktop_preview_handoff(engine)
        job = engine.parse_job(
            "galaxy-downloader://download?url=https%3A%2F%2Fexample.test%2Fwatch"
        )
        self.assertFalse(job.preview_only)
        window = engine.EngineWindow(None)
        self.assertEqual(window.submit_bridge_job({"sourceUrl": "https://example.test/watch"}), (False, "legacy submit"))

    def test_resident_preview_is_not_forwarded_to_download_submit(self):
        engine = self.make_engine()
        calls = []
        original_parse = workbench._parse_quick_url_async
        workbench._parse_quick_url_async = lambda window, _engine: calls.append(window._quick_url_var.value)
        try:
            install_desktop_preview_handoff(engine)
            window = engine.EngineWindow(None)
            result = window.submit_bridge_job(
                {"sourceUrl": "https://example.test/watch", "previewOnly": True}
            )
            self.assertTrue(result.accepted)
            self.assertEqual(result.code, "PREVIEW_ACCEPTED")
            self.assertEqual(calls, ["https://example.test/watch"])
            self.assertEqual(window._quick_url_var.value, "https://example.test/watch")
            self.assertTrue(window.focused)
        finally:
            workbench._parse_quick_url_async = original_parse

    def test_cold_start_preview_does_not_become_startup_download_job(self):
        engine = self.make_engine()
        calls = []
        original_parse = workbench._parse_quick_url_async
        workbench._parse_quick_url_async = lambda window, _engine: calls.append(window._quick_url_var.value)
        try:
            install_desktop_preview_handoff(engine)
            preview_job = engine.job_from_payload(
                {"sourceUrl": "https://example.test/watch", "previewOnly": True}
            )
            window = engine.EngineWindow(preview_job)
            self.assertIsNone(window.job)
            self.assertEqual(calls, ["https://example.test/watch"])
        finally:
            workbench._parse_quick_url_async = original_parse

    def test_status_advertises_preview_handoff(self):
        engine = self.make_engine()
        install_desktop_preview_handoff(engine)
        window = engine.EngineWindow(None)
        self.assertTrue(window.bridge_status()["desktopPreviewHandoff"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
