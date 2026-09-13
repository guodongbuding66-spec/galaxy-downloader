# Core Components

This document defines behavior contracts. Platform implementations may use Tk, web controls or another native toolkit, but semantics should stay consistent.

## Button

Variants: primary, secondary, ghost, danger.

Required states: default, hover where supported, keyboard focus, disabled, busy when the action owns an in-flight operation.

Rules:
- Use a verb/action label.
- One dominant primary action per local group.
- Busy actions prevent accidental duplicate submission.

## IconButton

Use only for familiar compact actions. Requires tooltip/accessibility label and a practical hit target. Destructive icon-only actions require a confirmation or adjacent explicit context.

## Input

Visible label, persistent value, keyboard focus indication and error/helper text. Placeholder is optional supporting text, never the only label.

Readonly output must look distinct from disabled input and remain copyable where practical.

## Select / Combobox

Use for a constrained set of mutually exclusive values. Default must be visible. Disabled state must explain dependency when non-obvious.

## Checkbox

Use for independent boolean options such as archive, subtitles or auto chunk. Label describes the enabled behavior, not implementation jargon.

## Switch

Reserve for immediate on/off preferences. Do not use a switch for actions that require a separate Save/Apply step unless the whole form follows that model.

## Segmented Control

Use for 2–4 mutually exclusive modes when switching changes the current view/result immediately. Selected state must be obvious without relying only on color.

## Tabs

Use for sibling workflows within one product area, such as Transfer Center modes. Preserve state when changing tabs unless documented otherwise. Keyboard traversal must remain available through the underlying platform control.

## Sidebar Item

Contains icon + visible label; optional badge/status. Active state uses at least two cues (for example color + text weight/border).

## Table / List

- Stable columns/row identity.
- Sort direction visible when sortable.
- Empty state occupies the table region rather than leaving a blank rectangle.
- Bulk selection exposes explicit selection count and bounded batch actions.
- Long filenames/URLs truncate visually while preserving access to full value.

## Progress

Determinate progress shows percent when known; download/process surfaces should also expose phase, speed and ETA when available. Indeterminate progress is allowed only when total work is genuinely unknown.

## Toast

For brief non-blocking confirmation or recoverable notification. Do not put critical destructive confirmation or long error diagnostics only in a toast.

## Dialog

Use for focused decisions, configuration or blocking confirmation. Initial keyboard focus should be deliberate. Escape closes non-destructive dialogs where safe. Closing an owning dialog should release ephemeral sessions/workers where applicable.

## Drawer

Use for contextual detail or filters without replacing the primary workspace. Do not nest drawers.

## Tooltip

Supports icon-only or abbreviated controls. It is supplemental and must not contain the only critical instruction.

## Empty State

Contains: concise reason, next useful action when one exists, and no fake sample data. Keep illustration/icon secondary.

## Skeleton

Use only while layout/data shape is known and expected quickly. For long local processing prefer explicit phase/progress text.

## Error State

Contains:
- what failed in user terms
- safe detail when useful
- retry/corrective action
- retained user input/state where possible

Do not surface Bot Tokens, cookies, local secret file paths or raw adapter command lines.

## Component implementation priority

1. Reuse existing shared implementation (`ActionButton`, shared labels/styles, native ttk controls).
2. Extend the shared component/token layer.
3. Introduce a one-off control only when a documented semantic component cannot represent the interaction.
