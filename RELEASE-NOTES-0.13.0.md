# Galaxy Local Engine 0.13.0

## Network controls

- Adds three retry profiles: Standard, Resilient, and Fast-fail.
- Standard remains the default and preserves the 0.12 transport settings: 10 download retries, 10 fragment retries, 5 extractor retries, and a 30 second socket timeout.
- Adds concurrent fragment controls: 1 / 2 / 4 / 8 / 16. The default remains 4.
- Adds an optional 1–100 Mbps download speed cap. Unlimited remains the default.
- The same network preferences are applied to both the bundled external yt-dlp path and the embedded fallback path.

## Runtime health

- Shows remaining space for the portable `downloads` volume in the desktop workbench.
- Adds a configurable low-space warning threshold. This is warning-only and never cancels, skips, or blocks downloads.
- Adds an optional completion/failure alert using the Windows system sound and taskbar flash. It is off by default.

## Privacy-safe diagnostics

- Adds an optional local diagnostic log at `state/engine.log`; logging is off by default.
- Logged URLs drop credentials, query strings and fragments before they are written.
- Common token, cookie, session, password and authorization fields receive a second redaction pass.
- Adds a log viewer with search, copy, clear and open-folder actions.
- Log storage can be capped between 128 KB and 2 MB.

## UI

- Expands the workbench settings center with network, retry, runtime-health and diagnostics sections.
- Adds a persistent free-space indicator and a direct Diagnostics button in the desktop header.
- Current-job details now show the active retry profile, fragment concurrency, and speed cap.

## Regression boundary

The 0.13 work intentionally leaves the validated media-first parser order, Yuanbao browser-auth reuse, format selection, FFmpeg path, image/document downloaders, queue semantics, Download Archive behavior, safe shutdown and exact-version website pinning unchanged by default.
