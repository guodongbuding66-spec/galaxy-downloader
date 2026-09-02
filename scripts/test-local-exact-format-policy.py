from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from exact_format_policy import install_exact_format_policy, run_exact_format_policy_self_test  # noqa: E402


@dataclass(frozen=True)
class BaseJob:
    source_url: str
    video_quality: str = "best"
    audio_quality: str = "best"
    include_audio: bool = True


class BaseWindow:
    def bridge_status(self):
        return {"ok": True}


def fake_engine():
    module = SimpleNamespace()
    module.Job = BaseJob
    module.EngineWindow = BaseWindow
    module._bool = lambda value, default=False: default if value is None else str(value).lower() in {"1", "true", "yes", "on"}

    # Real Galaxy policy factories deliberately resolve engine_module.Job at
    # call time. That is what lets later dataclass policies extend the Job
    # contract without rewriting every earlier parser.
    def parse_job(raw: str):
        query = parse_qs(urlparse(raw).query)
        return module.Job(
            source_url=query.get("url", ["https://example.test/video"])[0],
            video_quality=query.get("video", ["best"])[0],
            audio_quality=query.get("audio", ["best"])[0],
            include_audio=module._bool(query.get("include_audio", ["1"])[0], True),
        )

    def from_payload(payload):
        return module.Job(
            source_url=str(payload.get("sourceUrl") or "https://example.test/video"),
            video_quality=str(payload.get("videoQuality") or "best"),
            audio_quality=str(payload.get("audioQuality") or "best"),
            include_audio=bool(payload.get("includeAudio", True)),
        )

    def to_payload(job):
        return {
            "sourceUrl": job.source_url,
            "videoQuality": job.video_quality,
            "audioQuality": job.audio_quality,
            "includeAudio": job.include_audio,
        }

    def selector(job):
        return f"legacy:{job.video_quality}:{job.audio_quality}:{int(job.include_audio)}"

    module.parse_job = parse_job
    module.job_from_payload = from_payload
    module.job_to_payload = to_payload
    module.format_selector = selector
    return module


class ExactFormatPolicyTests(unittest.TestCase):
    def test_self_test(self):
        run_exact_format_policy_self_test()

    def test_legacy_selector_is_unchanged_without_exact_ids(self):
        engine = fake_engine()
        install_exact_format_policy(engine)
        job = engine.job_from_payload({"sourceUrl": "https://example.test/v", "videoQuality": "1080p", "audioQuality": "192"})
        self.assertEqual(engine.format_selector(job), "legacy:1080p:192:1")

    def test_video_only_plus_audio_uses_exact_ids(self):
        engine = fake_engine()
        install_exact_format_policy(engine)
        job = engine.job_from_payload(
            {
                "sourceUrl": "https://example.test/v",
                "videoFormatId": "137",
                "audioFormatId": "251",
                "selectedVideoHasAudio": False,
            }
        )
        self.assertEqual(job.video_format_id, "137")
        self.assertEqual(job.audio_format_id, "251")
        self.assertEqual(engine.format_selector(job), "137+251")

    def test_muxed_video_does_not_add_audio_stream(self):
        engine = fake_engine()
        install_exact_format_policy(engine)
        job = engine.job_from_payload(
            {
                "sourceUrl": "https://example.test/v",
                "videoFormatId": "22",
                "audioFormatId": "251",
                "selectedVideoHasAudio": True,
            }
        )
        self.assertEqual(engine.format_selector(job), "22")

    def test_exact_video_without_audio_respects_include_audio_false(self):
        engine = fake_engine()
        install_exact_format_policy(engine)
        job = engine.job_from_payload(
            {
                "sourceUrl": "https://example.test/v",
                "videoFormatId": "137",
                "audioFormatId": "251",
                "includeAudio": False,
            }
        )
        self.assertEqual(engine.format_selector(job), "137")

    def test_audio_only_selection_is_supported(self):
        engine = fake_engine()
        install_exact_format_policy(engine)
        job = engine.job_from_payload({"sourceUrl": "https://example.test/a", "audioFormatId": "251"})
        self.assertEqual(engine.format_selector(job), "251")

    def test_payload_round_trip_preserves_exact_identity(self):
        engine = fake_engine()
        install_exact_format_policy(engine)
        job = engine.job_from_payload(
            {
                "sourceUrl": "https://example.test/v",
                "videoFormatId": "dash-video_1080",
                "audioFormatId": "audio-160",
                "selectedVideoHasAudio": False,
            }
        )
        payload = engine.job_to_payload(job)
        self.assertEqual(payload["videoFormatId"], "dash-video_1080")
        self.assertEqual(payload["audioFormatId"], "audio-160")
        self.assertFalse(payload["selectedVideoHasAudio"])
        restored = engine.job_from_payload(payload)
        self.assertEqual(restored, job)

    def test_protocol_query_supports_exact_ids(self):
        engine = fake_engine()
        install_exact_format_policy(engine)
        job = engine.parse_job(
            "galaxy-downloader://download?url=https%3A%2F%2Fexample.test%2Fv&video_format_id=137&audio_format_id=251&video_muxed=0"
        )
        self.assertEqual(engine.format_selector(job), "137+251")

    def test_selector_injection_is_rejected(self):
        engine = fake_engine()
        install_exact_format_policy(engine)
        with self.assertRaises(ValueError):
            engine.job_from_payload(
                {
                    "sourceUrl": "https://example.test/v",
                    "videoFormatId": "137+bestaudio/best",
                }
            )

    def test_bridge_capability_is_exposed(self):
        engine = fake_engine()
        install_exact_format_policy(engine)
        self.assertTrue(engine.EngineWindow().bridge_status()["exactFormatSelection"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
