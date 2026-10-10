# Design Tokens

## Naming

Runtime code should use semantic names. A token describes purpose, not a one-off widget. Galaxy Local Engine V1.6.1 uses a restrained graphite desktop system with one blue action accent; status colors are semantic only.

## Color

Canonical native Desktop mapping:

| Semantic token | Current value | Existing runtime name |
| --- | --- | --- |
| `color.bg` | `#121315` | `BG` |
| `color.surface` | `#161719` | `PANEL` |
| `color.surface.raised` | `#1C1E22` | `PANEL_2` |
| `color.surface.elevated` | `#22252A` | `PANEL_3` |
| `color.border` | `#30333A` | `BORDER` |
| `color.border.subtle` | `#26292F` | `BORDER_SOFT` |
| `color.text.primary` | `#F1F2F4` | `TEXT` |
| `color.text.secondary` | `#A6A9AE` | `MUTED` |
| `color.text.subtle` | `#777B82` | `SUBTLE` |
| `color.accent` | `#6F8FFF` | `ACCENT` |
| `color.accent.hover` | `#829CFF` | `ACCENT_HOVER` |
| `color.info` | `#78A9D4` | `CYAN` |
| `color.success` | `#5FAF88` | `SUCCESS` |
| `color.warning` | `#C99A54` | `WARNING` |
| `color.danger` | `#D76A6A` | `DANGER` |
| `color.danger.hover` | `#E17A7A` | `DANGER_HOVER` |
| `color.focus` | `#8EA6FF` | dedicated keyboard focus ring |

Rules:
- Primary text/body contrast takes priority over brand color.
- Accent is reserved for current/focused/primary action; do not spread blue across passive decoration.
- Do not encode state using color alone; pair with label, icon or status text.
- No neon glow, glassmorphism, ornamental gradients, or purple/cyan “AI dashboard” treatment in the native utility.
- New literal colors require adding a semantic token first.

## Spacing

Use a 4 px base unit:

| Token | px | Use |
| --- | ---: | --- |
| `space.0` | 0 | reset |
| `space.1` | 4 | tight inline gap |
| `space.2` | 8 | control/internal gap |
| `space.3` | 12 | compact group gap |
| `space.4` | 16 | standard section/card padding |
| `space.5` | 20 | panel padding |
| `space.6` | 24 | page padding / major separation |
| `space.8` | 32 | large section separation |
| `space.10` | 40 | sparse empty-state spacing |

Avoid arbitrary values unless required by a native widget geometry constraint. The native workbench prefers quiet spacing and hierarchy over grids of repeated cards.

## Radius

Tk controls do not consistently support radius. Radius tokens primarily document web/dashboard and custom-drawn surfaces:

- `radius.none = 0`
- `radius.sm = 4`
- `radius.md = 6`
- `radius.lg = 8`
- `radius.pill = 999`

Desktop Tk surfaces should prefer borders, spacing, and tonal layering over simulated rounded cards.

## Shadow

- `shadow.none`: default for layout surfaces and most Desktop controls.
- `shadow.low`: subtle elevation for floating menus/tooltips only.
- `shadow.dialog`: modal/dialog separation only.

Do not use glow as a shadow token. Main application panels do not need drop shadows.

## Type

Default family: `Segoe UI`, platform fallback when unavailable. The V1.6.1 scale is intentionally larger than the older 7/8/9 pt native UI so Chinese and English labels remain legible on common Windows 100–125% scaling.

| Token | Desktop size | Typical use |
| --- | ---: | --- |
| `type.caption` | 8 | metadata/status helper |
| `type.body.sm` | 9 | compact controls/table rows |
| `type.body` | 10 | standard body/control |
| `type.title.sm` | 11 | section title |
| `type.title` | 17 | page/current-task title |
| `type.brand` | 18 | application identity |
| `type.display` | 20 | rare large emphasis |

Weights: regular and bold. Avoid decorative tracked uppercase labels and unnecessary intermediate weights.

## Control sizing

- Normal button vertical padding: 8 px; compact: 6 px.
- Minimum practical interaction target: 44 px when the surrounding native geometry permits it.
- Keyboard focus uses a dedicated 2 px visible focus ring; hover and press feedback must not be conveyed by scale alone.
- Text/select controls should remain comfortably keyboard/mouse usable and readable at 100–125% Windows scaling.
- Icon-only actions require an accessible label/tooltip and a practical hit target.

## Motion

- `motion.fast = 100ms`
- `motion.normal = 150ms`
- `motion.slow = 220ms`
- standard easing: ease-out for entrances/state confirmation; ease-in-out for reversible transitions.
- native buttons use short hover/press state changes; repeated utility interactions should stay visually quiet.
- respect reduced-motion preferences where the surface can detect them.

Motion is never required for progress correctness; progress and state must remain readable without animation.
