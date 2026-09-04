from __future__ import annotations

from http.server import ThreadingHTTPServer

import headless_api_base as _base
from headless_ai_api import HeadlessAiApi
from headless_asr_api import HeadlessAsrApi
from headless_asr_http import HeadlessAsrHttpMixin
from headless_plugin_api import HeadlessPluginApi
from headless_plugin_http import HeadlessPluginHttpMixin

# Publish the legacy handler before importing headless_ai_http. That module
# imports GalaxyApiRequestHandler from headless_api, so exposing this alias
# first keeps the dependency acyclic during module initialization.
GalaxyApiRequestHandler = _base.GalaxyApiRequestHandler

from headless_ai_http import AiGalaxyApiRequestHandler, AiGalaxyApiServer  # noqa: E402,F401


class GalaxyApiRequestHandler(
    HeadlessPluginHttpMixin,
    HeadlessAsrHttpMixin,
    AiGalaxyApiRequestHandler,
):
    """Production request chain: Plugins -> ASR -> AI -> existing workspaces."""


class GalaxyApiServer(ThreadingHTTPServer):
    """Production Galaxy server with Plugin, AI and ASR workspaces enabled.

    Existing Media/Transcript/Subscription/Reader/Learning/Music routing stays
    in `headless_api_base.py`. Plugin management, AI and ASR are layered on the
    same listener so CLI, Docker/NAS, and direct embedders keep one API surface.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address,
        runtime,
        auth_token: str,
        bound_host: str,
        media_api,
        transcript_api=None,
        subscription_api=None,
        reader_api=None,
        learning_api=None,
        music_api=None,
        ai_api: HeadlessAiApi | None = None,
        asr_api: HeadlessAsrApi | None = None,
        plugin_api: HeadlessPluginApi | None = None,
    ) -> None:
        ai = ai_api or HeadlessAiApi(runtime.download_root)
        self._owns_ai_api = ai_api is None
        self._ai_closed = False
        try:
            asr = asr_api or HeadlessAsrApi(runtime.download_root)
            plugins = plugin_api or HeadlessPluginApi(runtime.download_root)
            self.runtime = runtime
            self.auth_token = auth_token
            self.bound_host = bound_host
            self.media_api = media_api
            self.transcript_api = transcript_api
            self.subscription_api = subscription_api
            self.reader_api = reader_api
            self.learning_api = learning_api
            self.music_api = music_api
            self.ai_api = ai
            self.asr_api = asr
            self.plugin_api = plugins
            super().__init__(address, GalaxyApiRequestHandler)
        except Exception:
            if self._owns_ai_api:
                ai.shutdown()
            raise

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            if self._owns_ai_api and not self._ai_closed:
                self._ai_closed = True
                self.ai_api.shutdown()


# The legacy run_server/main functions resolve GalaxyApiServer at call time.
# Patching only these extension points preserves the established startup path
# while enabling /v1/plugins/*, /v1/ai/* and /v1/asr/* in production.
_base.GalaxyApiRequestHandler = GalaxyApiRequestHandler
_base.GalaxyApiServer = GalaxyApiServer

run_server = _base.run_server
main = _base.main


def __getattr__(name: str):
    """Forward legacy module attributes for compatibility."""

    return getattr(_base, name)


if __name__ == "__main__":
    raise SystemExit(main())
