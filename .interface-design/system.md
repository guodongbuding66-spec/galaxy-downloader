# Galaxy Local Engine — Design System v1.7

## Intent
Native Windows utility for people who repeatedly capture product images, videos, audio and documents. It must feel like a serious local tool: readable, calm, operational and trustworthy. The native `GalaxyLocalEngine.exe` is the canonical surface; the HTML dashboard is optional and never substitutes for the EXE UI.

## Product world
Capture strip, product gallery, original-resolution probe, transfer queue, filesystem, codecs, local engine, task history, diagnostics.

## Signature
One capture strip leads the workbench: **paste URL → inspect → choose media/original images → download**. Home Depot/product-page original-image recovery is part of this strip, not a hidden secondary web page.

## Rejected defaults
- No neon, glow, glassmorphism, decorative gradients or “AI dashboard” styling.
- No grid of equal rounded cards; use a workbench with clear primary/secondary zones.
- No 7–8pt operational text; 9pt is reserved for low-priority metadata only.
- No forced `tk scaling = 1.0`; respect Windows DPI.
- No pill chips unless they are real status/filter controls.
- No oversized marketing headings in the desktop application.
- No motion-only feedback.

## UI Skills mapping
- `interface-design`: borders-only depth, 4px spatial grid, semantic tokens, four-level text hierarchy, native/ttk controls before custom widgets.
- `frontend-design`: distinctive product-specific hierarchy; avoid template SaaS/AI aesthetics.
- `better-ui`: high-frequency feedback ≤150ms, explicit hover/focus/press states, optical alignment, one icon language, no `transition: all` equivalent behavior.

## Tokens
- Grid: 4px base. Normal spacing: 8 / 12 / 16 / 20 / 24 / 32.
- Radius: native Tk controls stay flat; 4–8px only where the platform primitive supports it.
- Minimum hit target: 44px; comfortable primary target: 46px.
- Canvas: `#0E1116`.
- Workspace: `#141922`.
- Raised surface: `#1A2130`.
- Elevated inset: `#202A3A`.
- Primary text: `#F7F9FC`.
- Secondary text: `#C2CAD6`.
- Tertiary text: `#8F9AAA`.
- Accent: `#4F7DFF`, reserved for primary action/current focus.
- Success: `#65BE92`; warning: `#D9A85F`; danger: `#E27676`.
- Border: `#334052`; subtle border: `#273241`.
- Typeface: Segoe UI / Segoe UI Variable when available; Microsoft YaHei UI fallback is acceptable on Chinese Windows.
- Native type scale: caption 9pt (metadata only), supporting 10pt, body 11pt, section 13pt, title 18pt, brand 21pt, display 24pt.
- Depth strategy: borders + surface-color shifts only. No layout shadows.
- Motion language: native hover/pressed color feedback around 100–150ms where possible; keyboard focus ring always visible; reduced-motion/static cues remain sufficient.

## Layout
- Preferred native window: approximately 1320×880.
- Responsive floor: approximately 960×680 when the Windows work area is smaller; never force the window outside the visible display.
- At constrained widths the secondary header actions wrap below the product identity instead of clipping off-screen.
- Main workbench / status rail: ~72/28.
- Capture strip is the first focal block inside the main workbench.
- Current task and advanced options follow the capture strip.
- Queue and local runtime components live in the right rail.
- Original-image action sits with the capture strip and explains maximum-public-resolution fallback.
- gallery-dl fallback and its low-frequency tuning stay behind progressive disclosure so they do not bury the current task on laptop-height displays.

## Accessibility / readability gates
- Never force Tk global scaling to 1.0 on Windows high-DPI displays.
- Every custom action must be keyboard focusable.
- Focus ring width ≥2px.
- Body text cannot be below the shared body token; legacy hook text is normalized after composition.
- Status must use text/icon/color together where applicable.
- Primary actions and dangerous actions must remain visually distinct in monochrome/squint tests.
- CI must fail when any visible native `Button` extends outside the root window bounds.
