# Desktop Runtime Token Migration

This contract documents the first runtime migration step for Galaxy Local Engine Desktop.

## Scope in this PR

- `desktop_ui.py` is a stable facade for existing imports.
- the prior implementation is isolated in `_desktop_ui_impl.py` without changing download behavior.
- semantic palette values are rebound from `desktop_design_tokens.COLOR`.
- the shared `ActionButton` consumes token-backed typography and padding.
- `_label`, `_entry`, and `_check` consume token-backed typography while retaining existing call signatures and numeric sizes.
- existing public aliases (`BG`, `PANEL`, `TEXT`, `ACCENT`, and related names) remain available.

## Deliberately deferred

This PR does not claim the full Desktop redesign is complete. Page-level spacing, remaining exceptional display sizes, dialogs, transfer workspaces, and motion/accessibility refinements are migrated in independent follow-up contracts so each change stays testable and rollbackable.

## Gate

`Design System` runs the runtime token registry self-test, the Desktop facade self-test, the dedicated facade contract test, and the design documentation contract on every relevant pull request and `main` push.
