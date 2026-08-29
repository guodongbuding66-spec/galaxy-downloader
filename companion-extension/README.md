# Galaxy Downloader Companion

The Companion is the local yt-dlp execution layer for Galaxy Downloader.

## Goal

Media bytes and post-processing should stay on the user's device. The hosted Galaxy web app provides UI and compatibility fallbacks; it is not intended to proxy multi-gigabyte media files.

## Architecture

```text
Galaxy web app
  -> window.postMessage protocol
  -> content.js (isolated extension world)
  -> background / local-engine worker
       -> Pyodide
       -> yt-dlp
       -> browser session/cookies kept inside the extension
       -> ffmpeg.wasm bridge when yt-dlp requests post-processing
  -> final file saved by the browser
```

This is inspired by the local-first architecture demonstrated by projects such as dlPro and ffmpeg webCLI, but the Galaxy implementation is independent code.

## Security rules

1. Cookies never cross the extension/page boundary. The website can request a media operation; the extension may internally use browser cookies for that target, but raw cookies are never returned to page JavaScript.
2. Cross-site permissions are optional. The extension asks for host access only when a user explicitly enables local downloading for that site.
3. The page bridge accepts only the versioned Galaxy protocol and a small allowlist of methods.
4. Media processing should prefer local Web Workers / WebAssembly. No cloud media-processing service is required.
5. DRM-protected or otherwise inaccessible media is out of scope.

## Current implementation status

### Implemented

- Manifest V3 scaffold
- versioned page <-> extension bridge
- local engine capability probe
- optional host permission model
- cross-origin-isolation capability detection in the web app

### Next

- vendor Pyodide into the extension (no remote executable code)
- load a pinned yt-dlp wheel/source bundle inside a dedicated worker
- patch yt-dlp networking to extension-controlled fetch
- keep target cookies/headers inside the extension
- map yt-dlp format selection to Galaxy's existing quality UI
- bridge yt-dlp ffmpeg/ffprobe calls to Galaxy's ffmpeg.wasm worker
- stream downloads to browser storage / OPFS where available
- expose progress, cancellation, subtitles, cover and final-file output through the existing protocol

## Development install

Until a packaged extension build is added, load `companion-extension/` as an unpacked extension in a Chromium-based browser.

The current scaffold only reports engine capabilities; `media.parse` and `media.download` intentionally return `Local yt-dlp engine is not loaded yet` until the Pyodide worker lands.
