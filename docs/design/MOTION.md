# Motion

## Purpose

Motion communicates state change; it must not decorate routine work or hide latency.

## Durations

- Fast: 100 ms — hover/focus feedback where supported.
- Normal: 180 ms — small reveal/selection transitions.
- Slow: 260 ms — drawers, larger view transitions.

Avoid animation longer than 300 ms for ordinary desktop interactions.

## Easing

- Enter/state confirmation: ease-out.
- Reversible movement: ease-in-out.
- Continuous progress: linear only when animation genuinely represents ongoing work.

## Allowed patterns

- Subtle hover/focus feedback.
- Progress indicators for indeterminate work.
- Drawer/panel reveal when it improves spatial understanding.
- Brief toast entrance/exit.
- Queue item state transition without reflow jumps.

## Avoid

- Animated gradients/glows.
- Bouncy spring motion in productivity surfaces.
- Repeated pulsing for normal status.
- Moving controls while the user may click them.
- Fake progress tied only to elapsed time.
- Animating large lists during bulk updates.

## Download/process state

State transitions must remain explicit in text:

`queued → preparing → downloading → merging/post-processing → completed`

Alternative states include `paused`, `retrying`, `cancelled`, and `failed`.

Animation may support these states but never replace the label, progress value, speed or ETA where available.

## Reduced motion

Where reduced-motion preference is detectable, disable nonessential transitions. All workflows must remain fully usable with motion removed.

## Performance

- Never run animation loops that contend with download/process workers.
- Avoid high-frequency Tk timers when a state event can update the UI directly.
- Batch list/table updates where practical.
- Do not animate expensive image resizing or full-window redraws.
