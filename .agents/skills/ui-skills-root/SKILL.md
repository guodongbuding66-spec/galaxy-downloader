---
name: ui-skills-root
description: Route UI work to the smallest useful set of UI Skills before implementation.
source: https://github.com/ibelick/ui-skills/tree/main/skills/ui-skills-root
license: MIT
metadata:
  author: ibelick
  upstream-version: "1.0.0"
  install-mode: project-local
---

# UI Skills Root

Use this skill before UI-related work.

## Protocol

1. Decide whether the task is UI-related.
2. Identify the narrowest useful design category.
3. Prefer one skill. Use two only for two distinct concerns. Use three only for a broad redesign/review.
4. Never load more than three UI skills for one pass.
5. Prefer specific skills over broad skills.
6. Implement with the selected skill context, then visually verify the result.

## Galaxy Local Engine routing

For the native Windows application, default to:

- `interface-design` for hierarchy, density, navigation, workbench structure, settings and data-heavy utility surfaces.
- `better-ui` for typography, surfaces, borders, optical alignment, states and micro-polish.
- `interaction-design` only when motion, loading feedback, hover/press/focus transitions, progress states or other interaction feedback are in scope.

`frontend-design` and `web-artifacts-builder` may be used for an exploratory web prototype, but the prototype must not replace the canonical native `GalaxyLocalEngine.exe` unless the user explicitly asks for a web application.
