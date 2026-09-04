from __future__ import annotations

from urllib.parse import urlsplit

import headless_api_base as _base
from headless_ai_api import HeadlessAiApi
from headless_ai_http import handle_ai_get, handle_ai_post

_BaseGalaxyApiRequestHandler = _base.GalaxyApiRequestHandler
_BaseGalaxyApiServer = _base.GalaxyApiServer


class GalaxyApiRequestHandler(_BaseGalaxyApiRequestHandler):
    """Thin compatibility layer that adds `/v1/ai/*` before legacy routing.

    Every non-AI request is delegated to the unchanged handler stored in
    `headless_api_base.py`. Keeping the extension here avoids another large
    monolithic routing block and makes the AI surface independently reversible.
    """

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if handle_ai_get(self, parsed):
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if handle_ai_post(self, parsed):
            return
        super().do_POST()


class GalaxyApiServer(_BaseGalaxyApiServer):
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
        self.ai_api = ai_api or HeadlessAiApi(runtime.download_root)
        self._owns_ai_api = ai_api is None
        try:
            super().__init__(
                address,
                runtime,
                auth_token,
                bound_host,
                media_api,
                transcript_api,
                subscription_api,
                reader_api,
                learning_api,
                music_api,
            )
        except Exception:
            if self._owns_ai_api:
                self.ai_api.shutdown()
            raise

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            if self._owns_ai_api:
                self.ai_api.shutdown()


# The legacy run_server/main functions resolve these globals at call time. Patch
# only the two extension points so CLI, Docker/NAS and existing callers retain
# their established startup behavior while receiving the AI surface.
_base.GalaxyApiRequestHandler = GalaxyApiRequestHandler
_base.GalaxyApiServer = GalaxyApiServer

run_server = _base.run_server
main = _base.main


def __getattr__(name: str):
    """Forward legacy module attributes without wildcard namespace pollution."""

    return getattr(_base, name)


if __name__ == "__main__":
    raise SystemExit(main())
