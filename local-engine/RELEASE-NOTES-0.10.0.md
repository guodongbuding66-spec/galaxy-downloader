# Galaxy Local Engine 0.10.0

0.10.0 focuses on the desktop/web workbench and advanced download controls. It intentionally keeps the stable 0.9.0 parsing, authentication and core download routing unchanged.

## Desktop workbench

- Larger dark Galaxy/SparkDownloader workbench with a clearer current-job hierarchy.
- Real-time progress, speed, ETA and downloaded-size metrics.
- Queue rail now supports removing individual waiting jobs and clearing the waiting queue without cancelling the active job.
- Runtime readiness chips for FFmpeg, yt-dlp and optional aria2c.
- One-click diagnostic summary copied to the clipboard.
- Direct SparkDownloader shortcut and explicit user-triggered update checking.

## Advanced download UI

- Quick presets: Standard, Course/Podcast, Remove Sponsors and Fast.
- Video segment start/end controls and chapter splitting remain opt-in.
- Explicit manual/automatic/both subtitle source selection and subtitle/audio language controls.
- Exposes all SponsorBlock categories already supported by the 0.9 backend: sponsor, self-promotion, interaction, intro, outro, preview/recap, off-topic music and filler.
- Optional aria2c acceleration remains subordinate to yt-dlp and is only enabled when aria2c is detected.
- Reset-to-default and save-default actions are explicit; current active jobs are never changed by saving preferences.

## Web UI

- Reorganized advanced controls into a denser progressive workbench.
- Shows an active-option count.
- Adds the same quick presets and full SponsorBlock category set as the desktop UI.
- All advanced options remain disabled by default.

## Compatibility

- Core media-first parsing, Yuanbao/browser authentication fallback and queue/bridge behavior come directly from the validated 0.9.0 line.
- Download Archive remains optional and off by default.
- The website pins the exact `local-engine-v0.10.0` release asset instead of using `releases/latest`.
