# Security Policy

## Supported versions

Security fixes are applied to the current `main` branch and the latest published Galaxy Local Engine release when the issue affects the Windows helper.

## Reporting a vulnerability

Do not publish exploit details, authentication material, private URLs, cookies, tokens, or user data in a public discussion.

Prefer GitHub private vulnerability reporting / Security Advisories for this repository when that option is available. If private reporting is unavailable, contact the repository maintainer through GitHub and share only enough public information to establish contact; provide sensitive reproduction details privately afterward.

A useful report should include:

- affected component and version or commit;
- impact and realistic attack prerequisites;
- minimal reproduction steps;
- whether the issue is remotely exploitable or requires local access/authentication;
- any known workaround;
- suggested remediation, if available.

## Security-sensitive areas

Changes in these areas should receive extra review and complete CI/security checks before merge:

- `.github/workflows/` and release automation;
- `src/app/api/proxy-image/`, `src/app/api/proxy-media/`, and other server-side fetch/proxy routes;
- `worker/` Cloudflare request handling and abuse controls;
- `local-engine/` browser authentication, protocol handling, subprocess execution, URL policy, downloads, updates, and Windows packaging;
- `container-backend/` network fetching, playback, parser execution, and container entrypoints.

## Baseline expectations

- Public URL fetches must fail closed for private, loopback, link-local, reserved, credentialed, and unsafe redirect targets.
- Remote content returned from a Galaxy same-origin endpoint must use an explicit safe content-type policy and `nosniff` where appropriate.
- Download/proxy byte limits must be enforced on the actual streamed body, not only `Content-Length`.
- Shell/subprocess arguments must remain structured and must not concatenate untrusted input into a shell command.
- Secrets and browser cookies must never be written to logs or committed to the repository.
- Release artifacts must continue to publish checksums and be built only after validation succeeds.
