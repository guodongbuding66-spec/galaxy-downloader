from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _platform_from_source(value: object) -> str | None:
    source = str(value or "").strip()
    if not source:
        return None
    try:
        host = (urlparse(source).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    mappings = (
        (("xiaohongshu.com", "xhscdn.com"), "xiaohongshu"),
        (("douyin.com", "iesdouyin.com"), "douyin"),
        (("tiktok.com",), "tiktok"),
        (("instagram.com",), "instagram"),
        (("weibo.com", "weibo.cn"), "weibo"),
        (("weixin.qq.com", "qq.com"), "wechat"),
        (("pinterest.com", "pinimg.com"), "pinterest"),
        (("twitter.com", "x.com"), "x"),
        (("bilibili.com", "b23.tv"), "bilibili"),
    )
    for suffixes, platform in mappings:
        if any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes):
            return platform
    return host or None


def _metadata(payload: dict[str, Any], archive_path: Path) -> dict[str, Any]:
    images = [str(value or "").strip() for value in payload.get("images", []) if str(value or "").strip()]
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = [
            name
            for name in archive.namelist()
            if not name.lower().endswith((".txt", ".md", "metadata.json")) and not name.endswith("/")
        ]
    file_map = [
        {"originalImageUrl": source, "localFile": names[index] if index < len(names) else None}
        for index, source in enumerate(images)
    ]
    platform = str(payload.get("platform") or "").strip() or _platform_from_source(payload.get("sourceUrl"))
    return {
        "schemaVersion": 1,
        "title": str(payload.get("title") or "").strip() or None,
        "author": str(payload.get("author") or "").strip() or None,
        "publishedAt": str(payload.get("publishedAt") or "").strip() or None,
        "sourceUrl": str(payload.get("sourceUrl") or "").strip() or None,
        "platform": platform,
        "description": str(payload.get("description") or "").strip() or None,
        "archiveFormat": str(payload.get("archiveFormat") or "zip").strip().lower(),
        "images": file_map,
    }


def install_image_archive_policy(image_download_module):
    """Append metadata.json to packaged image archives and optionally emit CBZ.

    CBZ deliberately uses the same stored ZIP payload as the existing image
    archive path; only the extension changes. This keeps ordering and original
    files intact while making comic/long-image readers recognize the package.
    """
    if getattr(image_download_module, "_galaxy_image_archive_policy_installed", False):
        return

    original_run = image_download_module._run_image_job

    def run_image_job(payload: dict[str, Any]) -> None:
        archive_format = str(payload.get("archiveFormat") or "zip").strip().lower()
        if archive_format not in {"zip", "cbz"}:
            archive_format = "zip"
        next_payload = dict(payload)
        if archive_format == "cbz":
            next_payload["package"] = True
        next_payload["archiveFormat"] = archive_format

        original_run(next_payload)
        state = image_download_module.image_job_status()
        if state.get("status") != "Completed":
            return
        raw_path = str(state.get("lastPath") or "").strip()
        if not raw_path:
            return
        archive_path = Path(raw_path)
        if not archive_path.exists() or archive_path.suffix.lower() != ".zip":
            return

        try:
            metadata = _metadata(next_payload, archive_path)
            with zipfile.ZipFile(archive_path, "a", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr(
                    "metadata.json",
                    json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
                )
            final_path = archive_path
            if archive_format == "cbz":
                candidate = archive_path.with_suffix(".cbz")
                suffix = 2
                while candidate.exists():
                    candidate = archive_path.with_name(f"{archive_path.stem}-{suffix}.cbz")
                    suffix += 1
                archive_path.replace(candidate)
                final_path = candidate
            image_download_module._set_state(
                lastPath=str(final_path),
                detail=f"Saved to {final_path}",
            )
        except Exception as exc:  # noqa: BLE001
            # The images themselves have already been saved. Preserve the archive
            # and surface a metadata warning rather than deleting user data.
            image_download_module._set_state(
                detail=f"Saved archive, but metadata export failed: {exc}",
            )

    image_download_module._run_image_job = run_image_job
    image_download_module._galaxy_image_archive_policy_installed = True
