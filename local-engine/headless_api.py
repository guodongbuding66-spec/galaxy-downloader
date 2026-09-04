from __future__ import annotations

from http.server import ThreadingHTTPServer

import headless_api_base as _base
from headless_ai_api import HeadlessAiApi
from headless_asr_api import HeadlessAsrApi
from headless_asr_http import HeadlessAsrHttpMixin
from headless_parakeet_asr_api import ParakeetHeadlessAsrApi
from headless_plugin_api import HeadlessPluginApi
from headless_plugin_http import HeadlessPluginHttpMixin
from headless_transfer_api import HeadlessTransferApi
from headless_transfer_http import HeadlessTransferHttpMixin
from headless_whisperx_api import HeadlessWhisperXApi
from headless_whisperx_http import HeadlessWhisperXHttpMixin

# Publish the legacy handler before importing headless_ai_http. That module
# imports GalaxyApiRequestHandler from headless_api, so exposing this alias
# first keeps the dependency acyclic during module initialization.
GalaxyApiRequestHandler = _base.GalaxyApiRequestHandler

from headless_ai_http import AiGalaxyApiRequestHandler, AiGalaxyApiServer  # noqa: E402,F401


class GalaxyApiRequestHandler(
    HeadlessTransferHttpMixin,
    HeadlessPluginHttpMixin,
    HeadlessWhisperXHttpMixin,
    HeadlessAsrHttpMixin,
    AiGalaxyApiRequestHandler,
):
    """Production request chain: Transfer -> Plugins -> WhisperX -> ASR -> AI -> Galaxy."""


class GalaxyApiServer(ThreadingHTTPServer):
    """Production Galaxy server with Transfer, Plugin, AI and ASR enabled."""

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
        whisperx_api: HeadlessWhisperXApi | None = None,
        plugin_api: HeadlessPluginApi | None = None,
        transfer_api: HeadlessTransferApi | None = None,
    ) -> None:
        ai = ai_api or HeadlessAiApi(runtime.download_root)
        self._owns_ai_api = ai_api is None
        self._ai_closed = False
        self._owns_asr_api = asr_api is None
        transfer: HeadlessTransferApi | None = None
        self._owns_transfer_api = transfer_api is None
        self._transfer_closed = False
        try:
            asr = asr_api or ParakeetHeadlessAsrApi(runtime.download_root)
            shared_asr_context = getattr(asr, "context", None)
            whisperx = whisperx_api or HeadlessWhisperXApi(runtime.download_root, context=shared_asr_context)
            plugins = plugin_api or HeadlessPluginApi(runtime.download_root)
            transfer = transfer_api or HeadlessTransferApi(runtime.download_root)
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
            self.whisperx_api = whisperx
            self.plugin_api = plugins
            self.transfer_api = transfer
            super().__init__(address, GalaxyApiRequestHandler)
        except Exception:
            if self._owns_transfer_api and transfer is not None:
                transfer.shutdown()
            if self._owns_ai_api:
                ai.shutdown()
            raise

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            if self._owns_transfer_api and not self._transfer_closed:
                self._transfer_closed = True
                self.transfer_api.shutdown()
            if self._owns_ai_api and not self._ai_closed:
                self._ai_closed = True
                self.ai_api.shutdown()


# The legacy run_server/main functions resolve GalaxyApiServer at call time.
# Patching only these extension points preserves the established startup path.
_base.GalaxyApiRequestHandler = GalaxyApiRequestHandler
_base.GalaxyApiServer = GalaxyApiServer

run_server = _base.run_server
main = _base.main


def __getattr__(name: str):
    """Forward legacy module attributes for compatibility."""

    return getattr(_base, name)


if __name__ == "__main__":
    raise SystemExit(main())
