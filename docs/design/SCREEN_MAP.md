# Screen Map

## Desktop information architecture

```text
Galaxy Desktop
├── Home / Download Workbench
├── Downloads
├── Media Library
├── Transcript
├── AI
├── Courses
├── Reader
├── Music
├── Subscriptions
├── Transfer Center
├── Plugins
└── Settings
```

The roadmap may deliver some areas incrementally, but new entry points should fit this map instead of creating unrelated floating windows without a product home.

## Home / Download Workbench

Primary job: URL/input → preview/format choice → queue/download.

Key regions:
- URL/input and paste/clipboard handoff
- source/format preview
- download options
- queue/current task
- progress/status
- advanced settings entry

## Downloads

Primary job: inspect and control active/recent jobs.

Key states/actions:
- queued, running, paused, retrying, post-processing, complete, failed
- speed/ETA/progress
- pause/resume/cancel/retry
- open file/folder
- history/archive relation

## Media Library

Primary job: find and organize completed local media.

Key regions:
- search/filter/sort
- list/table/grid depending content
- metadata/detail
- collections/tags/bookmarks
- rename/move/convert/reindex actions

## Transcript

Primary job: transcribe, search and navigate media by speech.

Key regions:
- model/ASR capability
- transcript timeline/text
- search
- speaker labels
- player seek
- export

## AI

Primary job: run local/remote AI operations with visible provider/model/task history.

Key regions:
- provider/model status
- prompt/task input
- queue
- history/output
- provider test/configuration

## Courses

Primary job: acquire and study structured courses.

Hierarchy: provider → course → section/chapter → lesson → attachment.

Key regions:
- course library
- lesson tree
- player/content
- attachments
- notes
- resume/progress

## Reader

Primary job: read local documents/books and retain position/notes.

Key regions:
- library/document list
- reader viewport
- table of contents/search
- notes/bookmarks
- reading progress

## Music

Primary job: manage and play local music/audio.

Key regions:
- library/search
- now playing/player
- queue/playlist
- metadata/artwork

## Subscriptions

Primary job: monitor feeds/channels and reconcile automated downloads.

Key regions:
- sources
- last check/status
- rules/profile
- new/queued/downloaded items
- reconcile/action history

## Transfer Center

Sibling workflows belong in one center:
- Torrent / Magnet
- P2P short code
- Telegram upload
- Telegram download / Chat Browser
- QR phone receive

Transfer surfaces must state whether traffic is LAN-only, direct external service, or another transport.

## Plugins

Primary job: discover/manage explicitly installed extension capabilities.

Key regions:
- installed plugins
- status/version
- permissions/capabilities
- enable/disable/update
- diagnostics

## Settings

Organize by user mental model, not module names:
- General
- Download defaults
- Network / proxy
- Browser & cookies
- Tools / FFmpeg / yt-dlp
- AI / ASR models
- Integrations / Telegram
- Storage / Library
- Appearance / accessibility
- Advanced / diagnostics

## Browser Extension

```text
Browser Extension
├── Page Media Discovery
├── Element Hover Actions
├── Candidate Browser
├── Settings
└── Desktop Handoff
```

Settings include ignored domains, minimum media dimensions and bounded stream auto-handoff.

## Web / Remote

The Web Dashboard / Remote API should mirror capability/status and safe task actions; it must not expose arbitrary local filesystem paths or Desktop-only secrets.

## Navigation rule

A feature is not considered product-complete when only a backend module exists. It needs a discoverable entry point in this map, or a documented reason that it is API/CLI-only.
