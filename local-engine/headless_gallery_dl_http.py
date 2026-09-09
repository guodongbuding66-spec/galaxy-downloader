from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from headless_gallery_dl_api import HeadlessGalleryDlApi, HeadlessGalleryDlApiError
from headless_service import _safe_detail


def _path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


class HeadlessGalleryDlHttpMixin:
    """Composable authenticated `/v1/gallery-dl/*` routes."""

    @property
    def gallery_dl_api(self) -> HeadlessGalleryDlApi | None:
        return self.server.gallery_dl_api  # type: ignore[attr-defined]

    def _gallery_dl_unavailable(self) -> bool:
        if self.gallery_dl_api is not None:
            return False
        self._json(  # type: ignore[attr-defined]
            503,
            {"ok": False, "error": "gallery-dl api is unavailable", "code": "GALLERY_DL_API_UNAVAILABLE"},
        )
        return True

    def _gallery_dl_error(self, exc: HeadlessGalleryDlApiError) -> None:
        self._json(  # type: ignore[attr-defined]
            exc.status,
            {"ok": False, "error": _safe_detail(exc), "code": exc.code},
        )

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)  # type: ignore[attr-defined]
        path = parsed.path
        if not path.startswith("/v1/gallery-dl"):
            super().do_GET()  # type: ignore[misc]
            return
        if not self._authorized():  # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "unauthorized"})  # type: ignore[attr-defined]
            return
        if self._gallery_dl_unavailable():
            return
        try:
            parts = _path_parts(path)
            if parts == ["v1", "gallery-dl", "status"]:
                self._json(200, {"ok": True, **self.gallery_dl_api.status()})  # type: ignore[union-attr,attr-defined]
                return
            if parts == ["v1", "gallery-dl", "jobs"]:
                values = parse_qs(parsed.query, keep_blank_values=False, max_num_fields=4)
                raw_limit = (values.get("limit") or [""])[0]
                limit = 200 if not raw_limit else int(raw_limit)
                self._json(200, {"ok": True, **self.gallery_dl_api.jobs(limit=limit)})  # type: ignore[union-attr,attr-defined]
                return
            if len(parts) == 4 and parts[:3] == ["v1", "gallery-dl", "jobs"]:
                self._json(200, {"ok": True, **self.gallery_dl_api.job(parts[3])})  # type: ignore[union-attr,attr-defined]
                return
            self._json(404, {"ok": False, "error": "not found"})  # type: ignore[attr-defined]
        except HeadlessGalleryDlApiError as exc:
            self._gallery_dl_error(exc)
        except (TypeError, ValueError):
            self._json(  # type: ignore[attr-defined]
                400,
                {"ok": False, "error": "invalid gallery-dl request", "code": "GALLERY_DL_INVALID_REQUEST"},
            )
        except Exception:
            self._json(502, {"ok": False, "error": "gallery-dl request failed"})  # type: ignore[attr-defined]

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path  # type: ignore[attr-defined]
        if not path.startswith("/v1/gallery-dl"):
            super().do_POST()  # type: ignore[misc]
            return
        if not self._authorized():  # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "unauthorized"})  # type: ignore[attr-defined]
            return
        if self._gallery_dl_unavailable():
            return
        try:
            parts = _path_parts(path)
            if parts == ["v1", "gallery-dl", "jobs"]:
                result = self.gallery_dl_api.submit(self._read_json())  # type: ignore[union-attr,attr-defined]
                self._json(201, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if (
                len(parts) == 5
                and parts[:3] == ["v1", "gallery-dl", "jobs"]
                and parts[4] in {"cancel", "retry"}
            ):
                result = self.gallery_dl_api.action(parts[3], parts[4])  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            self._json(404, {"ok": False, "error": "not found"})  # type: ignore[attr-defined]
        except HeadlessGalleryDlApiError as exc:
            self._gallery_dl_error(exc)
        except ValueError:
            self._json(  # type: ignore[attr-defined]
                400,
                {"ok": False, "error": "invalid gallery-dl request", "code": "GALLERY_DL_INVALID_REQUEST"},
            )
        except Exception:
            self._json(502, {"ok": False, "error": "gallery-dl request failed"})  # type: ignore[attr-defined]
