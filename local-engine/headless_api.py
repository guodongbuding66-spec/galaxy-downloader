from __future__ import annotations

import headless_api_base as _base
from headless_ai_api import HeadlessAiApi

# Publish the legacy handler before importing headless_ai_http. That module
# imports GalaxyApiRequestHandler from headless_api, so exposing this alias
# first keeps the dependency acyclic during module initialization.
GalaxyApiRequestHandler = _base.GalaxyApiRequestHandler

from headless_ai_http import AiGalaxyApiRequestHandler, AiGalaxyApiServer  # noqa: E402

GalaxyApiRequestHandler = AiGalaxyApiRequestHandler


class GalaxyApiServer(AiGalaxyApiServer):
    """Production Galaxy server with the AI workspace enabled.

    Existing Media/Transcript/Subscription/Reader/Learning/Music routing is
    preserved in headless_api_base.py. This wrapper only owns AI adapter
    creation and lifecycle, keeping the production integration reversible.
    """

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
    ) -> None:
        ai = ai_api or HeadlessAiApi(runtime.download_root)
        self._owns_ai_api = ai_api is None
        self._ai_closed = False
        try:
            super().__init__(
                address,
                runtime,
                auth_token,
                bound_host,
                media_api,
                ai_api=ai,
                transcript_api=transcript_api,
                subscription_api=subscription_api,
                reader_api=reader_api,
                learning_api=learning_api,
                music_api=music_api,
            )
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
# Patch only that extension point so CLI, Docker/NAS and existing callers keep
# the established startup behavior while receiving /v1/ai/* in production.
_base.GalaxyApiRequestHandler = GalaxyApiRequestHandler
_base.GalaxyApiServer = GalaxyApiServer

run_server = _base.run_server
main = _base.main


def __getattr__(name: str):
    """Forward legacy module attributes for compatibility."""

    return getattr(_base, name)


if __name__ == "__main__":
    raise SystemExit(main())
