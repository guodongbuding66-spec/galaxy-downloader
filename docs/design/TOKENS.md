# Design Tokens

## Naming

Runtime code uses semantic names. Galaxy Local Engine V1.7 uses a light slate native desktop system with one blue action accent; status colors are semantic only. The native EXE is the canonical product surface.

## Color

Canonical native Desktop mapping:

| Semantic token | Current value | Existing runtime name |
| --- | --- | --- |
| `color.bg` | `#F2F5FA` | `BG` |
| `color.surface` | `#FFFFFF` | `PANEL` |
| `color.surface.raised` | `#F7F9FD` | `PANEL_2` |
| `color.surface.elevated` | `#EDF2FA` | `PANEL_3` |
| `color.border` | `#7B899E` | `BORDER` |
| `color.border.subtle` | `#DCE3EE` | `BORDER_SOFT` |
| `color.text.primary` | `#18243B` | `TEXT` |
| `color.text.secondary` | `#47566D` | `MUTED` |
| `color.text.subtle` | `#596B83` | `SUBTLE` |
| `color.accent` | `#2458D8` | `ACCENT` |
| `color.accent.hover` | `#1B46B7` | `ACCENT_HOVER` |
| `color.info` | `#285FAD` | `CYAN` |
| `color.success` | `#167548` | `SUCCESS` |
| `color.warning` | `#8C6010` | `WARNING` |
| `color.danger` | `#B93445` | `DANGER` |
| `color.danger.hover` | `#9C2736` | `DANGER_HOVER` |
| `color.focus` | `#2458D8` | dedicated keyboard focus ring |

Rules:
- Primary text/body contrast takes priority over brand color.
- Accent is reserved for current/focused/primary action; do not spread blue across passive decoration.
- Do not encode state using color alone; pair with label, icon or status text.
- No neon glow, glassmorphism, ornamental gradients, or purple/cyan “AI dashboard” treatment in the native utility.
- New literal colors require adding a semantic token first.

## Spacing

Use a 4 px base unit: 4, 8, 12, 16, 20, 24, 32 and 40 px. Avoid arbitrary values unless a native widget geometry constraint requires them. The workbench uses spacing and hierarchy instead of grids of repeated cards.

## Radius

Tk controls do not consistently support radius. `radius.none = 0`, `radius.sm = 4`, `radius.md = 6`, `radius.lg = 8`, `radius.pill = 999`. Native Tk surfaces prefer borders, spacing and tonal layering over simulated rounded cards.

## Shadow

`shadow.none` is the default. `shadow.low` is reserved for floating menus/tooltips and `shadow.dialog` for modal separation. Main application panels do not use glow or decorative drop shadows.

## Type

Default family: `Segoe UI`, with platform fallback when unavailable. V1.7 raises the older native scale and preserves Windows DPI scaling, so the app remains readable at 100%, 125%, 150% and 200% display scale.

| Token | Desktop size | Typical use |
| --- | ---: | --- |
| `type.caption` | 9 | metadata/status helper |
| `type.body.sm` | 10 | compact controls/table rows |
| `type.body` | 11 | standard body/control |
| `type.title.sm` | 13 | section title |
| `type.title` | 18 | page/current-task title |
| `type.brand` | 21 | application identity |
| `type.display` | 24 | rare large emphasis |

Weights are regular and bold. Avoid decorative tracked uppercase labels and unnecessary intermediate weights.

## Control sizing

- Normal button base vertical padding: 8 px; compact: 6 px. Font metrics add padding to maintain the 44 px target.
- Minimum practical interaction target: 44 px; primary controls target 46 px where native geometry permits it.
- Keyboard focus uses a dedicated 2 px visible focus ring; hover/press feedback is not conveyed by motion alone.
- Text/select controls remain keyboard/mouse usable and readable under Windows DPI scaling.
- Icon-only actions require an accessible label/tooltip and a practical hit target.

## Motion

- `motion.fast = 100ms`
- `motion.normal = 150ms`
- `motion.slow = 220ms`
- use ease-out for entrances/state confirmation and ease-in-out for reversible transitions.
- native buttons use short hover/press changes and repeated utility interactions stay visually quiet.
- reduced-motion users still receive static state cues.

Motion is never required for progress correctness; progress and state stay readable without animation.
