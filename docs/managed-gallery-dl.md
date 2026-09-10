# Managed gallery-dl

Galaxy Local Engine treats gallery-dl as an optional managed tool.

- Provider metadata is fetched only from `https://pypi.org/pypi/gallery-dl/json`.
- Only a stable numeric release with exactly one `py3-none-any` wheel is accepted.
- Wheel bytes must come from `files.pythonhosted.org` over HTTPS and match the SHA-256 supplied by PyPI.
- The wheel is never executed as an installer. It is extracted with Galaxy's bounded safe archive implementation.
- The staged package version must match the provider version and Galaxy provenance metadata is written before atomic promotion.
- Existing managed gallery-dl remains untouched if download, extraction, validation, metadata, or promotion fails.
- gallery-dl is optional: absence is reported as a dependency warning, not a failure of core yt-dlp/FFmpeg readiness.

## Download Archive boundary

Gallery-dl download Archive is opt-in and disabled by default.

- Local executor callers may enable it only with the boolean `archive_enabled` contract.
- Authenticated Headless clients may enable it only with JSON `archiveEnabled: true`; strings, numbers, objects, and arbitrary archive path fields are rejected.
- Headless status exposes only the `archiveSupported` capability flag. It never returns the local state directory or Archive database path.
- Galaxy derives the database exclusively from the trusted platform state root as `state_dir/gallery-dl/archive.sqlite3`.
- A configured state root, managed Archive directory, or Archive file that violates the executor's symlink/non-regular path checks is rejected before gallery-dl runs.
- Retry reuses the same managed Archive while each attempt keeps its own output directory.
- A successful Archive-enabled run with zero new files is a valid completed state because all discovered items may already be archived.
