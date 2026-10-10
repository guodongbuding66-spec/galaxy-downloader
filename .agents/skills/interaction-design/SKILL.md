---
name: interaction-design
description: Design purposeful microinteractions, state transitions and feedback for the Galaxy Local Engine UI.
source: https://www.ui-skills.com/skills/wshobson/interaction-design
upstream: https://github.com/wshobson/agents
install-mode: project-local
---

# Interaction Design

Motion communicates state; it does not decorate the interface.

## Apply when

- Buttons need hover, pressed, focus or disabled feedback.
- Parsing/downloading needs loading, progress, success or error feedback.
- Drawers, advanced options, queue sections or previews expand/collapse.
- A transition helps the user understand where content came from or where it went.

## Timing

- 100-150 ms: hover, press, focus and other micro-feedback.
- 200-300 ms: toggles, dropdowns and compact disclosure transitions.
- 300-500 ms: larger panels or modal transitions only when they improve orientation.

## Galaxy rules

- High-frequency desktop actions must feel immediate and quiet.
- Prefer color, border, opacity and small positional changes over zoomy or spring-heavy motion.
- Do not use looping decorative animation, ripples, glow pulses or background motion.
- Never block interaction while an animation is running.
- Loading states must preserve layout and clearly state what the engine is doing.
- Error states must explain the next action rather than only changing color.
- Respect reduced-motion settings where the platform/runtime exposes them.
- Native Tk implementation takes precedence over web-animation examples from the upstream skill.
