---
name: web-artifacts-builder
description: Build high-fidelity interactive web prototypes when a complex multi-component design comp is useful before native implementation.
source: https://github.com/anthropics/skills/tree/main/skills/web-artifacts-builder
license: See upstream LICENSE.txt
install-mode: project-local-guidance
---

# Web Artifacts Builder

Use this skill for complex interactive prototypes that benefit from React, TypeScript, routing, state management or reusable UI components.

## Galaxy Local Engine scope

The shipping product is the native Windows `GalaxyLocalEngine.exe`. A web artifact is a design/prototyping surface only unless the user explicitly asks to change the product architecture.

Do not repeat the previous mistake of replacing the native application with a browser wrapper or a localhost dashboard launcher.

## Prototype workflow

1. Preserve the real product information architecture and operations.
2. Prototype the target workbench at realistic desktop sizes.
3. Verify hierarchy, copy, density, states and interactions visually.
4. Treat the prototype as implementation evidence for the native Tk UI.
5. Port the approved design into the native application and validate the actual EXE separately.

## Design guidance from upstream

Avoid generic AI aesthetics: excessive centered layouts, purple gradients, uniform rounded corners, ornamental glass effects and default-looking typography. Do not use Inter as a reflex. Prefer a deliberate visual system tied to the product and platform.

For Galaxy, prototype with a Windows utility mindset: compact but readable, low-noise surfaces, strong task hierarchy, clear status feedback and one restrained accent color.
