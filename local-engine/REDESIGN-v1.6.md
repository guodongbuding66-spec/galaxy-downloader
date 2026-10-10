# Galaxy Local Engine UI v1.6

## What changed

- The root `GalaxyLocalEngine.exe` is now the **modern UI launcher**. Double-clicking it starts the existing engine in the background and opens the redesigned workbench.
- The original frozen Tk/Python engine is preserved byte-for-byte as `GalaxyLocalEngineBackend.exe`.
- Default UI was redesigned as a restrained desktop workbench: flat graphite surfaces, a single blue action accent, compact spacing, minimal radius, no glow, no decorative gradients, no glassmorphism, no identical SaaS card grid.
- The default home screen is now a split workbench: capture/download workflow on the left, engine/task context on the right.
- Existing skin studio remains available. The new default is `Workbench / 工作台 · 石墨` and the skin variables still drive the v1.6 surface tokens.
- A new geometric app mark is included as `GalaxyLocalEngine.ico`, `GalaxyLocalEngine-icon.png`, and dashboard SVG favicon.
- `install.ps1` now refreshes the desktop shortcut using the dedicated ICO.

## UI Skills used

Project-scoped skill profiles are stored under `.agents/skills/`:
- `interface-design`
- `frontend-design`
- `better-ui`

The design decisions are stored in `.interface-design/system.md` so later iterations do not drift back toward the rejected visual style.

## Important architecture change

`GalaxyLocalEngine.exe` = UI launcher
`GalaxyLocalEngineBackend.exe` = original download engine

The launcher calls `start-modern-ui.ps1`, which starts the backend hidden, starts the media preview helper, then opens the local dashboard in Edge App Mode. `galaxy-downloader://` arguments are forwarded to the backend so protocol integration remains usable.
