---
name: galaxy-ui
description: Canonical UI routing and quality contract for every Galaxy web and native desktop surface.
metadata:
  mode: project-local
  revision: "2026-10-11"
---

# Galaxy UI — canonical design route

Use this skill before changing any Galaxy page, component, dialog, native window, empty state, error state, loading state, or visual token.

## 1. Route first — maximum three skills

Use `ui-skills-root` first and load only the smallest useful set.

### Web product UI / downloader workbench — default

1. `impeccable` — **Operate** mode: hierarchy, cognitive load, accessibility, states, responsive behavior and production hardening.
2. `interface-design` — dense tool/workbench structure, information hierarchy, navigation, settings and data-heavy controls.
3. `interaction-design` — only when progress, drag/drop, hover/press/focus, loading or motion is materially in scope.

Do **not** use Taste Skill as the primary system for dense downloader/product UI. Its own scope says it is for landing pages, portfolios and redesign presentation surfaces, not dashboards/data tables/multi-step product UI.

### Web marketing / explanatory / landing surfaces

1. `design-taste-frontend` — design read, anti-template direction, variance/motion/density discipline.
2. `impeccable` — Persuade or Read mode, accessibility, responsive and production checks.
3. `better-ui` — only when typography/surface/micro-polish needs a focused pass.

### Native Desktop / Tk workbench

1. `interface-design` — native workbench hierarchy and density.
2. `impeccable` — Operate mode + native audit/adapt rules.
3. `interaction-design` — only for state feedback and interaction behavior.

Never replace native affordances with a web aesthetic merely for visual novelty.

## 2. Galaxy design read

Galaxy is a cross-platform power tool for downloading, parsing and managing media/documents. Product surfaces should read as:

> A precise, calm, high-density utility for people who want to finish a download task quickly, with confidence about source, output, progress and recovery.

Default product dials:

- DESIGN_VARIANCE: 5
- MOTION_INTENSITY: 3
- VISUAL_DENSITY: 7

Marketing/read surfaces may raise variance and lower density. The downloader/workbench must not.

## 3. Non-negotiable visual rules

- Token first. Do not introduce one-off color/radius/shadow values when an existing semantic token can express the intent.
- One accent family. No AI-purple/blue glow, decorative mesh gradients, glassmorphism everywhere, or unrelated neon accents.
- No card soup. Group by task and hierarchy; cards are structural surfaces, not decoration around every paragraph.
- No pill soup. Reserve pills/badges for compact status or categorization.
- Keep borders quiet and shadows shallow. Elevation communicates stacking/interaction, not luxury.
- Typography must communicate hierarchy before color does. Avoid random size jumps and excessive bold.
- Use the existing icon family consistently. Do not hand-draw SVGs for ordinary controls.
- Preserve factual copy and product behavior unless the task explicitly changes them.

## 4. Interaction/state contract

Every interactive control must define applicable states:

- default
- hover
- pressed
- focus-visible
- disabled
- loading/busy
- error/invalid when applicable
- selected/active when applicable

Focus must remain keyboard-visible. Never remove focus indication without a replacement.

Motion must be purposeful, short, and transform/opacity-first. Respect `prefers-reduced-motion`.

## 5. Accessibility and target sizing

- Primary controls and touch-oriented controls target approximately 44 px on coarse pointers/mobile.
- Dense desktop-only secondary controls may remain visually compact only when their effective target and spacing remain usable.
- Inputs need persistent labels or an equivalent accessible name; placeholder is not a label.
- Icon-only buttons require an accessible name and tooltip when meaning is not universal.
- Do not use color alone to communicate status.
- Maintain usable contrast in both light and dark themes.

## 6. Layout contract

- Product UI: task-first workbench; source/input first, then options, then result/progress, then secondary help.
- Use CSS Grid for multi-column structure; avoid percentage-width flex math.
- Keep a consistent content container and spacing rhythm.
- Mobile must collapse by task priority, not simply shrink desktop columns.
- Long filenames/URLs/localized text must wrap or truncate without breaking controls.
- Empty/error/loading content must reserve enough layout stability to avoid major jumps.

## 7. Quality gate before commit

For each UI change:

1. Audit the incumbent surface before editing.
2. Change shared primitives/tokens before duplicating page-level fixes.
3. Check light + dark when the surface supports themes.
4. Check desktop + narrow/mobile for Web; shipped native classes for Desktop.
5. Check keyboard focus and disabled/error/loading states.
6. Run lint/type/build and the relevant UI smoke tests.
7. Do one bounded defect pass, fix findings in one batch, then one confirmation pass.

Backend behavior and V2 transfer/recovery contracts are out of scope for purely visual work unless a verified UI defect requires an interface change.
