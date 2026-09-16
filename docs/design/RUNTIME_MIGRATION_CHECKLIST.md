# Runtime Token Migration Acceptance Checklist

- [x] `desktop_ui` public import path remains stable.
- [x] Legacy implementation is isolated without behavior changes.
- [x] Semantic colors come from `desktop_design_tokens.COLOR`.
- [x] Shared action-button typography and padding come from token registries.
- [x] Shared label, entry, and checkbox typography uses the token type scale.
- [x] Existing public color aliases remain available for workspace compatibility.
- [x] Dedicated import/alias contract test runs in the Design System workflow.
- [x] Exceptional 17/18pt display sizes are represented by named type tokens.
- [x] Shared action buttons enforce the 44px interaction-target contract from measured font metrics.
- [x] Shared action buttons expose token-backed visible keyboard focus rings.
- [x] Remaining core page-level spacing migrated to the shared 4px semantic layout scale.
- [x] Transfer/workspace-specific components migrated (Transfer Center, QR Transfer, Telegram Download).
- [x] Final motion/accessibility pass completed: global Escape-close follows each dialog's `WM_DELETE_WINDOW` cleanup path, initial keyboard focus is assigned on Toplevel map, shared controls expose visible focus rings, and reduced-motion preference is available through the Desktop runtime contract.
