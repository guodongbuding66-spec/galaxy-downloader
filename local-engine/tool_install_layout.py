from __future__ import annotations

import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

from tool_artifacts import ToolArtifact, ToolArtifactError, install_verified_artifact


def _safe_relative_path(value: str, *, label: str) -> PurePosixPath:
    path = PurePosixPath(str(value or "").replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ToolArtifactError(f"unsafe {label}: {value}")
    return path


def archive_root_from_asset_name(asset_name: str, archive: str) -> str:
    """Return the expected single top-level directory for a packaged tool asset."""
    name = Path(str(asset_name or "")).name
    archive_type = str(archive or "").lower()
    suffix = {
        "zip": ".zip",
        "tar.gz": ".tar.gz",
        "tar.xz": ".tar.xz",
    }.get(archive_type)
    if suffix is None or not name.endswith(suffix):
        raise ToolArtifactError(f"asset name does not match archive type {archive_type}: {asset_name}")
    root = name[: -len(suffix)]
    relative = _safe_relative_path(root, label="archive content root")
    if len(relative.parts) != 1:
        raise ToolArtifactError("archive content root must be a single directory name")
    return relative.as_posix()


def install_rooted_verified_artifact(
    artifact: ToolArtifact,
    archive_path: Path,
    target_directory: Path,
    *,
    content_root: str,
    required_files: Iterable[str],
    validator: Callable[[Path], bool] | None = None,
) -> Path:
    """Verify/extract a tool archive, then atomically promote one trusted root.

    Providers such as BtbN package binaries beneath a build-name directory. The
    generic artifact verifier intentionally preserves archive layout; this helper
    composes it with a second atomic promotion so runtime/tools can keep a stable
    provider-independent layout such as ffmpeg/bin.
    """
    root_relative = _safe_relative_path(content_root, label="archive content root")
    if len(root_relative.parts) != 1:
        raise ToolArtifactError("archive content root must be a single directory name")

    normalized_required: list[str] = []
    for value in required_files:
        relative = _safe_relative_path(str(value), label="required tool file")
        normalized_required.append((root_relative / relative).as_posix())

    target = Path(target_directory)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    workspace = parent / f".{target.name}.rooted-{uuid.uuid4().hex}"
    expanded = workspace / "expanded"
    backup = parent / f".{target.name}.backup-{uuid.uuid4().hex}"

    def expanded_validator(expanded_root: Path) -> bool:
        payload_root = expanded_root.joinpath(*root_relative.parts)
        if not payload_root.is_dir() or payload_root.is_symlink():
            return False
        return True if validator is None else bool(validator(payload_root))

    try:
        workspace.mkdir(parents=True, exist_ok=False)
        install_verified_artifact(
            artifact,
            archive_path,
            expanded,
            required_files=tuple(normalized_required),
            validator=expanded_validator,
        )
        payload_root = expanded.joinpath(*root_relative.parts)
        if not payload_root.is_dir() or payload_root.is_symlink():
            raise ToolArtifactError(f"verified archive content root is missing: {content_root}")

        if target.exists():
            target.replace(backup)
        payload_root.replace(target)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(workspace, ignore_errors=True)
        return target
    except Exception:
        if backup.exists() and not target.exists():
            try:
                backup.replace(target)
            except OSError:
                pass
        shutil.rmtree(workspace, ignore_errors=True)
        raise


def run_tool_install_layout_self_test() -> None:
    import hashlib
    import tempfile
    import zipfile

    from tool_artifacts import runtime_arch, runtime_platform

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        build_name = "ffmpeg-N-126313-g1ae4048218-win64-gpl"
        archive_path = root / f"{build_name}.zip"
        binary = "ffmpeg.exe" if runtime_platform() == "windows" else "ffmpeg"
        with zipfile.ZipFile(archive_path, "w") as archive_file:
            archive_file.writestr(f"{build_name}/bin/{binary}", b"ffmpeg")
            archive_file.writestr(f"{build_name}/LICENSE.txt", b"license")
        artifact = ToolArtifact(
            tool="ffmpeg",
            version="N-126313-g1ae4048218",
            platform=runtime_platform(),
            arch=runtime_arch(),
            url=f"https://downloads.example.com/{archive_path.name}",
            sha256=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            archive="zip",
        )
        target = root / "runtime" / "tools" / "ffmpeg"
        installed = install_rooted_verified_artifact(
            artifact,
            archive_path,
            target,
            content_root=archive_root_from_asset_name(archive_path.name, "zip"),
            required_files=(f"bin/{binary}", "LICENSE.txt"),
            validator=lambda payload: (payload / "bin" / binary).read_bytes() == b"ffmpeg",
        )
        assert (installed / "bin" / binary).read_bytes() == b"ffmpeg"
        assert not (installed / build_name).exists()
