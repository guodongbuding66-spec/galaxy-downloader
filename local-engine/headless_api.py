from __future__ import annotations

from http.server import ThreadingHTTPServer

import headless_api_base as _base
from course_attachment_download_service import CourseAttachmentDownloadService
from course_download_coordinator import CourseDownloadCoordinator
from headless_ai_api import HeadlessAiApi
from headless_asr_api import HeadlessAsrApi
from headless_asr_http import HeadlessAsrHttpMixin
from headless_browser_cookies import install_headless_browser_cookie_support
from headless_course_attachments_http import HeadlessCourseAttachmentsHttpMixin
from headless_course_metadata_tracking import install_headless_course_metadata_tracking
from headless_course_providers_http import HeadlessCourseProvidersHttpMixin
from headless_learning_media_http import HeadlessLearningMediaHttpMixin
from headless_learning_resume_http import HeadlessLearningResumeHttpMixin
from headless_learning_structure import install_headless_learning_structure
from headless_output_tracking import install_headless_output_tracking
from headless_plugin_api import HeadlessPluginApi
from headless_plugin_http import HeadlessPluginHttpMixin
from headless_qwen3_asr_api import Qwen3HeadlessAsrApi
from headless_settings_http import HeadlessSettingsHttpMixin
from headless_transfer_api import HeadlessTransferApi
from headless_transfer_http import HeadlessTransferHttpMixin
from headless_udemy_attachment_inventory import install_headless_udemy_attachment_inventory
from headless_web_dashboard import HeadlessWebDashboardMixin
from headless_whisperx_api import HeadlessWhisperXApi
from headless_whisperx_http import HeadlessWhisperXHttpMixin

# Compose bounded browser authentication first, final-file tracking second,
# provider-specific safe inventory capture third, and persistent metadata capture
# last. No layer exposes browser credentials, signed attachment URLs, or absolute
# output paths publicly.
install_headless_browser_cookie_support()
install_headless_output_tracking()
install_headless_udemy_attachment_inventory()
install_headless_course_metadata_tracking()
install_headless_learning_structure()

# Publish the legacy handler before importing headless_ai_http. That module
# imports GalaxyApiRequestHandler from headless_api, so exposing this alias
# first keeps the dependency acyclic during module initialization.
GalaxyApiRequestHandler = _base.GalaxyApiRequestHandler

from headless_ai_http import AiGalaxyApiRequestHandler, AiGalaxyApiServer  # noqa: E402,F401


class GalaxyApiRequestHandler(
    HeadlessWebDashboardMixin,
    HeadlessCourseAttachmentsHttpMixin,
    HeadlessLearningMediaHttpMixin,
    HeadlessLearningResumeHttpMixin,
    HeadlessCourseProvidersHttpMixin,
    HeadlessSettingsHttpMixin,
    HeadlessTransferHttpMixin,
    HeadlessPluginHttpMixin,
    HeadlessWhisperXHttpMixin,
    HeadlessAsrHttpMixin,
    AiGalaxyApiRequestHandler,
):
    """Production request chain with Dashboard, Learning extensions and bounded service APIs."""


class GalaxyApiServer(ThreadingHTTPServer):
    """Production Galaxy server with Course coordination and attachment downloads enabled."""

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
        coordinator: CourseDownloadCoordinator | None = None
        attachment_downloads: CourseAttachmentDownloadService | None = None
        self._owns_transfer_api = transfer_api is None
        self._transfer_closed = False
        self._course_download_coordinator_closed = False
        self._course_attachment_download_service_closed = False
        try:
            asr = asr_api or Qwen3HeadlessAsrApi(runtime.download_root)
            shared_asr_context = getattr(asr, "context", None)
            whisperx = whisperx_api or HeadlessWhisperXApi(runtime.download_root, context=shared_asr_context)
            plugins = plugin_api or HeadlessPluginApi(runtime.download_root)
            transfer = transfer_api or HeadlessTransferApi(runtime.download_root)
            if learning_api is not None:
                coordinator = CourseDownloadCoordinator(runtime, learning_api)
                attachment_downloads = CourseAttachmentDownloadService(learning_api.context)
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
            self.course_download_coordinator = coordinator
            self.course_attachment_download_service = attachment_downloads
            super().__init__(address, GalaxyApiRequestHandler)
        except Exception:
            if attachment_downloads is not None:
                attachment_downloads.close()
            if coordinator is not None:
                coordinator.close()
            if self._owns_transfer_api and transfer is not None:
                transfer.shutdown()
            if self._owns_ai_api:
                ai.shutdown()
            raise

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            attachment_downloads = getattr(self, "course_attachment_download_service", None)
            if attachment_downloads is not None and not self._course_attachment_download_service_closed:
                self._course_attachment_download_service_closed = True
                attachment_downloads.close()
            coordinator = getattr(self, "course_download_coordinator", None)
            if coordinator is not None and not self._course_download_coordinator_closed:
                self._course_download_coordinator_closed = True
                coordinator.close()
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
