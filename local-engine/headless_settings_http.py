from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from headless_service import _loopback_host


_CONFIGURATION_ENVIRONMENT = (
    {"name": "GALAXY_HEADLESS_HOST", "secret": False, "restartRequired": True},
    {"name": "GALAXY_HEADLESS_PORT", "secret": False, "restartRequired": True},
    {"name": "GALAXY_DOWNLOAD_DIR", "secret": True, "restartRequired": True},
    {"name": "GALAXY_HEADLESS_TOKEN", "secret": True, "restartRequired": True},
)


def _feature_flags(server: object) -> dict[str, bool]:
    return {
        "downloads": True,
        "media": getattr(server, "media_api", None) is not None,
        "transcript": getattr(server, "transcript_api", None) is not None,
        "subscriptions": getattr(server, "subscription_api", None) is not None,
        "reader": getattr(server, "reader_api", None) is not None,
        "learning": getattr(server, "learning_api", None) is not None,
        "music": getattr(server, "music_api", None) is not None,
        "ai": getattr(server, "ai_api", None) is not None,
        "asr": getattr(server, "asr_api", None) is not None,
        "whisperx": getattr(server, "whisperx_api", None) is not None,
        "plugins": getattr(server, "plugin_api", None) is not None,
        "transfer": getattr(server, "transfer_api", None) is not None,
        "webDashboard": True,
    }


def build_runtime_settings(
    *,
    bound_host: str,
    auth_token_configured: bool,
    queue_capacity: object,
    features: dict[str, bool],
) -> dict[str, Any]:
    loopback = _loopback_host(bound_host)
    try:
        capacity = max(1, min(int(queue_capacity), 10_000))
    except (TypeError, ValueError):
        capacity = 1
    return {
        "protocol": 2,
        "bindingMode": "loopback" if loopback else "remote",
        "remoteAccess": not loopback,
        "authentication": {
            "mode": "bearer" if auth_token_configured else "none",
            "configured": bool(auth_token_configured),
        },
        "queue": {"capacity": capacity},
        "configuration": {
            "writable": False,
            "mode": "environment-or-cli",
            "environment": [dict(item) for item in _CONFIGURATION_ENVIRONMENT],
        },
        "features": {key: bool(value) for key, value in sorted(features.items())},
    }


class HeadlessSettingsHttpMixin:
    """Expose read-only NAS runtime configuration without leaking secrets or local paths."""

    def do_GET(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/v1/settings":
            super().do_GET()
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return

        status = self.runtime.status()
        settings = build_runtime_settings(
            bound_host=self.bound_host,
            auth_token_configured=bool(self.auth_token),
            queue_capacity=status.get("capacity"),
            features=_feature_flags(self.server),
        )
        self._json(200, {"ok": True, "settings": settings})
