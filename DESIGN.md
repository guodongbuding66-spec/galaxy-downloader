# Galaxy UI Design System

This file is the durable visual and interaction contract for Galaxy. It complements `.agents/skills/galaxy-ui/SKILL.md`.

## Design read

Galaxy is a precise, calm, high-density utility. The product should feel engineered rather than decorated: neutral surfaces, clear grouping, strong state communication, restrained motion and one controlled accent family.

Default product dials:

- `DESIGN_VARIANCE: 5`
- `MOTION_INTENSITY: 3`
- `VISUAL_DENSITY: 7`

Landing/read surfaces may lower density and raise variance. Operational surfaces should not imitate a marketing page.

## Foundations

### Color

- Neutral base first.
- One brand/focus accent family.
- Semantic success/warning/info/destructive colors are reserved for state.
- No decorative purple/blue glow, mesh-gradient wallpaper, or multi-accent dashboard styling.
- Light and dark themes must preserve the same hierarchy, not merely invert values.

Web semantic variables live in `src/app/globals.css`. Native semantic tokens live in `local-engine/desktop_design_tokens.py` and shared native primitives.

### Typography

- Use the existing platform-appropriate sans stack unless a deliberate brand typography task changes it.
- Hierarchy comes from weight, size, line-height and spacing before color.
- Product/workbench copy is compact and direct.
- Long localized strings must wrap without breaking controls.
- Avoid tiny explanatory text when the content is required for successful operation.

### Radius and elevation

- Small/medium radii only; avoid a screen full of floating pill shapes.
- Borders define most product grouping.
- Shadows are shallow and reserved for true elevation/stacking.
- Do not wrap every sentence or setting in a card.

### Spacing

Use a consistent 4px-derived rhythm. Product density is intentionally high, but adjacent task groups need visible separation. Mobile collapse follows task priority rather than simply squeezing columns.

## Components

### Buttons

- One primary action per local task region where possible.
- Secondary/outline for adjacent reversible actions.
- Ghost for low-emphasis utility actions.
- Destructive only for destructive outcomes.
- All states: default, hover, pressed, focus-visible, disabled, busy where applicable.
- Coarse-pointer effective target approaches 44px even when desktop visual density is compact.

### Fields

- Persistent accessible label or equivalent accessible name.
- Placeholder is guidance, not the only label.
- Hover, focus, invalid and disabled states must be distinguishable without layout jumps.
- Mobile text entry must avoid browser zoom-inducing tiny font sizes.

### Cards/panels

Use panels to group a coherent task or result. Do not create equal-weight card grids when information has a natural hierarchy.

### Dialogs

- Dialog title states the task, not generic “Details”.
- Primary action remains visually clear.
- Destructive actions are separated or clearly styled.
- Long content uses bounded scrolling without hiding the action area.

### Status/progress

Never communicate status by color alone. Use text/icon/progress together where practical. Paused/retrying/error/recovered states need explicit wording.

## Surface rules

### Web unified downloader

Priority order:

1. product/task title + concise operational context;
2. source input and primary parse/download action;
3. immediate error/helper state;
4. batch/advanced controls;
5. current result/progress;
6. history/help/secondary material.

### Web results and batch workbench

- Optimize for scanning and repeated action.
- Use aligned columns/grid, not decorative card mosaics.
- Keep filenames, sizes, quality, destination and actions visually associated.
- Selection state must remain obvious in light/dark themes.

### Read/marketing/legal pages

These may use more whitespace and stronger editorial composition. Taste Skill may be primary here, but the same brand tokens and accessibility floor remain.

### Native Desktop

- Preserve native workbench expectations and keyboard behavior.
- Main task path should be visible without opening settings.
- Advanced settings use progressive disclosure and compact grouping.
- New controls use shared native tokens/primitives before introducing page-local styling.
- Minimum target policy is enforced by the native token system; compact visual treatment must not silently remove the usable target.

## Interaction

- Prefer 120–180ms transitions for local hover/press/focus feedback.
- Prefer transform/opacity for motion.
- Avoid continuous decorative animation in Operate surfaces.
- Respect `prefers-reduced-motion` on Web and equivalent native constraints.
- Loading must not look like a frozen control; preserve action context.

## Responsive behavior

- Web layout container is shared and bounded.
- Use CSS Grid for multi-column workbench structure.
- At narrow widths: source/action first, results second, secondary help last.
- Touch/coarse pointer targets expand without forcing desktop mouse density to become oversized.
- Safe-area insets must remain usable for fixed mobile actions.

## Quality gate

A UI change is not complete until the applicable checks pass:

- light/dark
- keyboard focus
- hover/press/disabled/loading/error states
- desktop + narrow/mobile Web
- native source + packaged UI smoke when native files change
- lint/tests/build
- one bounded visual defect pass and one confirmation pass

Backend transfer/security/recovery behavior must remain unchanged during a purely visual pass.
