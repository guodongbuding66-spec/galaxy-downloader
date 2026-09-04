# Implementation notes

The V2 presenter is intentionally patched into the existing workbench hook rather than replacing the hook itself. This preserves the established toolbar button, cancellation flag, and graceful-exit behavior.
