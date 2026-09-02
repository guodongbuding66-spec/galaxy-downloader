from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from tool_artifacts import (  # noqa: E402
    ToolArtifact,
    ToolArtifactError,
    download_verified_artifact,
    extract_verified_artifact,
    install_verified_artifact,
    run_tool_artifacts_self_test,
    runtime_arch,
    runtime_platform,
    validate_artifact,
)


class ToolArtifactTests(unittest.TestCase):
    def artifact(self, payload: bytes = b"payload", **overrides) -> ToolArtifact:
        values = {
            "tool": "demo",
            "version": "1.0.0",
            "platform": runtime_platform(),
            "arch": runtime_arch(),
            "url": "https://downloads.example.com/demo.zip",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "archive": "raw",
        }
        values.update(overrides)
        return ToolArtifact(**values)

    def test_rejects_insecure_or_private_urls(self) -> None:
        for url in (
            "http://downloads.example.com/demo.zip",
            "https://user:pass@downloads.example.com/demo.zip",
            "https://localhost/demo.zip",
            "https://127.0.0.1/demo.zip",
            "https://10.0.0.5/demo.zip",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ToolArtifactError):
                    validate_artifact(self.artifact(url=url))

    def test_rejects_platform_arch_and_digest_mismatch(self) -> None:
        with self.assertRaises(ToolArtifactError):
            validate_artifact(self.artifact(platform="definitely-not-this-platform"))
        with self.assertRaises(ToolArtifactError):
            validate_artifact(self.artifact(arch="definitely-not-this-arch"))
        with self.assertRaises(ToolArtifactError):
            validate_artifact(self.artifact(sha256="bad"))

    def test_download_requires_matching_sha256_and_https_redirect(self) -> None:
        payload = b"verified payload"
        artifact = self.artifact(payload)

        class Response(io.BytesIO):
            headers = {"Content-Length": str(len(payload))}

            def __init__(self, data: bytes, final_url: str):
                super().__init__(data)
                self.final_url = final_url

            def geturl(self):
                return self.final_url

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "tool.bin"
            result = download_verified_artifact(
                artifact,
                target,
                opener=lambda *_args, **_kwargs: Response(payload, artifact.url),
            )
            self.assertEqual(result.read_bytes(), payload)

            bad = self.artifact(payload, sha256="0" * 64)
            with self.assertRaises(ToolArtifactError):
                download_verified_artifact(
                    bad,
                    root / "bad.bin",
                    opener=lambda *_args, **_kwargs: Response(payload, bad.url),
                )
            self.assertFalse((root / "bad.bin").exists())

            with self.assertRaises(ToolArtifactError):
                download_verified_artifact(
                    artifact,
                    root / "redirect.bin",
                    opener=lambda *_args, **_kwargs: Response(payload, "http://downloads.example.com/demo.zip"),
                )

    def test_zip_traversal_and_symlink_are_rejected(self) -> None:
        artifact = self.artifact(archive="zip")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            traversal = root / "traversal.zip"
            with zipfile.ZipFile(traversal, "w") as archive:
                archive.writestr("../escape", b"bad")
            with self.assertRaises(ToolArtifactError):
                extract_verified_artifact(artifact, traversal, root / "out-traversal")

            symlink = root / "symlink.zip"
            info = zipfile.ZipInfo("bin/link")
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            with zipfile.ZipFile(symlink, "w") as archive:
                archive.writestr(info, "../target")
            with self.assertRaises(ToolArtifactError):
                extract_verified_artifact(artifact, symlink, root / "out-symlink")

    def test_zip_limits_fail_before_any_member_is_written(self) -> None:
        artifact = self.artifact(archive="zip")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "limited.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("a", b"aa")
                archive.writestr("b", b"bb")
                archive.writestr("c", b"cc")

            member_out = root / "member-out"
            with self.assertRaises(ToolArtifactError):
                extract_verified_artifact(
                    artifact,
                    archive_path,
                    member_out,
                    max_members=2,
                    max_extracted_bytes=100,
                )
            self.assertEqual(list(member_out.iterdir()), [])

            byte_out = root / "byte-out"
            with self.assertRaises(ToolArtifactError):
                extract_verified_artifact(
                    artifact,
                    archive_path,
                    byte_out,
                    max_members=10,
                    max_extracted_bytes=5,
                )
            self.assertEqual(list(byte_out.iterdir()), [])

    def test_tar_limits_fail_before_any_member_is_written(self) -> None:
        artifact = self.artifact(archive="tar.gz")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "limited.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                for name, payload in (("a", b"aa"), ("b", b"bb"), ("c", b"cc")):
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))

            member_out = root / "member-out"
            with self.assertRaises(ToolArtifactError):
                extract_verified_artifact(
                    artifact,
                    archive_path,
                    member_out,
                    max_members=2,
                    max_extracted_bytes=100,
                )
            self.assertEqual(list(member_out.iterdir()), [])

            byte_out = root / "byte-out"
            with self.assertRaises(ToolArtifactError):
                extract_verified_artifact(
                    artifact,
                    archive_path,
                    byte_out,
                    max_members=10,
                    max_extracted_bytes=5,
                )
            self.assertEqual(list(byte_out.iterdir()), [])

    def test_raw_artifact_respects_extracted_byte_limit_and_cleans_partial_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(b"123456")
            artifact = self.artifact(
                payload=source.read_bytes(),
                url="https://downloads.example.com/tool.bin",
                archive="raw",
            )
            output = root / "out"
            with self.assertRaises(ToolArtifactError):
                extract_verified_artifact(
                    artifact,
                    source,
                    output,
                    max_members=1,
                    max_extracted_bytes=5,
                )
            self.assertFalse((output / "tool.bin").exists())

    def test_invalid_extraction_limits_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(b"x")
            artifact = self.artifact(
                payload=b"x",
                url="https://downloads.example.com/tool.bin",
                archive="raw",
            )
            with self.assertRaises(ToolArtifactError):
                extract_verified_artifact(artifact, source, root / "out-a", max_members=0)
            with self.assertRaises(ToolArtifactError):
                extract_verified_artifact(artifact, source, root / "out-b", max_extracted_bytes=0)

    def test_atomic_install_preserves_previous_target_on_digest_validation_or_limit_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "tool.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("bin/tool", b"new")
            archive_bytes = archive_path.read_bytes()
            artifact = self.artifact(
                payload=archive_bytes,
                archive="zip",
                sha256=hashlib.sha256(archive_bytes).hexdigest(),
            )
            target = root / "installed"
            (target / "bin").mkdir(parents=True)
            (target / "bin" / "tool").write_bytes(b"old")

            tampered = root / "tampered.zip"
            tampered.write_bytes(archive_bytes + b"tampered")
            with self.assertRaises(ToolArtifactError):
                install_verified_artifact(
                    artifact,
                    tampered,
                    target,
                    required_files=("bin/tool",),
                    validator=lambda _path: True,
                )
            self.assertEqual((target / "bin" / "tool").read_bytes(), b"old")

            with self.assertRaises(ToolArtifactError):
                install_verified_artifact(
                    artifact,
                    archive_path,
                    target,
                    required_files=("bin/tool",),
                    validator=lambda _path: False,
                )
            self.assertEqual((target / "bin" / "tool").read_bytes(), b"old")

            with self.assertRaises(ToolArtifactError):
                install_verified_artifact(
                    artifact,
                    archive_path,
                    target,
                    required_files=("bin/tool",),
                    validator=lambda _path: True,
                    max_extracted_bytes=2,
                )
            self.assertEqual((target / "bin" / "tool").read_bytes(), b"old")

            installed = install_verified_artifact(
                artifact,
                archive_path,
                target,
                required_files=("bin/tool",),
                validator=lambda path: (path / "bin" / "tool").read_bytes() == b"new",
            )
            self.assertEqual((installed / "bin" / "tool").read_bytes(), b"new")

    def test_embedded_self_test(self) -> None:
        run_tool_artifacts_self_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
