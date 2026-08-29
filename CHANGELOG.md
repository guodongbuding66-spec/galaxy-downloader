# Changelog

All notable changes to Galaxy Downloader are documented here. The in-app changelog remains the user-facing release history.

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
