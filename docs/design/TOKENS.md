# Design Tokens

## Naming

Runtime code should migrate toward semantic names. A token describes purpose, not a one-off widget.

## Color

Current Desktop baseline and semantic mapping:

| Semantic token | Current value | Existing runtime name |
| --- | --- | --- |
| `color.bg` | `#080C14` | `BG` |
| `color.surface` | `#0F1624` | `PANEL` |
| `color.surface.raised` | `#141E30` | `PANEL_2` |
| `color.surface.elevated` | `#1A2740` | `PANEL_3` |
| `color.border` | `#25324B` | `BORDER` |
| `color.border.subtle` | `#1C2940` | `BORDER_SOFT` |
| `color.text.primary` | `#F6F8FC` | `TEXT` |
| `color.text.secondary` | `#9AA6BB` | `MUTED` |
| `color.text.subtle` | `#6F7D95` | `SUBTLE` |
| `color.accent` | `#7C6CFF` | `ACCENT` |
| `color.accent.hover` | `#9185FF` | `ACCENT_HOVER` |
| `color.info` | `#36D7C4` | `CYAN` |
| `color.success` | `#45D18A` | `SUCCESS` |
| `color.warning` | `#F2B84B` | `WARNING` |
| `color.danger` | `#FF6278` | `DANGER` |
| `color.danger.hover` | `#FF788B` | `DANGER_HOVER` |
| `color.focus` | `#9185FF` | derive from accent hover |

Rules:
- Text/body contrast takes priority over brand color.
- Do not encode state using color alone; pair with label/icon/status text.
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
| `space.5` | 20 | page subsection gap |
| `space.6` | 24 | page padding / major separation |
| `space.8` | 32 | large section separation |
| `space.10` | 40 | sparse empty-state spacing |

Avoid arbitrary values unless required by a native widget geometry constraint.

## Radius

Tk controls do not consistently support radius. Radius tokens primarily document web/dashboard and custom-drawn surfaces:

- `radius.none = 0`
- `radius.sm = 4`
- `radius.md = 8`
- `radius.lg = 12`
- `radius.pill = 999`

Desktop Tk surfaces should prefer borders and spacing over simulated rounded cards.

## Shadow

- `shadow.none`: default for most Desktop controls.
- `shadow.low`: subtle elevation for floating menus/tooltips only.
- `shadow.dialog`: modal/dialog separation only.

Do not use glow as a shadow token.

## Type

Default family: `Segoe UI`, platform fallback when unavailable.

| Token | Desktop size | Typical use |
| --- | ---: | --- |
| `type.caption` | 7 | metadata/status helper |
| `type.body.sm` | 8 | compact controls/table rows |
| `type.body` | 9 | standard body/control |
| `type.title.sm` | 10 | section title |
| `type.title` | 16 | page/dialog title |
| `type.display` | 17–18 | brand/rare metrics |

Weights: regular and bold. Avoid introducing many intermediate weights.

## Control sizing

- Normal button vertical padding: 8 px; compact: 5 px.
- Text/select controls should remain comfortably keyboard/mouse usable; target approximately 36–44 px visual height when the surrounding layout permits.
- Icon-only actions require at least a documented accessible label/tooltip and a practical hit target.

## Motion

- `motion.fast = 100ms`
- `motion.normal = 180ms`
- `motion.slow = 260ms`
- standard easing: ease-out for entrances/state confirmation; ease-in-out for reversible transitions.
- respect reduced-motion preferences where the surface can detect them.

Motion is never required for progress correctness; progress state must remain readable without animation.
