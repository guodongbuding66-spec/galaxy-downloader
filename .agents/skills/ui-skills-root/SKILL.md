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

## Galaxy project routing

For this repository, route first through `galaxy-ui`. It is the project-specific contract that decides which two additional skills, at most, belong to a particular surface.

Typical routes:

- Web product/downloader workbench: `galaxy-ui` + `impeccable` + `interface-design`.
- Web landing/marketing/read surface: `galaxy-ui` + `design-taste-frontend` + `impeccable`.
- Native Windows/Tk workbench: `galaxy-ui` + `interface-design` + `impeccable`.
- Interaction-only refinement: replace the less relevant third skill with `interaction-design`.

Do not load every installed design skill at once. `better-ui`, `frontend-design`, and `interaction-design` are targeted tools, not mandatory companions.

A web prototype must never replace the canonical native `GalaxyLocalEngine.exe` unless the user explicitly requests a web application.
