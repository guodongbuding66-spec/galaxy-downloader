# Changelog

All notable changes to Galaxy Downloader are documented here. The in-app changelog remains the user-facing release history.

## Unreleased — Local Engine 0.8.0

### Local download queue and duplicate control
- Added a bounded FIFO media download queue with up to 25 waiting jobs.
- The web workbench can submit new Local Engine jobs while another job is active and shows queue length/capacity.
- Added optional **Skip previously downloaded content** using the Local Engine's own `state/download-archive.txt`. The option is off by default.
- Closing the Local Engine safely cancels active media/image work and clears waiting jobs before the desktop process exits.

### Version and Bridge reliability
- Website and GitHub backup downloads are pinned to the exact `local-engine-v0.8.0` release asset rather than `releases/latest`.
- Local Bridge download submission now returns stable result codes and HTTP semantics: `ACCEPTED`, `QUEUED`, `BAD_REQUEST`, `QUEUE_FULL`, `ENGINE_SHUTTING_DOWN`, and `ENGINE_HANDOFF_TIMEOUT`.
- The web client preserves Bridge status/code and localizes queue/lifecycle errors instead of interpreting backend English strings.
- Windows/Release validation now executes archive, queue, image and real loopback Bridge policy tests in addition to source/EXE self-tests and installer lifecycle checks.

### Image and network hardening
- Image downloads gained bounded retry/backoff, cancellation, `.part` cleanup, disk-space checks, local WebP/AVIF conversion safeguards, and ZIP-space reservation.
- Playback redirect targets are revalidated hop-by-hop and malformed/multipart/oversized Range requests are rejected.
- Cloudflare media/image relay traffic is protected by Durable Object rate limiting and bounded image response sizes.
- Application URL validation blocks obvious localhost/private/reserved destinations; deployment egress restrictions remain recommended because application validation cannot eliminate DNS-rebinding TOCTOU.

## 6.4.0 — 2026-08-29

### One finished video instead of separate assets
- Reworked Advanced Download into a one-click Finished Video workflow.
- Video quality, audio quality, subtitles and cover are selected before processing.
- The browser fetches the required media tracks, runs the assembly pipeline automatically and downloads one final MP4.
- Standalone video/audio/subtitle/cover downloads are no longer the primary workflow for normal video results.

### Media assembly
- The selected video stream is copied without re-encoding whenever possible, preserving the requested source quality.
- A separately selected audio stream is merged and normalized to AAC for MP4 compatibility.
- Subtitles are embedded as a selectable `mov_text` MP4 subtitle track rather than requiring a separate subtitle file.
- Cover art is embedded into the same MP4 as an attached picture.
- Title and source URL metadata are written into the final file.
- Auxiliary subtitle/cover streams no longer participate in `-shortest`, preventing accidental truncation of the finished video.

### Workflow and UX
- Added a single `Build and download final video` action.
- Added progress for stream resolution, video/audio/subtitle/cover downloads, FFmpeg startup, muxing and final save.
- Added task cancellation.
- Added automatic fallback to parser-provided media streams if a selected-quality resolver endpoint is unavailable.
- HLS browser download remains available as a compatibility fallback.
- Audio-only content and image posts with background audio retain their standalone audio download action.

### Quality assurance
- Added FFmpeg argument tests for video + audio + subtitle + cover output and muxed-audio fallback.
- Preserved existing image-note background-audio behavior after regression testing.
- Tests, ESLint and the production bundle are validated by CI before production merge.

## 6.3.0 — 2026-08-29

### Download quality
- Added advanced video quality selection with Best available, 8K/4320p, 4K/2160p, 2K/1440p, 1080p, 720p and lower-resolution presets.
- Parser-provided formats are preferred when available, including resolution, FPS, container, codec and file-size information.
- Primary video downloads now request the best available quality again instead of reusing a possibly low-resolution temporary CDN stream.
- Selected-quality requests can pass parser format IDs back to the backend.

### Audio and extra resources
- Added audio-quality selection.
- Added cover/thumbnail downloads.
- Added subtitle and auto-caption downloads when the parser exposes subtitle tracks.
- Added media-information JSON export.
- Added source-URL copy action.

### Parser compatibility
- Added normalization for common parser fields including `formats`, `videoFormats`, `video_formats`, `qualities`, `subtitles`, `captions`, `automatic_captions` and `automaticCaptions`.
- Added per-item quality/subtitle handling for multi-part and collection results.
- Bilibili multi-P downloads now preserve the selected `p` value when requesting a fresh stream.

### Download reliability
- Download resolution now supports both backend response modes: direct media streams and JSON responses that contain a resolved media URL.
- Improved handling of temporary signed URLs, cross-origin media and some 403 download scenarios.
- Kept legacy parse-stat responses backward compatible when total-count data is absent.

### Quality assurance
- Added GitHub Actions CI validation for tests, ESLint and production builds.
- Added tests for quality-option normalization, subtitle normalization and download-resolver response modes.

## 6.2.0 — 2026-08-12
- Browser HLS downloads use a Cloudflare Worker proxy for cross-origin playlists and segments.
- HLS downloads start only after explicit user action; closing the dialog stops an active download.
- Platform directory displays all API-registered platforms.

## 6.1.0 — 2026-07-23
- Added Apple Podcasts support.

For earlier releases, see `src/lib/changelog.json` or the in-app changelog dialog.
