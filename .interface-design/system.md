# Galaxy Local Engine — Design System v1.6

## Intent
Desktop power tool for people capturing/downloading media all day. It should feel like a serious local utility: calm, compact, trustworthy, fast. Not a futuristic AI dashboard.

## Product world
Capture queue, filesystem, transfer status, codecs, source inspection, local engine, task history.

## Signature
A single “capture strip” leads the workspace: paste URL → inspect → choose resource → download. Everything else is subordinate operational context.

## Defaults explicitly rejected
- No neon, glow, glassmorphism or ornamental gradients.
- No grids of identical rounded cards.
- No tracked all-caps eyebrow labels as decoration.
- No pill chips unless they represent actual status/filter state.
- No oversized marketing typography inside the application.

## Tokens
- Grid: 4px base; main spacing 8 / 12 / 16 / 24 / 32.
- Radius: 4px controls, 6px panels, 8px modal only.
- Control heights: 34px compact, 38px primary form controls.
- Canvas: #121315; workspace: #161719; inset: #0F1012.
- Primary text: #F1F2F4; secondary: #A6A9AE; muted: #70747B.
- Accent: #6F8FFF. Accent is reserved for focused/current/primary action.
- Success: #5FAF88; warning: #C99A54; error: #D76A6A.
- Border: rgba(255,255,255,.075); stronger: rgba(255,255,255,.12).
- Typeface: Segoe UI Variable / Segoe UI / Microsoft YaHei UI / system UI.
- Body: 13px; labels: 12px; page title: 20px/650; section title: 14px/650.
- Shadows: none for layout surfaces; only popovers/dialogs.
- Motion: color/border/background 120ms; button press 150ms ease-out scale(.96); no transition:all; reduced-motion supported.
