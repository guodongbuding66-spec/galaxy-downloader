# Galaxy Design System

## Purpose

Galaxy is a local-first media workspace, not a decorative download demo. The UI must make long-running downloads, local tools, media processing, transfer, reading, learning and automation understandable without hiding system state.

This directory is the source of truth for Desktop visual and interaction rules. New Desktop work should reference these documents before introducing new colors, spacing, controls, icons or motion.

## Product principles

1. **Local state is visible.** Show what is running locally, what is queued, where data is stored and which external service is used.
2. **Primary work stays calm.** One dominant action per surface; secondary actions should not compete visually.
3. **Real controls over decorative containers.** Prefer native focusable controls and explicit labels to icon-only cards or ornamental chrome.
4. **Progress is continuous.** Long-running work needs queued, running, paused, retrying, merging, completed and failed states.
5. **Errors are recoverable.** Explain the failed step, preserve the user's inputs and expose a concrete retry or corrective action.
6. **Capabilities are honest.** Optional tools, adapters and models must show unavailable/unconfigured states instead of silently disappearing.
7. **Density follows the task.** Workbench and library views may be information-dense; onboarding, empty states and destructive dialogs should stay sparse.
8. **No AI visual clichés.** Avoid gratuitous gradients, glowing blobs, oversized glass cards, rainbow accents and excessive rounded containers.

## Visual direction

- One charcoal canvas for navigation and work, with the raised source composer as the visual focus. Blue identifies primary action, current mode and keyboard focus.
- Strong contrast between application background, surfaces and elevated surfaces.
- Segoe UI on Windows; use the platform UI fallback where Segoe UI is unavailable.
- Corners are modest, shadows are rare, borders carry most hierarchy.
- Status colors communicate state; they are not decoration.

## Layout rules

- Desktop minimum useful width: 940 px for the main workbench unless a specific surface documents a smaller bound.
- Primary page padding uses the spacing scale from `TOKENS.md`.
- Keep labels immediately adjacent to their controls.
- Forms align by semantic groups rather than forcing every field into one row.
- Scroll one major region per view where possible; avoid nested scroll areas.
- Tables/list rows keep stable columns while state changes.

## Interaction rules

- Every actionable element must be keyboard reachable.
- Every text field and select has a visible label; placeholder text is not a label.
- Destructive actions require explicit wording and confirmation when data loss is meaningful.
- Network, filesystem, model and media-processing work must stay off the Tk UI thread.
- UI updates from workers return through the UI event loop.
- A close action must cancel/stop owned ephemeral resources when reasonable.

## State model

Every feature surface should deliberately cover:

- loading / initializing
- empty
- ready
- busy / progress
- paused when supported
- recoverable error
- unavailable dependency
- completed / success

## Review checklist

Before merging UI work:

- Uses semantic tokens instead of new literal colors where possible.
- Uses documented spacing/type/control patterns.
- Has visible labels, focusability and disabled/busy states.
- Does not block the UI thread with I/O.
- Does not leak secrets or local paths unintentionally.
- Handles empty/error/unavailable states.
- Preserves existing keyboard behavior.
- Passes the relevant Desktop UI smoke/contract tests.

## Native download workbench

The native shell uses the project’s canonical near-black canvas, a 168px navigation column and one raised source composer. At compact widths the queue and engine remain available through the transfer row, navigation and footer; a separate 248px queue rail appears when the client width reaches 1120px. There is no promotional banner. The mode switch sits next to the source input, whose contents survive a mode change.

The one primary action per mode is styled with a 6px radius, blue fill and dark high-contrast text. Other controls use tonal feedback; surfaces use no shadows or decorative gradients. Format selection appears only after a real source catalog is available. Changing link or login invalidates the old preview. Ctrl+L focuses the input. The transfer row shows real progress and timing only once a task exists.
