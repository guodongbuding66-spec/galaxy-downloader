# Third-Party Notices

Galaxy is distributed under the GNU General Public License v3.0 only (`GPL-3.0-only`).

This project may copy, adapt, or integrate source code from the projects listed below. When source is copied or adapted, Galaxy keeps the upstream copyright/license notices required by the original license and records the upstream path/commit in the affected source file or integration note where practical.

## VidBee

- Project: VidBee
- Repository: https://github.com/nexmoe/VidBee
- License: MIT
- Upstream revision used as the initial Galaxy integration baseline: `feeea6b2b5f451e62774c87c25f3056d583f494f`
- Copyright and MIT permission notices from VidBee remain applicable to copied/adapted VidBee material.

VidBee's MIT-licensed material is included in Galaxy under the terms of its original MIT license; the Galaxy distribution as a whole remains GPL-3.0-only.

Current direct/adapted integration:

- `local-engine/aria2_transfer.py`: lifecycle/state/retry semantics adapted from `packages/task-queue/src/api/index.ts` at the revision above.

## OmniGet

- Project: OmniGet
- Repository: https://github.com/OpenSelena/omniget
- License: GNU General Public License v3.0
- Upstream revision used as the initial Galaxy integration baseline: `73289076c7b4eade5eb85ab6f3948e30cec96a5e`

Copied or adapted OmniGet material remains subject to GPL-3.0 requirements and is distributed as part of Galaxy under GPL-3.0-only.

Current direct/adapted integration:

- `local-engine/aria2_transfer.py`: aria2 command construction and progress parsing adapted from `src-tauri/omniget-core/src/core/tools/aria2.rs` at the revision above.
- Galaxy also keeps OmniGet's current security boundary that HLS/DASH fragmented manifests are not handed directly to aria2c.

## Provenance policy

For future direct imports, prefer an in-source provenance header in this form:

```text
Upstream: <repository URL>
Upstream path: <path>
Upstream revision: <commit SHA>
License: <SPDX identifier>
Galaxy modifications: <short description and date>
```

Generated assets, bundled binaries, and independent third-party libraries may have their own licenses. Their existing notices must not be removed.
