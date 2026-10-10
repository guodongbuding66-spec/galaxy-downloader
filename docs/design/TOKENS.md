# Design Tokens

## Naming

Runtime code uses semantic names. Galaxy Local Engine V1.7 uses a high-contrast graphite native desktop system with one blue action accent; status colors are semantic only. The native EXE is the canonical product surface.

## Color

Canonical native Desktop mapping:

| Semantic token | Current value | Existing runtime name |
| --- | --- | --- |
| `color.bg` | `#0E1116` | `BG` |
| `color.surface` | `#141922` | `PANEL` |
| `color.surface.raised` | `#1A2130` | `PANEL_2` |
| `color.surface.elevated` | `#202A3A` | `PANEL_3` |
| `color.border` | `#334052` | `BORDER` |
| `color.border.subtle` | `#273241` | `BORDER_SOFT` |
| `color.text.primary` | `#F7F9FC` | `TEXT` |
| `color.text.secondary` | `#C2CAD6` | `MUTED` |
| `color.text.subtle` | `#8F9AAA` | `SUBTLE` |
| `color.accent` | `#4F7DFF` | `ACCENT` |
| `color.accent.hover` | `#6C94FF` | `ACCENT_HOVER` |
| `color.info` | `#75A7D8` | `CYAN` |
| `color.success` | `#65BE92` | `SUCCESS` |
| `color.warning` | `#D9A85F` | `WARNING` |
| `color.danger` | `#E27676` | `DANGER` |
| `color.danger.hover` | `#EC8787` | `DANGER_HOVER` |
| `color.focus` | `#86A4FF` | dedicated keyboard focus ring |

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

- Normal button vertical padding: 9 px; compact: 7 px.
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
