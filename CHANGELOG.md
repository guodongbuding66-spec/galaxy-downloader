# Changelog

All notable changes to Galaxy Downloader are documented here. The in-app changelog remains the user-facing release history.

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
