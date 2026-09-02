from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from tool_sources import (  # noqa: E402
    BTBN_PROVIDER_ID,
    BTBN_RELEASES_API,
    FFMPEG_PROVIDER_PROVENANCE,
    ToolSourceError,
    fetch_btbn_releases,
    resolve_btbn_ffmpeg_source,
    run_tool_sources_self_test,
    trusted_ffmpeg_source_available,
)


class ToolSourceTests(unittest.TestCase):
    def release(self, *, platform_name: str = "windows", arch: str = "x86-64", digest: str = "a" * 64):
        target, extension = {
            ("windows", "x86-64"): ("win64", "zip"),
            ("windows", "arm64"): ("winarm64", "zip"),
            ("linux", "x86-64"): ("linux64", "tar.xz"),
            ("linux", "arm64"): ("linuxarm64", "tar.xz"),
        }[(platform_name, arch)]
        tag = "autobuild-2026-09-01-13-13"
        name = f"ffmpeg-N-126313-g1ae4048218-{target}-gpl.{extension}"
        return {
            "tag_name": tag,
            "draft": False,
            "prerelease": False,
            "published_at": "2026-09-01T13:36:08Z",
            "html_url": f"https://github.com/BtbN/FFmpeg-Builds/releases/tag/{tag}",
            "assets": [
                {
                    "name": name,
                    "digest": f"sha256:{digest}",
                    "browser_download_url": f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{tag}/{name}",
                }
            ],
        }

    def test_resolves_all_supported_platform_targets(self) -> None:
        for platform_name, arch, archive in (
            ("windows", "x86-64", "zip"),
            ("windows", "arm64", "zip"),
            ("linux", "x86-64", "tar.xz"),
            ("linux", "arm64", "tar.xz"),
        ):
            with self.subTest(platform_name=platform_name, arch=arch):
                resolved = resolve_btbn_ffmpeg_source(
                    platform_name=platform_name,
                    arch=arch,
                    releases=[self.release(platform_name=platform_name, arch=arch)],
                )
                self.assertEqual(resolved.provider_id, BTBN_PROVIDER_ID)
                self.assertEqual(resolved.artifact.platform, platform_name)
                self.assertEqual(resolved.artifact.arch, arch)
                self.assertEqual(resolved.artifact.archive, archive)
                self.assertEqual(resolved.provenance_url, FFMPEG_PROVIDER_PROVENANCE)
                self.assertTrue(resolved.release_tag.startswith("autobuild-"))
                self.assertNotIn("/latest/", resolved.artifact.url)

    def test_skips_floating_latest_release(self) -> None:
        floating = {
            "tag_name": "latest",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-09-02T00:00:00Z",
            "html_url": "https://github.com/BtbN/FFmpeg-Builds/releases/tag/latest",
            "assets": [],
        }
        resolved = resolve_btbn_ffmpeg_source(
            platform_name="windows",
            arch="x86-64",
            releases=[floating, self.release()],
        )
        self.assertNotEqual(resolved.release_tag, "latest")

    def test_rejects_bad_digest_wrong_download_url_and_duplicate_asset(self) -> None:
        bad_digest = self.release(digest="bad")
        with self.assertRaises(ToolSourceError):
            resolve_btbn_ffmpeg_source(platform_name="windows", arch="x86-64", releases=[bad_digest])

        wrong_url = self.release()
        wrong_url["assets"][0]["browser_download_url"] = "https://example.com/tool.zip"
        with self.assertRaises(ToolSourceError):
            resolve_btbn_ffmpeg_source(platform_name="windows", arch="x86-64", releases=[wrong_url])

        duplicate = self.release()
        duplicate["assets"].append(dict(duplicate["assets"][0]))
        with self.assertRaises(ToolSourceError):
            resolve_btbn_ffmpeg_source(platform_name="windows", arch="x86-64", releases=[duplicate])

    def test_rejects_forged_release_url_and_unsupported_platform(self) -> None:
        forged = self.release()
        forged["html_url"] = "https://github.com/other/repo/releases/tag/autobuild-2026-09-01-13-13"
        with self.assertRaises(ToolSourceError):
            resolve_btbn_ffmpeg_source(platform_name="windows", arch="x86-64", releases=[forged])
        with self.assertRaises(ToolSourceError):
            resolve_btbn_ffmpeg_source(platform_name="macos", arch="arm64", releases=[])
        self.assertFalse(trusted_ffmpeg_source_available(platform_name="macos", arch="arm64"))

    def test_fetch_rejects_redirect_away_from_pinned_github_api(self) -> None:
        payload = json.dumps([self.release()]).encode("utf-8")

        class Response(io.BytesIO):
            def __init__(self, data: bytes, final_url: str):
                super().__init__(data)
                self.final_url = final_url

            def geturl(self):
                return self.final_url

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        releases = fetch_btbn_releases(opener=lambda *_args, **_kwargs: Response(payload, BTBN_RELEASES_API))
        self.assertEqual(len(releases), 1)
        with self.assertRaises(ToolSourceError):
            fetch_btbn_releases(
                opener=lambda *_args, **_kwargs: Response(payload, "https://example.com/releases")
            )

    def test_embedded_self_test(self) -> None:
        run_tool_sources_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
