# gallery-dl managed action policy

Managed gallery-dl lifecycle operations must flow through `managed_tool_actions.py`.

| Action | Network | Mutates managed tool | User initiation required |
| --- | --- | --- | --- |
| `check` | yes | no | yes |
| `install` | yes | yes | yes |
| `update` | yes | yes | yes |
| `remove` | no | yes | yes |

`gallery-dl` intentionally does not expose `seed` or `reset`: there is no bundled gallery-dl baseline in release packages. Removing the managed package returns the tool to the optional/unavailable state.

Update checks compare the currently installed Galaxy provenance metadata with the fixed trusted PyPI project source. Matching release tags must also match wheel identity and SHA-256. A provider mismatch, missing ordering metadata, or ambiguous release identity is never guessed into an update recommendation.

The Desktop tool manager and future Headless/Task Center integrations must consume this action contract rather than calling the installer or remover directly.
