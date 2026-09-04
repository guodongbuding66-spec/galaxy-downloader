from __future__ import annotations

from urllib.parse import urlsplit

from headless_plugin_api import HeadlessPluginApi, HeadlessPluginApiError
from headless_service import HeadlessServiceError, _safe_detail


def _path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


class HeadlessPluginHttpMixin:
    """Composable `/v1/plugins/*` management routes for Galaxy Headless."""

    @property
    def plugin_api(self) -> HeadlessPluginApi | None:
        return self.server.plugin_api  # type: ignore[attr-defined]

    def _plugin_unavailable(self) -> bool:
        if self.plugin_api is not None:
            return False
        self._json(  # type: ignore[attr-defined]
            503,
            {"ok": False, "error": "plugin api is unavailable", "code": "PLUGIN_UNAVAILABLE"},
        )
        return True

    def _plugin_error(self, exc: HeadlessPluginApiError) -> None:
        self._json(  # type: ignore[attr-defined]
            exc.status,
            {"ok": False, "error": _safe_detail(exc), "code": exc.code},
        )

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path  # type: ignore[attr-defined]
        if not path.startswith("/v1/plugins"):
            super().do_GET()  # type: ignore[misc]
            return
        if not self._authorized():  # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "unauthorized"})  # type: ignore[attr-defined]
            return
        if self._plugin_unavailable():
            return
        try:
            parts = _path_parts(path)
            if parts == ["v1", "plugins", "status"]:
                result = self.plugin_api.status()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if parts == ["v1", "plugins", "marketplace"]:
                result = self.plugin_api.marketplace()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if len(parts) == 3 and parts[:2] == ["v1", "plugins"]:
                result = self.plugin_api.plugin_detail(parts[2])  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            self._json(404, {"ok": False, "error": "not found"})  # type: ignore[attr-defined]
        except HeadlessPluginApiError as exc:
            self._plugin_error(exc)
        except ValueError as exc:
            self._json(  # type: ignore[attr-defined]
                400,
                {"ok": False, "error": _safe_detail(exc), "code": "PLUGIN_INVALID_REQUEST"},
            )
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})  # type: ignore[attr-defined]

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path  # type: ignore[attr-defined]
        if not path.startswith("/v1/plugins"):
            super().do_POST()  # type: ignore[misc]
            return
        if not self._authorized():  # type: ignore[attr-defined]
            self._json(401, {"ok": False, "error": "unauthorized"})  # type: ignore[attr-defined]
            return
        if self._plugin_unavailable():
            return
        try:
            parts = _path_parts(path)
            if parts == ["v1", "plugins", "marketplace", "refresh"]:
                result = self.plugin_api.refresh_marketplace()  # type: ignore[union-attr]
                self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                return
            if len(parts) == 4 and parts[:2] == ["v1", "plugins"]:
                plugin_id = parts[2]
                action = parts[3]
                if action == "enable":
                    result = self.plugin_api.set_enabled(plugin_id, True)  # type: ignore[union-attr]
                elif action == "disable":
                    result = self.plugin_api.set_enabled(plugin_id, False)  # type: ignore[union-attr]
                elif action == "install":
                    result = self.plugin_api.install(plugin_id)  # type: ignore[union-attr]
                elif action == "update":
                    result = self.plugin_api.update(plugin_id)  # type: ignore[union-attr]
                elif action == "remove":
                    result = self.plugin_api.remove(plugin_id)  # type: ignore[union-attr]
                else:
                    result = None
                if result is not None:
                    self._json(200, {"ok": True, **result})  # type: ignore[attr-defined]
                    return
            self._json(404, {"ok": False, "error": "not found"})  # type: ignore[attr-defined]
        except HeadlessPluginApiError as exc:
            self._plugin_error(exc)
        except HeadlessServiceError as exc:
            self._json(  # type: ignore[attr-defined]
                400,
                {"ok": False, "error": _safe_detail(exc), "code": "PLUGIN_INVALID_REQUEST"},
            )
        except ValueError as exc:
            self._json(  # type: ignore[attr-defined]
                400,
                {"ok": False, "error": _safe_detail(exc), "code": "PLUGIN_INVALID_REQUEST"},
            )
        except Exception as exc:
            self._json(502, {"ok": False, "error": _safe_detail(exc)})  # type: ignore[attr-defined]
