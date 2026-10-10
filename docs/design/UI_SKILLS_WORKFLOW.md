# Galaxy Local Engine — Skill-led UI Workflow

This document defines how UI skills are used for the native desktop application.

## Canonical surface

`GalaxyLocalEngine.exe` is the product. The native Windows/Tk UI is the canonical interface. HTML/web artifacts may be used to explore a composition or interaction, but they are evidence for implementation, not a replacement shell.

## Installed project skills

| Skill | Source | Role in Galaxy |
| --- | --- | --- |
| `ui-skills-root` | ibelick/ui-skills | Routes UI tasks to the smallest useful skill set. |
| `interface-design` | UI Skills / Dammyjay93 | Workbench hierarchy, density, structure, navigation, settings and data surfaces. |
| `better-ui` | UI Skills / jakubkrehel | Typography, surfaces, borders, optical alignment and interaction-state polish. |
| `interaction-design` | UI Skills / wshobson | Purposeful hover/press/focus/loading/progress/disclosure feedback. |
| `frontend-design` | anthropics/skills | Distinctive anti-generic direction for web prototypes only. |
| `web-artifacts-builder` | anthropics/skills | Optional high-fidelity interactive prototype workflow. |
| `last30days` | mvanhorn/last30days-skill | Fresh public research before major redesigns; project adapter avoids paid backends. |

## Required order for a major desktop redesign

1. **Research evidence** — use `last30days` only when recent market/community evidence could change the design. Keep existing user complaints and real product screenshots as stronger evidence than trends.
2. **Select UI skills** — use `ui-skills-root`. For Galaxy, normally select `interface-design` + `better-ui`; add `interaction-design` only when motion/state feedback is a meaningful part of the task.
3. **Define structure before styling** — establish focal task, primary/secondary zones, density, navigation and progressive disclosure before choosing decorative details.
4. **Prototype only if useful** — use `web-artifacts-builder` for a complex interaction comp when static sketches are insufficient. Do not ship the web prototype as the app shell.
5. **Implement natively** — port the approved hierarchy, tokens and interaction decisions into the real Tk/Windows surface.
6. **Verify the real EXE** — capture the actual native window and test at compact, normal and large desktop sizes.

## Visual direction for Galaxy

- Serious Windows utility, not a marketing site and not a futuristic AI dashboard.
- One clear focal action: paste/inspect/download.
- One restrained accent color; status colors are semantic only.
- Segoe UI / Segoe UI Variable on Windows.
- High-contrast operational text; metadata may be quieter but never illegible.
- Prefer spacing, weight and tonal separation over excessive borders, cards or shadows.
- Avoid purple gradients, glow, glassmorphism, giant centered headings, equal rounded-card grids and arbitrary pills.
- Avoid Inter as a default web-design shortcut.
- Use native/ttk controls where they improve platform familiarity.

## Interaction rules

- Hover/press/focus feedback: roughly 100–150 ms when the native toolkit can support it cleanly.
- Small disclosures: roughly 200–300 ms where motion is useful; otherwise immediate native disclosure is acceptable.
- No decorative looping animation.
- No movement that delays high-frequency actions.
- Parsing/downloading must expose explicit states: idle → parsing → ready → queued/downloading → complete/error.
- Errors must include the next useful action.

## Acceptance gates

- Actual `GalaxyLocalEngine.exe` screenshot required for UI sign-off.
- No visible action outside the window bounds.
- Operational body text uses the shared body token or larger.
- Primary actions remain obvious in grayscale/squint review.
- Buttons and important targets stay comfortably clickable at Windows DPI scaling.
- Keyboard focus remains visible.
- The UI remains usable around 1020×720 and scales up cleanly to normal desktop sizes.
- A prototype is never accepted as proof that the native EXE is fixed.
