# Galaxy Downloader — Product Context

## Product

Galaxy Downloader / SparkDownloader is a multilingual download and media utility with two connected surfaces:

- a React/Next-style Web application for entering links, parsing sources, choosing outputs, previewing results, batch work and history;
- Galaxy Local Engine, a native desktop companion that performs local parsing/download work, exposes task/recovery state and supports native transfer tools.

The product is a utility first. Users arrive with a source and want to reach a usable output with minimal ambiguity.

## Primary jobs

1. Paste or enter a media/document source.
2. Understand whether the source can be handled and what outputs are available.
3. Choose output/options without losing the main task context.
4. Start work and understand progress, pause/resume/retry/recovery state.
5. Find completed/recent work and repeat or inspect it.
6. Configure advanced behavior only when needed.

## Important surfaces

### Web

- localized unified downloader (`src/app/[locale]`)
- unified input and parse/result flow
- batch workbench
- result panels for media/images/audio/documents
- local-engine setup/status hints
- download history
- playback/preview page
- contact, feedback, privacy and terms pages
- dialogs and secondary tools

### Native Desktop

- primary Local Engine workbench
- task center and resume/recovery flows
- transfer center including Torrent/Magnet
- settings/advanced controls
- QR/local transfer and supporting dialogs
- packaged Windows/Linux/macOS native surfaces where applicable

## Product truths to preserve during UI work

- Do not change download, parse, provider, recovery, security or routing behavior merely to simplify a visual redesign.
- Preserve localized/factual copy unless the task explicitly includes copy changes.
- Preserve clear error reasons and actionable recovery guidance.
- Advanced capability may be progressively disclosed, but must remain reachable.
- Desktop is a real native workbench, not a web mockup.
- Existing light/dark theme behavior must remain coherent.
- Long URLs, filenames and translations are normal product input, not edge decoration.

## User experience priorities

1. Task clarity.
2. Trust in current state and output destination.
3. Fast scanning for power users.
4. Progressive disclosure for advanced options.
5. Accessible keyboard/touch operation.
6. Stable responsive layouts and predictable native behavior.
7. Visual polish without generic template aesthetics.

## Design routing

All UI work must begin with `.agents/skills/ui-skills-root/SKILL.md`, which routes this repository through `.agents/skills/galaxy-ui/SKILL.md` and no more than two task-specific design skills.
