# Galaxy Downloader

Galaxy Downloader is a multi-platform media and rich-document downloader with a browser workbench plus an optional Windows Local Engine for deterministic local downloads, FFmpeg processing, authenticated extraction, original-image downloads, and dynamic document rendering.

## Local Engine 0.8.0

The current website requires **Galaxy Local Engine 0.8.0+**.

Download the Windows package from the website's **Install Local Engine** action. The website pins the package to the exact `local-engine-v0.8.0` release instead of following `releases/latest`, so the downloaded engine always matches the web build's minimum requirement.

### Installation

1. Download `GalaxyLocalEngine-Windows.zip`.
2. Fully extract the ZIP to a permanent folder.
3. Run `install.cmd`.
4. Keep `GalaxyLocalEngine.exe` running while using local parsing/download features.
5. Finished media and downloaded images are stored in the package's `downloads` folder.

The release package is offline-first: verified `yt-dlp.exe`, FFmpeg and FFprobe are already bundled. Installation does not need to download those dependencies from GitHub.

### Download behavior

- The default media job saves one finished file: best video + best audio, merged when required.
- Subtitles and cover embedding are opt-in.
- Thumbnail, info JSON, description, comments and playlist metadata sidecars are disabled by default.
- User/global yt-dlp configuration is ignored so a machine-specific config cannot silently change Galaxy's output policy.
- Collections support **current item**, **entire collection**, and **selected items**.
- A bounded FIFO queue accepts up to 25 waiting media jobs while another job is active.
- The website shows the current queue length/capacity and allows additional jobs to be queued without starting a second engine process.
- **Skip previously downloaded content** is optional and disabled by default. When enabled, yt-dlp uses the Local Engine's `state/download-archive.txt`; the archive state does not pollute the downloads folder.
- Browser cookies are attempted only when an anonymous/public extraction explicitly reports that authentication is required.

### Local Bridge

The website talks to the resident Local Engine over the loopback bridge. Download submissions now expose stable status semantics:

- `202 ACCEPTED` — job started immediately.
- `202 QUEUED` — job added to the FIFO queue.
- `400 BAD_REQUEST` — invalid job/source URL.
- `409 QUEUE_FULL` — the waiting queue reached its configured capacity.
- `503 ENGINE_SHUTTING_DOWN` — the resident engine is closing.
- `504 ENGINE_HANDOFF_TIMEOUT` — the desktop UI thread did not accept/reject the job in time.

The browser client keeps the code and HTTP status and localizes known lifecycle/queue errors instead of parsing English error strings.

## Rich documents and images

The Local Engine document path is:

1. dedicated/platform-aware parser;
2. static HTML, metadata, JSON-LD and hydration-state extraction;
3. authenticated static retry when explicitly required;
4. installed Edge/Chrome CDP dynamic rendering;
5. yt-dlp media fallback.

WeChat article conversion preserves available paragraph order, headings, links, lists, blockquotes, code/pre blocks, tables and inline image positions. ZIP packaging rewrites Markdown image references to the locally saved filenames.

For original-image workflows, the Local Engine supports direct local downloads, bounded retries, cancellation, temporary-file cleanup, disk-space checks, WebP/AVIF conversion where required, and local ZIP packaging. WeChat image handling tries original-size candidates before parsed derivatives where supported by the CDN.

## Playback

The container backend exposes `/api/play` for progressive media preview with single-range forwarding and `206 Content-Range` support. Redirect targets are manually followed and revalidated. Cookie/Authorization headers are not forwarded. Malformed or multi-range requests are rejected. If a provider exposes only separated/DASH streams, the existing merged-download route remains the compatibility fallback.

## Security boundaries

- Local Engine parse/download/protocol/static-document/CDP paths share a fail-closed public HTTP(S) source policy.
- Localhost, local names, private/reserved literal addresses, credential-bearing URLs, IPv6 zone identifiers, mixed public/private DNS answers and unresolved hosts are rejected before local extraction starts.
- Next.js media/document/image relays use the same class of public-URL restrictions and validate redirect hops.
- Cloudflare image/media relays use a Durable Object fixed-window rate limiter rather than per-isolate in-memory counters.
- Image relay bodies are bounded; oversized declared responses are rejected before relay and unknown-length bodies are counted while streaming.
- Media relays accept only one syntactically valid byte range.

### Deployment-level limitation

Application URL validation reduces SSRF exposure but does **not** eliminate DNS-rebinding TOCTOU: DNS can theoretically change between validation and the later network connection. Production container/network policy should independently block private, link-local and metadata-service egress. WAF/rate/bandwidth controls are also recommended as a second layer for public deployments.

## Validation

Pull request validation covers:

- Local Engine command/output policy;
- public-URL policy;
- download archive policy;
- queue behavior and real loopback Bridge status semantics;
- image download/bridge behavior;
- document and CDP policies;
- frontend Vitest/lint/production Next.js build;
- container backend unit tests and production container startup;
- live container/document smoke tests;
- Windows source self-test, real browser CDP test, PyInstaller EXE self-test, offline dependency bundle, installer/custom-protocol lifecycle and artifact packaging;
- the 33-platform live diagnostic workflow.

The exact latest workflow run numbers are tracked in PR #41 while the branch remains under active development.
