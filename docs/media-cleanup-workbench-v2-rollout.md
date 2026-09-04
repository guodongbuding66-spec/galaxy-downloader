# Workbench 2.0 rollout boundary

This slice wires the already-tested cleanup cores into the desktop workbench.

Included:
- image inpainting execution
- fixed-video cleanup
- moving-video temporal tracking cleanup
- user-confirmed automatic suggestions
- cooperative cancellation and progress
- same-frame Before/After comparison

Not included in this slice:
- Batch Task Center desktop UI
- HTTP routes
- remote/background cleanup execution

Those remain separate reversible changes.
