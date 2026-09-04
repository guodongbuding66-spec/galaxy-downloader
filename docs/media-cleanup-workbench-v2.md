# Media Cleanup Workbench 2.0

This desktop surface edits only user-selected visible pixels.

## Modes

- Images: Pillow-based visible-pixel inpainting.
- Videos: fixed visible-overlay cleanup.
- Videos: tracked visible-overlay cleanup with one confirmed anchor region.

## Guardrails

- Automatic suggestions never execute cleanup until the user confirms them.
- Moving-video tracking requires exactly one confirmed region and fails closed on low-confidence tracking.
- Source files are never overwritten.
- Before/after comparison uses the same source frame time for both files.
- SynthID, C2PA, and other invisible provenance/authenticity markers are out of scope.

## Desktop lifecycle

The legacy workbench hook still owns the toolbar button, cancellation state, and graceful-exit contract. Workbench 2.0 replaces only the presenter at startup, so existing close/cancel behavior remains compatible.
