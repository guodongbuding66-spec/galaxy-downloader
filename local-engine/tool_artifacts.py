from __future__ import annotations

import hashlib
import ipaddress
import os
import platform as platform_module
import shutil
import tarfile
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable, Iterable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_TOOL_ARTIFACT_BYTES = 1_500_000_000
MAX_TOOL_ARCHIVE_MEMBERS = 50_000
MAX_TOOL_EXTRACTED_BYTES = 4_000_000_000
_ALLOWED_ARCHIVES = {"raw", "zip", "tar.gz", "tar.xz"}


class ToolArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolArtifact:
    tool: str
    version: str
    platform: str
    arch: str
    url: str
    sha256: str
    archive: str


@dataclass
class _ExtractionBudget:
    max_members: int
    max_bytes: int
    members: int = 0
    declared_bytes: int = 0
    written_bytes: int = 0

    def register(self, name: str, declared_size: int) -> None:
        if declared_size < 0:
            raise ToolArtifactError(f"tool archive member has invalid size: {name}")
        self.members += 1
        if self.members > self.max_members:
            raise ToolArtifactError(
                f"tool archive contains too many members ({self.members} > {self.max_members})"
            )
        self.declared_bytes += declared_size
        if self.declared_bytes > self.max_bytes:
            raise ToolArtifactError(
                f"tool archive expands beyond size limit ({self.declared_bytes} > {self.max_bytes})"
            )

    def consume(self, size: int) -> None:
        self.written_bytes += size
        if self.written_bytes > self.max_bytes:
            raise ToolArtifactError(
                f"tool archive wrote beyond size limit ({self.written_bytes} > {self.max_bytes})"
            )


def runtime_platform() -> str:
    value = platform_module.system().lower()
    return {"windows": "windows", "darwin": "macos", "linux": "linux"}.get(value, "other")


def runtime_arch() -> str:
    value = platform_module.machine().strip().lower().replace("_", "-")
    return {
        "amd64": "x86-64",
        "x86-64": "x86-64",
        "x86_64": "x86-64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(value, value or "unknown")


def _validate_https_url(url: str) -> None:
    try:
        parsed = urlparse(str(url or ""))
    except ValueError as exc:
        raise ToolArtifactError(f"invalid artifact URL: {exc}") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ToolArtifactError("tool artifacts must use HTTPS URLs")
    if parsed.username or parsed.password:
        raise ToolArtifactError("tool artifact URLs must not contain credentials")
    host = parsed.hostname.strip().lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise ToolArtifactError("localhost tool artifact URLs are not allowed")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return
    if not address.is_global:
        raise ToolArtifactError("private, loopback, link-local, or reserved artifact hosts are not allowed")


def validate_artifact(
    artifact: ToolArtifact,
    *,
    platform_name: str | None = None,
    arch: str | None = None,
) -> ToolArtifact:
    tool = artifact.tool.strip()
    version = artifact.version.strip()
    if not tool or not version:
        raise ToolArtifactError("tool artifact name and version are required")
    archive = artifact.archive.strip().lower()
    if archive not in _ALLOWED_ARCHIVES:
        raise ToolArtifactError(f"unsupported tool artifact archive: {archive}")
    digest = artifact.sha256.strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ToolArtifactError("tool artifact SHA-256 must be a 64-character hexadecimal digest")
    _validate_https_url(artifact.url)
    expected_platform = platform_name or runtime_platform()
    expected_arch = arch or runtime_arch()
    if artifact.platform != expected_platform:
        raise ToolArtifactError(
            f"tool artifact platform mismatch: expected {expected_platform}, got {artifact.platform}"
        )
    if artifact.arch != expected_arch:
        raise ToolArtifactError(f"tool artifact architecture mismatch: expected {expected_arch}, got {artifact.arch}")
    return artifact


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as input_file:
        while True:
            chunk = input_file.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _response_final_url(response, fallback: str) -> str:
    getter = getattr(response, "geturl", None)
    if callable(getter):
        try:
            value = getter()
        except Exception:
            value = None
        if value:
            return str(value)
    return fallback


def _response_content_length(response) -> int | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("Content-Length")
    except Exception:
        return None
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def download_verified_artifact(
    artifact: ToolArtifact,
    destination: Path,
    *,
    opener: Callable[..., BinaryIO] = urlopen,
    timeout: float = 45.0,
    max_bytes: int = MAX_TOOL_ARTIFACT_BYTES,
    platform_name: str | None = None,
    arch: str | None = None,
) -> Path:
    validate_artifact(artifact, platform_name=platform_name, arch=arch)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + f".{uuid.uuid4().hex}.part")
    digest = hashlib.sha256()
    written = 0
    request = Request(
        artifact.url,
        headers={
            "User-Agent": "GalaxyLocalEngine/verified-tool-artifacts",
            "Accept": "application/octet-stream,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        response = opener(request, timeout=max(1.0, float(timeout)))
        final_url = _response_final_url(response, artifact.url)
        _validate_https_url(final_url)
        declared = _response_content_length(response)
        if declared is not None and declared > max_bytes:
            raise ToolArtifactError(f"tool artifact exceeds size limit ({declared} > {max_bytes})")
        with response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ToolArtifactError(f"tool artifact exceeds size limit ({written} > {max_bytes})")
                digest.update(chunk)
                output.write(chunk)
        actual = digest.hexdigest()
        if actual != artifact.sha256.lower():
            raise ToolArtifactError(
                f"tool artifact SHA-256 mismatch: expected {artifact.sha256.lower()}, got {actual}"
            )
        temporary.replace(target)
        return target
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _safe_member_destination(root: Path, member_name: str) -> Path:
    normalized = PurePosixPath(member_name.replace("\\", "/"))
    if normalized.is_absolute() or any(part in {"", ".", ".."} for part in normalized.parts):
        raise ToolArtifactError(f"unsafe archive member path: {member_name}")
    destination = root.joinpath(*normalized.parts)
    try:
        destination.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (ValueError, OSError, RuntimeError) as exc:
        raise ToolArtifactError(f"archive member escapes destination: {member_name}") from exc
    return destination


def _validate_extraction_limits(max_members: int, max_extracted_bytes: int) -> tuple[int, int]:
    members = int(max_members)
    extracted = int(max_extracted_bytes)
    if members < 1:
        raise ToolArtifactError("tool archive member limit must be at least 1")
    if extracted < 1:
        raise ToolArtifactError("tool archive extracted-byte limit must be at least 1")
    return members, extracted


def _copy_bounded(input_file: BinaryIO, output_file: BinaryIO, budget: _ExtractionBudget) -> None:
    while True:
        chunk = input_file.read(1024 * 1024)
        if not chunk:
            break
        budget.consume(len(chunk))
        output_file.write(chunk)


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def _extract_zip(
    source: Path,
    destination: Path,
    *,
    max_members: int,
    max_extracted_bytes: int,
) -> None:
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        budget = _ExtractionBudget(max_members=max_members, max_bytes=max_extracted_bytes)
        for info in infos:
            _safe_member_destination(destination, info.filename)
            if _zip_member_is_symlink(info):
                raise ToolArtifactError(f"symbolic links are not allowed in tool archives: {info.filename}")
            budget.register(info.filename, 0 if info.is_dir() else int(info.file_size))

        for info in infos:
            target = _safe_member_destination(destination, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with archive.open(info, "r") as input_file, target.open("wb") as output_file:
                    _copy_bounded(input_file, output_file, budget)
            except Exception:
                try:
                    target.unlink()
                except OSError:
                    pass
                raise
            unix_mode = (info.external_attr >> 16) & 0o777
            if unix_mode and os.name != "nt":
                target.chmod(unix_mode)


def _extract_tar(
    source: Path,
    destination: Path,
    mode: str,
    *,
    max_members: int,
    max_extracted_bytes: int,
) -> None:
    with tarfile.open(source, mode) as archive:
        members = archive.getmembers()
        budget = _ExtractionBudget(max_members=max_members, max_bytes=max_extracted_bytes)
        for member in members:
            _safe_member_destination(destination, member.name)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ToolArtifactError(f"links and special files are not allowed in tool archives: {member.name}")
            if not member.isdir() and not member.isfile():
                raise ToolArtifactError(f"unsupported tool archive member: {member.name}")
            budget.register(member.name, int(member.size) if member.isfile() else 0)

        for member in members:
            target = _safe_member_destination(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            input_file = archive.extractfile(member)
            if input_file is None:
                raise ToolArtifactError(f"could not read tool archive member: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with input_file, target.open("wb") as output_file:
                    _copy_bounded(input_file, output_file, budget)
            except Exception:
                try:
                    target.unlink()
                except OSError:
                    pass
                raise
            if os.name != "nt":
                target.chmod(member.mode & 0o777)


def extract_verified_artifact(
    artifact: ToolArtifact,
    source: Path,
    destination: Path,
    *,
    max_members: int = MAX_TOOL_ARCHIVE_MEMBERS,
    max_extracted_bytes: int = MAX_TOOL_EXTRACTED_BYTES,
) -> Path:
    member_limit, byte_limit = _validate_extraction_limits(max_members, max_extracted_bytes)
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    archive_type = artifact.archive.lower()
    if archive_type == "raw":
        target = root / Path(urlparse(artifact.url).path).name
        if not target.name:
            raise ToolArtifactError("raw tool artifact URL must contain a file name")
        size = Path(source).stat().st_size
        budget = _ExtractionBudget(max_members=member_limit, max_bytes=byte_limit)
        budget.register(target.name, size)
        try:
            with Path(source).open("rb") as input_file, target.open("wb") as output_file:
                _copy_bounded(input_file, output_file, budget)
        except Exception:
            try:
                target.unlink()
            except OSError:
                pass
            raise
        shutil.copystat(source, target)
    elif archive_type == "zip":
        _extract_zip(
            Path(source),
            root,
            max_members=member_limit,
            max_extracted_bytes=byte_limit,
        )
    elif archive_type == "tar.gz":
        _extract_tar(
            Path(source),
            root,
            "r:gz",
            max_members=member_limit,
            max_extracted_bytes=byte_limit,
        )
    elif archive_type == "tar.xz":
        _extract_tar(
            Path(source),
            root,
            "r:xz",
            max_members=member_limit,
            max_extracted_bytes=byte_limit,
        )
    else:
        raise ToolArtifactError(f"unsupported tool artifact archive: {archive_type}")
    return root


def _required_files_present(root: Path, required_files: Iterable[str]) -> None:
    for value in required_files:
        relative = PurePosixPath(str(value).replace("\\", "/"))
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ToolArtifactError(f"unsafe required file path: {value}")
        target = root.joinpath(*relative.parts)
        if not target.is_file() or target.is_symlink():
            raise ToolArtifactError(f"required tool file is missing: {value}")


def install_verified_artifact(
    artifact: ToolArtifact,
    archive_path: Path,
    target_directory: Path,
    *,
    required_files: Iterable[str],
    validator: Callable[[Path], bool] | None = None,
    max_members: int = MAX_TOOL_ARCHIVE_MEMBERS,
    max_extracted_bytes: int = MAX_TOOL_EXTRACTED_BYTES,
) -> Path:
    validate_artifact(artifact)
    source = Path(archive_path)
    actual_digest = _sha256_file(source)
    expected_digest = artifact.sha256.lower()
    if actual_digest != expected_digest:
        raise ToolArtifactError(
            f"tool artifact SHA-256 mismatch at install boundary: expected {expected_digest}, got {actual_digest}"
        )

    target = Path(target_directory)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".{target.name}.staging-{uuid.uuid4().hex}"
    backup = parent / f".{target.name}.backup-{uuid.uuid4().hex}"
    try:
        extract_verified_artifact(
            artifact,
            source,
            staging,
            max_members=max_members,
            max_extracted_bytes=max_extracted_bytes,
        )
        _required_files_present(staging, required_files)
        if validator is not None and not validator(staging):
            raise ToolArtifactError("tool artifact validation command failed")
        if target.exists():
            target.replace(backup)
        staging.replace(target)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        return target
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not target.exists():
            try:
                backup.replace(target)
            except OSError:
                pass
        raise


def run_tool_artifacts_self_test() -> None:
    import io

    payload = b"verified-tool-payload"
    digest = hashlib.sha256(payload).hexdigest()
    artifact = ToolArtifact(
        tool="demo",
        version="1.0.0",
        platform=runtime_platform(),
        arch=runtime_arch(),
        url="https://downloads.example.com/demo.zip",
        sha256=digest,
        archive="raw",
    )
    validate_artifact(artifact)

    class Headers(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class Response(io.BytesIO):
        headers = Headers({"Content-Length": str(len(payload))})

        def geturl(self):
            return artifact.url

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        downloaded = download_verified_artifact(
            artifact,
            root / "artifact.bin",
            opener=lambda *_args, **_kwargs: Response(payload),
        )
        assert downloaded.read_bytes() == payload

        archive_file = root / "demo.zip"
        with zipfile.ZipFile(archive_file, "w") as archive:
            archive.writestr("bin/demo", b"demo")
        archive_artifact = ToolArtifact(
            tool="demo",
            version="1.0.0",
            platform=runtime_platform(),
            arch=runtime_arch(),
            url="https://downloads.example.com/demo.zip",
            sha256=hashlib.sha256(archive_file.read_bytes()).hexdigest(),
            archive="zip",
        )
        installed = install_verified_artifact(
            archive_artifact,
            archive_file,
            root / "installed",
            required_files=("bin/demo",),
            validator=lambda path: (path / "bin" / "demo").read_bytes() == b"demo",
        )
        assert (installed / "bin" / "demo").read_bytes() == b"demo"

        unsafe = root / "unsafe.zip"
        with zipfile.ZipFile(unsafe, "w") as archive:
            archive.writestr("../escape", b"bad")
        try:
            extract_verified_artifact(archive_artifact, unsafe, root / "unsafe-out")
        except ToolArtifactError:
            pass
        else:
            raise AssertionError("path traversal archive was not rejected")
