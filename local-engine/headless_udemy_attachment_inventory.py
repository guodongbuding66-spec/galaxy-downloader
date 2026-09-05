from __future__ import annotations

import re
import threading
import uuid
from collections import OrderedDict
from typing import Any

import headless_service as _service
from course_attachments import CourseAttachmentError, normalize_attachment_inventory
from yt_dlp.extractor.udemy import UdemyCourseIE, UdemyIE
from yt_dlp.utils import smuggle_url, unsmuggle_url

_MAX_PENDING_INVENTORIES = 5_000
_LECTURE_RE = re.compile(r"/lecture/(\d+)(?:[/?#]|$)")
_LOCK = threading.RLock()
_PENDING: OrderedDict[str, dict[str, Any]] = OrderedDict()


def _enabled(extractor) -> bool:
    downloader = getattr(extractor, "_downloader", None)
    params = getattr(downloader, "params", None)
    return isinstance(params, dict) and bool(params.get("_galaxy_course_attachment_inventory"))


def _provider_asset_id(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or not raw.isdigit() or len(raw) > 40:
        return ""
    return f"udemy:asset:{raw}"


def _safe_inventory(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    candidates: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        provider_attachment_id = _provider_asset_id(raw.get("id"))
        if not provider_attachment_id:
            continue
        candidates.append(
            {
                "providerAttachmentId": provider_attachment_id,
                "title": str(raw.get("title") or ""),
                "fileName": str(raw.get("filename") or raw.get("file_name") or ""),
                "assetType": str(raw.get("asset_type") or raw.get("assetType") or ""),
            }
        )
    try:
        return normalize_attachment_inventory(candidates)
    except CourseAttachmentError:
        return []


def _remember_inventory(provider_lecture_id: str, attachments: list[dict[str, str]]) -> str:
    token = uuid.uuid4().hex
    with _LOCK:
        _PENDING[token] = {
            "provider": "udemy",
            "providerLectureId": provider_lecture_id,
            "attachments": [dict(item) for item in attachments],
        }
        _PENDING.move_to_end(token)
        while len(_PENDING) > _MAX_PENDING_INVENTORIES:
            _PENDING.popitem(last=False)
    return token


def _take_inventory(token: object) -> dict[str, Any] | None:
    clean = str(token or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32}", clean):
        return None
    with _LOCK:
        value = _PENDING.pop(clean, None)
    return None if value is None else dict(value)


def install_headless_udemy_attachment_inventory() -> None:
    """Capture safe supplementary-asset metadata from an authorized Udemy course.

    The course curriculum request asks only for attachment identity/title/file
    metadata. It never asks for `download_urls` or `external_url`, so signed URLs
    and provider secrets cannot enter the persistent course metadata pipeline.
    """

    current_options = _service._download_options
    if not getattr(current_options, "_galaxy_udemy_attachment_inventory", False):
        def options_with_attachment_inventory(payload: dict[str, Any], root, progress_hook):
            options = current_options(payload, root, progress_hook)
            if bool(payload.get("includeCourseAttachments", False)):
                options["_galaxy_course_attachment_inventory"] = True
            return options

        options_with_attachment_inventory._galaxy_udemy_attachment_inventory = True  # type: ignore[attr-defined]
        _service._download_options = options_with_attachment_inventory

    current_course_download_json = UdemyCourseIE._download_json
    if not getattr(current_course_download_json, "_galaxy_udemy_attachment_inventory", False):
        def course_download_json_with_inventory(self, url_or_request, *args, **kwargs):
            target = str(getattr(url_or_request, "url", url_or_request) or "")
            capture = _enabled(self) and "/cached-subscriber-curriculum-items" in target
            if capture:
                kwargs = dict(kwargs)
                query = dict(kwargs.get("query") or {})
                query["fields[lecture]"] = "title,asset,supplementary_assets"
                query["fields[asset]"] = "id,title,filename,asset_type"
                kwargs["query"] = query
            response = current_course_download_json(self, url_or_request, *args, **kwargs)
            if capture and isinstance(response, dict):
                inventory: dict[str, list[dict[str, str]]] = {}
                results = response.get("results")
                if isinstance(results, list):
                    for entry in results:
                        if not isinstance(entry, dict) or entry.get("_class") != "lecture":
                            continue
                        lecture_id = str(entry.get("id") or "").strip()
                        if not lecture_id.isdigit() or len(lecture_id) > 40:
                            continue
                        inventory[lecture_id] = _safe_inventory(entry.get("supplementary_assets"))
                self._galaxy_course_attachment_inventory = inventory
            return response

        course_download_json_with_inventory._galaxy_udemy_attachment_inventory = True  # type: ignore[attr-defined]
        UdemyCourseIE._download_json = course_download_json_with_inventory

    current_course_extract = UdemyCourseIE._real_extract
    if not getattr(current_course_extract, "_galaxy_udemy_attachment_inventory", False):
        def course_extract_with_inventory(self, url):
            if _enabled(self):
                self._galaxy_course_attachment_inventory = {}
            result = current_course_extract(self, url)
            if not _enabled(self) or not isinstance(result, dict):
                return result
            inventory = getattr(self, "_galaxy_course_attachment_inventory", None)
            entries = result.get("entries")
            if not isinstance(inventory, dict) or not isinstance(entries, list):
                return result

            updated_entries: list[Any] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    updated_entries.append(entry)
                    continue
                rendered_url = str(entry.get("url") or "")
                match = _LECTURE_RE.search(rendered_url)
                lecture_id = match.group(1) if match else ""
                if not lecture_id or lecture_id not in inventory:
                    updated_entries.append(entry)
                    continue
                provider_lecture_id = f"udemy:lecture:{lecture_id}"
                token = _remember_inventory(provider_lecture_id, inventory[lecture_id])
                plain_url, data = unsmuggle_url(rendered_url, {})
                smuggled = dict(data or {})
                smuggled["galaxy_attachment_inventory_id"] = token
                enriched = dict(entry)
                enriched["url"] = smuggle_url(plain_url, smuggled)
                updated_entries.append(enriched)
            values = dict(result)
            values["entries"] = updated_entries
            return values

        course_extract_with_inventory._galaxy_udemy_attachment_inventory = True  # type: ignore[attr-defined]
        UdemyCourseIE._real_extract = course_extract_with_inventory

    current_lecture_extract = UdemyIE._real_extract
    if not getattr(current_lecture_extract, "_galaxy_udemy_attachment_inventory", False):
        def lecture_extract_with_inventory(self, url):
            _plain_url, data = unsmuggle_url(url, {})
            inventory = _take_inventory((data or {}).get("galaxy_attachment_inventory_id"))
            result = current_lecture_extract(self, url)
            if inventory is None or not isinstance(result, dict):
                return result
            values = dict(result)
            values["_galaxyCourseAttachmentInventory"] = inventory
            return values

        lecture_extract_with_inventory._galaxy_udemy_attachment_inventory = True  # type: ignore[attr-defined]
        UdemyIE._real_extract = lecture_extract_with_inventory
