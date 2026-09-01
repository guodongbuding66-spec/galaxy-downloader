# Changelog

## Unreleased

### Galaxy Local Engine 0.8.0

- Added a bounded FIFO media download queue with up to 25 waiting jobs.
- The web workbench can submit new Local Engine jobs while another job is active and shows queue length/capacity.
- Added optional **Skip previously downloaded content** using the Local Engine's own `state/download-archive.txt`. The option is off by default.
- Website and GitHub backup downloads are pinned to the exact `local-engine-v0.8.0` release asset rather than `releases/latest`.
- Local Bridge download submission now returns stable result codes and HTTP semantics: `ACCEPTED`, `QUEUED`, `BAD_REQUEST`, `QUEUE_FULL`, `ENGINE_SHUTTING_DOWN`, and `ENGINE_HANDOFF_TIMEOUT`.
- The web client preserves Bridge status/code and localizes queue/lifecycle errors instead of interpreting backend English strings.
- Closing the Local Engine safely cancels active media/image work and clears waiting jobs before the desktop process exits.
- Image downloads gained bounded retry/backoff, cancellation, `.part` cleanup, disk-space checks, local WebP/AVIF conversion safeguards, and ZIP-space reservation.
- Windows/Release validation now executes archive, queue, image and real loopback Bridge policy tests in addition to source/EXE self-tests and installer lifecycle checks.

### Download policy

- Default local media download remains one finished file built from best video + best audio where separate streams are required.
- Cover and subtitles remain opt-in; thumbnail/info-json/description/comment/playlist sidecars remain disabled by default.
- Collection URLs expose current-item, entire-collection and selected-item modes.
- Global yt-dlp configuration is ignored for deterministic output behavior.

### Playback and network hardening

- Dedicated progressive playback relay forwards a single valid byte Range and supports `206 Content-Range` responses.
- Playback redirect targets are revalidated hop-by-hop and malformed/multipart/oversized Range requests are rejected.
- Local Engine, Next.js routes and container relays reject obvious localhost/private/reserved source URLs; production egress restrictions are still recommended because application validation cannot eliminate DNS-rebinding TOCTOU.
- Cloudflare media/image relay traffic is protected by Durable Object rate limiting and bounded image response sizes.

## 0.7.0

- Added Local Engine original-image downloads and multi-image packaging.
- Added local handling for images that exceed the public relay size limit.
- Added local WebP/AVIF conversion where the source metadata indicates a common raster target.

## 0.6.0

- Added rich web-document parsing and installed Edge/Chrome CDP dynamic rendering fallback.
- Added structured article/commerce extraction and WeChat article Markdown/archive support.
- Browser login cookies are only attempted after an explicit authentication-required result.
