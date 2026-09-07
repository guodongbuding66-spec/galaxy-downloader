# Managed gallery-dl

Galaxy Local Engine treats gallery-dl as an optional managed tool.

- Provider metadata is fetched only from `https://pypi.org/pypi/gallery-dl/json`.
- Only a stable numeric release with exactly one `py3-none-any` wheel is accepted.
- Wheel bytes must come from `files.pythonhosted.org` over HTTPS and match the SHA-256 supplied by PyPI.
- The wheel is never executed as an installer. It is extracted with Galaxy's bounded safe archive implementation.
- The staged package version must match the provider version and Galaxy provenance metadata is written before atomic promotion.
- Existing managed gallery-dl remains untouched if download, extraction, validation, metadata, or promotion fails.
- gallery-dl is optional: absence is reported as a dependency warning, not a failure of core yt-dlp/FFmpeg readiness.
