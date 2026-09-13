# Accessibility

## Baseline

Galaxy Desktop is a productivity application. Keyboard use, readable state and predictable focus are part of functional correctness.

## Keyboard

- Every actionable control must be reachable without a mouse.
- Tab order follows visual/task order.
- Native buttons/selects/checkboxes are preferred because they carry keyboard behavior by default.
- Enter/Space activate controls according to platform convention.
- Escape closes non-destructive dialogs where safe.
- Do not trap focus inside an ordinary panel.

## Focus

- Focus must be visible.
- Focus color derives from `color.focus` and must contrast with both control and surrounding surface.
- Do not remove native focus behavior unless replaced by an equally visible state.
- Opening a dialog places focus on the first useful control or the dialog heading/primary region as appropriate.

## Labels and names

- Inputs, selects and toggles require visible text labels.
- Icon-only actions require an accessible/tooltip name.
- Do not use placeholder text as the only field name.
- Status messages should name the object/action when ambiguity is possible.

## Color and contrast

- Color is never the only state signal.
- Primary/secondary text must remain readable against its background.
- Success/warning/error pair color with icon, label or wording.
- Disabled state uses both visual treatment and actual disabled interaction state.

## Text and scaling

- Avoid fonts below the documented caption scale for meaningful content.
- Do not compress critical labels to fit a fixed card; allow layout growth/wrapping.
- Verify common Windows scaling settings and platform font fallbacks.
- Tables should preserve access to full values through expansion, detail view or copy action when text is truncated.

## Target size

Aim for approximately 44 px hit targets for primary touch/click actions when layout permits. Compact desktop toolbar controls may be smaller, but should retain comfortable padding and separation.

## Dynamic state

- Busy state disables duplicate submission where needed.
- Progress updates must not steal keyboard focus.
- Toast/status updates should not continuously reflow the primary form.
- Errors stay visible long enough to read and provide a recovery action.

## Motion

Follow `MOTION.md`. Reduced motion must not remove information or block completion.

## Media-specific requirements

- Transcript search results expose matching text and timestamp.
- Player seek from transcript must have a text/action equivalent, not only clickable colored words.
- Subtitle/transcript exports use explicit format names.
- Speaker labels should be text, not only speaker colors.

## QA checklist

For each changed Desktop surface:

1. Complete the primary workflow keyboard-only.
2. Verify focus indicator on every interactive control.
3. Verify disabled/busy states.
4. Verify visible labels for fields and icon-only actions.
5. Verify state remains understandable in grayscale/color-blind conditions.
6. Verify empty/error/loading text.
7. Verify no secret/path leakage through status or error UI.
8. Run relevant UI smoke/contract tests on Windows and at least one non-Windows platform where supported.
