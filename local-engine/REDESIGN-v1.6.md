# Galaxy Local Engine UI v1.6

## What changed

- The V1.6 **portable Windows package** uses the root `GalaxyLocalEngine.exe` as the modern UI launcher. Double-clicking it starts the existing engine in the background and opens the redesigned workbench.
- In that portable package, the original frozen Tk/Python engine is preserved byte-for-byte as `GalaxyLocalEngineBackend.exe`.
- Default UI was redesigned as a restrained desktop workbench: flat graphite surfaces, a single blue action accent, compact spacing, minimal radius, no glow, no decorative gradients, no glassmorphism, no identical SaaS card grid.
- The default home screen is now a split workbench: capture/download workflow on the left, engine/task context on the right.
- Existing skin studio remains available. The new default is `Workbench / 工作台 · 石墨` and the skin variables still drive the v1.6 surface tokens.
- The source tree includes the geometric SVG app mark used by the dashboard. Windows `.ico`, launcher `.exe`, and rendered PNG assets are packaging/release artifacts.

## UI Skills used

Project-scoped skill profiles are stored under `.agents/skills/`:
- `interface-design`
- `frontend-design`
- `better-ui`

The design decisions are stored in `.interface-design/system.md` so later iterations do not drift back toward the rejected visual style.

## Runtime architecture

The source-side launcher is `start-modern-ui.ps1` / `Launch-Modern-UI.cmd`. It starts the local backend, starts the media preview helper, then opens the dashboard in Edge App Mode. `galaxy-downloader://` arguments are forwarded to the backend so protocol integration remains usable.

The packaged Windows layout is:

```text
GalaxyLocalEngine.exe        = modern UI launcher
GalaxyLocalEngineBackend.exe = existing download engine
```

## GitHub source sync

V1.6 is synchronized as auditable source first. The repository intentionally does not replace the existing engine with an opaque generated binary. Windows launcher/icon binaries belong to the build/release artifact stage.
