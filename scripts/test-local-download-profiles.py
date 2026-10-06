#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

import download_profiles as profiles  # noqa: E402


class DownloadProfilesContractTests(unittest.TestCase):
    def engine(self, root: Path):
        state = root / "state"
        state.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            app_dir=lambda: root,
            state_dir=lambda: state,
        )

    def test_crud_duplicate_and_atomic_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = self.engine(root)
            created = profiles.create_profile(
                engine,
                "YouTube 4K",
                settings={
                    "video": "2160p",
                    "audio": "best",
                    "container": "mkv",
                    "archive": True,
                    "browser": "none",
                    "directory": "Video/YouTube",
                    "rateLimitMiB": 12.5,
                    "chapters": True,
                    "sponsorBlock": True,
                    "script": {"enabled": False, "postDownload": "echo done"},
                },
                patterns=["youtube.com/*", "www.youtube.com/*"],
            )
            self.assertRegex(created["id"], r"^[a-f0-9]{32}$")
            self.assertEqual(created["settings"]["container"], "mkv")
            self.assertEqual(created["settings"]["rateLimitMiB"], 12.5)
            self.assertFalse(created["settings"]["script"]["enabled"])

            state_path = root / "state" / profiles.STATE_FILENAME
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], profiles.STATE_VERSION)
            self.assertEqual(payload["profiles"][0]["name"], "YouTube 4K")
            self.assertFalse(state_path.with_suffix(state_path.suffix + ".tmp").exists())

            updated = profiles.update_profile(engine, created["id"], name="YouTube Archive")
            self.assertEqual(updated["name"], "YouTube Archive")
            self.assertEqual(updated["settings"]["container"], "mkv")

            copied = profiles.duplicate_profile(engine, created["id"])
            self.assertNotEqual(copied["id"], created["id"])
            self.assertEqual(copied["settings"], updated["settings"])
            self.assertEqual(len(profiles.list_profiles(engine)), 2)

            self.assertTrue(profiles.delete_profile(engine, copied["id"]))
            self.assertFalse(profiles.delete_profile(engine, copied["id"]))
            self.assertEqual([row["id"] for row in profiles.list_profiles(engine)], [created["id"]])

    def test_url_pattern_resolution_and_manual_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = self.engine(Path(directory))
            youtube = profiles.create_profile(engine, "YouTube", patterns=["youtube.com/*"])
            course = profiles.create_profile(engine, "Course", patterns=["udemy.com/course/*"])

            match = profiles.resolve_profile(engine, "https://youtube.com/watch?v=123")
            self.assertEqual(match["id"], youtube["id"])
            match = profiles.resolve_profile(engine, "https://udemy.com/course/python/?coupon=abc")
            self.assertEqual(match["id"], course["id"])
            self.assertIsNone(profiles.resolve_profile(engine, "https://example.com/video"))

            manual = profiles.resolve_profile(
                engine,
                "https://youtube.com/watch?v=123",
                manual_profile_id=course["id"],
            )
            self.assertEqual(manual["id"], course["id"])

            self.assertTrue(profiles.pattern_matches("*.youtube.com/*", "https://music.youtube.com/watch?v=1"))
            self.assertFalse(profiles.pattern_matches("youtube.com/*", "https://notyoutube.com/watch?v=1"))

    def test_export_import_merge_and_replace(self) -> None:
        with tempfile.TemporaryDirectory() as left_dir, tempfile.TemporaryDirectory() as right_dir:
            left = self.engine(Path(left_dir))
            right = self.engine(Path(right_dir))
            original = profiles.create_profile(left, "Podcast", settings={"container": "mp4"}, patterns=["example.com/podcast/*"])
            exported = profiles.export_profiles(left)

            merged = profiles.import_profiles(right, exported)
            self.assertEqual(len(merged), 1)
            self.assertEqual(merged[0]["id"], original["id"])

            merged_again = profiles.import_profiles(right, exported)
            self.assertEqual(len(merged_again), 2)
            self.assertNotEqual(merged_again[1]["id"], original["id"])

            replaced = profiles.import_profiles(right, exported, replace=True)
            self.assertEqual(len(replaced), 1)
            self.assertEqual(replaced[0]["id"], original["id"])

    def test_validation_rejects_unsafe_or_unbounded_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = self.engine(Path(directory))
            invalid_settings = (
                {"container": "exe"},
                {"browser": "unknown"},
                {"directory": "../escape"},
                {"directory": "C:/absolute"},
                {"rateLimitMiB": 0},
                {"rateLimitMiB": 2048},
                {"rateLimitMiB": True},
                {"archive": "yes"},
                {"script": {"enabled": "yes"}},
                {"unknown": True},
            )
            for settings in invalid_settings:
                with self.subTest(settings=settings), self.assertRaises(profiles.DownloadProfileError):
                    profiles.create_profile(engine, "Invalid", settings=settings)

            invalid_patterns = (
                "",
                "file://example.com/*",
                "https://user:pass@example.com/*",
                "https://example.com:8443/*",
                "https://example.com/*?token=1",
            )
            for pattern in invalid_patterns:
                with self.subTest(pattern=pattern), self.assertRaises(profiles.DownloadProfileError):
                    profiles.create_profile(engine, "Invalid", patterns=[pattern])

    def test_import_is_versioned_bounded_and_does_not_accept_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = self.engine(Path(directory))
            with self.assertRaises(profiles.DownloadProfileError):
                profiles.import_profiles(engine, '{"version":999,"profiles":[]}')
            with self.assertRaises(profiles.DownloadProfileError):
                profiles.import_profiles(engine, '{"version":1,"profiles":[{"name":"x","extra":true}]}')
            with self.assertRaises(profiles.DownloadProfileError):
                profiles.import_profiles(engine, b"x" * (profiles.MAX_IMPORT_BYTES + 1))


if __name__ == "__main__":
    unittest.main()
