from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-engine"))

import external_ytdlp  # noqa: E402
import nfo_integration_policy as policy  # noqa: E402


class NfoIntegrationUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        policy._NFO_CONTEXT.job = None
        policy._NFO_CONTEXT.temp_dir = None
        policy._NFO_CONTEXT.info_template = None

    def tearDown(self) -> None:
        policy._NFO_CONTEXT.job = None
        policy._NFO_CONTEXT.temp_dir = None
        policy._NFO_CONTEXT.info_template = None

    def test_external_command_keeps_login_collection_and_media_output_contract(self) -> None:
        command = [
            "yt-dlp",
            "--no-write-info-json",
            "--cookies-from-browser",
            "edge",
            "--yes-playlist",
            "--playlist-items",
            "3,1",
            "-o",
            "downloads/%(title)s.%(ext)s",
            "--",
            "https://www.bilibili.com/video/BV1demo",
        ]
        policy._NFO_CONTEXT.info_template = "downloads/.galaxy-nfo/%(title)s.%(ext)s"
        updated = policy._apply_external_nfo_command(
            SimpleNamespace(include_nfo=True),
            list(command),
        )
        self.assertIn("--write-info-json", updated)
        self.assertNotIn("--no-write-info-json", updated)
        self.assertEqual(updated[updated.index("--cookies-from-browser") + 1], "edge")
        self.assertEqual(updated[updated.index("--playlist-items") + 1], "3,1")
        self.assertEqual(updated[updated.index("-o") + 1], "downloads/%(title)s.%(ext)s")
        info_outputs = [
            updated[index + 1]
            for index, value in enumerate(updated[:-1])
            if value == "-o" and updated[index + 1].startswith("infojson:")
        ]
        self.assertEqual(
            info_outputs,
            ["infojson:downloads/.galaxy-nfo/%(title)s.%(ext)s"],
        )
        self.assertEqual(updated[-2:], ["--", "https://www.bilibili.com/video/BV1demo"])

    def test_disabled_external_command_is_exactly_unchanged(self) -> None:
        command = ["yt-dlp", "--no-write-info-json", "--", "https://example.com/video"]
        policy._NFO_CONTEXT.info_template = "/tmp/info/%(title)s.%(ext)s"
        self.assertEqual(
            policy._apply_external_nfo_command(SimpleNamespace(include_nfo=False), list(command)),
            command,
        )

    def test_embedded_options_use_type_specific_infojson_template(self) -> None:
        policy._NFO_CONTEXT.info_template = "/tmp/.galaxy-nfo/%(title)s.%(ext)s"
        options = policy._apply_embedded_nfo_options(
            SimpleNamespace(include_nfo=True),
            {"outtmpl": "/downloads/%(title)s.%(ext)s", "writeinfojson": False},
        )
        self.assertTrue(options["writeinfojson"])
        self.assertEqual(options["outtmpl"]["default"], "/downloads/%(title)s.%(ext)s")
        self.assertEqual(
            options["outtmpl"]["infojson"],
            "/tmp/.galaxy-nfo/%(title)s.%(ext)s",
        )

    def test_promotion_is_bounded_and_refuses_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "stage"
            output = root / "output"
            staging.mkdir()
            output.mkdir()
            sample = {
                "id": "BV1demo",
                "extractor_key": "BiliBili",
                "title": "Demo",
                "description": "Description",
            }
            good = staging / "Demo [BV1demo].info.json"
            good.write_text(json.dumps(sample), encoding="utf-8")
            protected = root / "protected.txt"
            protected.write_text("keep", encoding="utf-8")
            target = output / "Demo [BV1demo].nfo"
            try:
                target.symlink_to(protected)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this platform")

            result = policy._promote_nfo_sidecars(staging, output)
            self.assertEqual(result.saved, ())
            self.assertEqual(len(result.failures), 1)
            self.assertEqual(protected.read_text(encoding="utf-8"), "keep")

    def test_discovery_is_deterministic_bounded_and_ignores_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "b.info.json").write_text("{}", encoding="utf-8")
            (root / "A.info.json").write_text("{}", encoding="utf-8")
            with unittest.mock.patch.object(policy, "MAX_NFO_SIDECARS_PER_JOB", 1):
                files, truncated = policy._discover_info_json_files(root)
            self.assertEqual([path.name for path in files], ["A.info.json"])
            self.assertTrue(truncated)

    def test_policy_embedded_success_promotes_nfo_and_cleans_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = self._fake_engine(root, mode="valid")
            original_builder = external_ytdlp.build_external_command
            try:
                Job = policy.install_nfo_sidecar_policy(engine)
                parsed = engine.parse_job(
                    "galaxy-downloader://download?url=https%3A%2F%2Fexample.com%2Fv&nfo=1"
                )
                self.assertIsInstance(parsed, Job)
                self.assertTrue(parsed.include_nfo)
                self.assertTrue(
                    engine.job_from_payload({"sourceUrl": "https://example.com/v", "includeNfo": True}).include_nfo
                )
                self.assertTrue(engine.job_to_payload(parsed)["includeNfo"])

                window = engine.EngineWindow(parsed)
                window._run_job()
                target = root / "Demo [BV1demo].nfo"
                self.assertTrue(target.is_file())
                self.assertEqual(window._bridge["state"], "completed")
                self.assertEqual(window._bridge["nfoSidecarStatus"], "saved")
                self.assertEqual(window._bridge["nfoSidecarSavedCount"], 1)
                self.assertEqual(list(root.glob(".galaxy-nfo-*")), [])
                self.assertTrue(window.bridge_status()["nfoSidecar"])
                self.assertFalse(window.bridge_status()["nfoSidecarDefault"])
            finally:
                external_ytdlp.build_external_command = original_builder

    def test_nfo_failure_never_changes_completed_media_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = self._fake_engine(root, mode="malformed")
            original_builder = external_ytdlp.build_external_command
            try:
                policy.install_nfo_sidecar_policy(engine)
                job = engine.job_from_payload({"sourceUrl": "https://example.com/v", "includeNfo": True})
                window = engine.EngineWindow(job)
                window._run_job()
                self.assertEqual(window._bridge["state"], "completed")
                self.assertEqual(window._bridge["nfoSidecarStatus"], "failed")
                self.assertEqual(window._bridge["nfoSidecarSavedCount"], 0)
                self.assertTrue(window._bridge["nfoSidecarWarning"])
                self.assertEqual(list(root.glob(".galaxy-nfo-*")), [])
            finally:
                external_ytdlp.build_external_command = original_builder

    def test_completed_media_without_metadata_is_fail_visible_not_stuck_preparing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = self._fake_engine(root, mode="missing")
            original_builder = external_ytdlp.build_external_command
            try:
                policy.install_nfo_sidecar_policy(engine)
                job = engine.job_from_payload({"sourceUrl": "https://example.com/v", "includeNfo": True})
                window = engine.EngineWindow(job)
                window._run_job()
                self.assertEqual(window._bridge["state"], "completed")
                self.assertEqual(window._bridge["nfoSidecarStatus"], "failed")
                self.assertIn("no NFO metadata", window._bridge["nfoSidecarWarning"])
                self.assertEqual(list(root.glob(".galaxy-nfo-*")), [])
            finally:
                external_ytdlp.build_external_command = original_builder

    def test_cancelled_media_discards_metadata_and_preserves_media_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = self._fake_engine(root, mode="cancelled")
            original_builder = external_ytdlp.build_external_command
            try:
                policy.install_nfo_sidecar_policy(engine)
                job = engine.job_from_payload({"sourceUrl": "https://example.com/v", "includeNfo": True})
                window = engine.EngineWindow(job)
                window._run_job()
                self.assertEqual(window._bridge["state"], "cancelled")
                self.assertEqual(window._bridge["nfoSidecarStatus"], "cancelled")
                self.assertFalse((root / "Demo [BV1demo].nfo").exists())
                self.assertEqual(list(root.glob(".galaxy-nfo-*")), [])
            finally:
                external_ytdlp.build_external_command = original_builder

    @staticmethod
    def _fake_engine(root: Path, *, mode: str):
        @dataclass(frozen=True)
        class BaseJob:
            source_url: str

        def parse_job(raw: str):
            query = parse_qs(urlparse(raw).query)
            return BaseJob(query.get("url", ["https://example.com/v"])[0])

        def job_from_payload(payload):
            return BaseJob(str(payload.get("sourceUrl") or "https://example.com/v"))

        def job_to_payload(job):
            return {"sourceUrl": job.source_url}

        class Window:
            def __init__(self, job):
                self.job = job
                self._bridge = {"state": "ready"}

            def _update_bridge(self, **changes):
                self._bridge.update(changes)

            def bridge_status(self):
                return dict(self._bridge)

            def build_options(self):
                return {"outtmpl": str(root / "%(title)s.%(ext)s"), "writeinfojson": False}

            def _run_external_job(self, _executable):
                return False

            def _run_job(self):
                options = self.build_options()
                info_template = options["outtmpl"]["infojson"]
                staging = Path(info_template).parent
                staging.mkdir(parents=True, exist_ok=True)
                info = staging / "Demo [BV1demo].info.json"
                if mode == "malformed":
                    info.write_text("{", encoding="utf-8")
                elif mode in {"valid", "cancelled"}:
                    info.write_text(
                        json.dumps({
                            "id": "BV1demo",
                            "extractor_key": "BiliBili",
                            "title": "Demo",
                            "description": "Description",
                        }),
                        encoding="utf-8",
                    )
                self._bridge["state"] = "cancelled" if mode == "cancelled" else "completed"

        return SimpleNamespace(
            Job=BaseJob,
            EngineWindow=Window,
            parse_job=parse_job,
            job_from_payload=job_from_payload,
            job_to_payload=job_to_payload,
            _bool=lambda value, default=False: default if value is None else str(value).lower() in {"1", "true", "yes", "on"},
            default_download_dir=lambda: root,
        )


if __name__ == "__main__":
    unittest.main()
