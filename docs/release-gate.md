# Production Release Gate

This document defines the release path for changes that can affect first-party parsing or media delivery.

## Target flow

```text
PR candidate revision
  -> CI / security / build
  -> deploy exact candidate to isolated galaxy-downloader-staging Worker
  -> First-party PR Media Gate / Staging real-media smoke
  -> required checks green
  -> merge main
  -> production deployment
  -> First-party Production Smoke
  -> alert / rollback policy on failure
```

The production Worker must never be used as the pre-merge target. A smoke run against production before merge only proves the old production revision, not the PR revision.

## 1. Why this project uses a staging Worker instead of a Preview URL

`wrangler.jsonc` binds the `ParseStats` and `ProxyRateLimiter` Durable Objects. Cloudflare Worker Preview URLs are not generated for Workers that implement Durable Objects, so a `wrangler versions upload --preview-alias ...` gate cannot provide a usable preview URL for this application.

The PR gate therefore deploys the current candidate to a separate Worker:

```text
galaxy-downloader-staging
```

Expected public staging endpoint:

```text
https://galaxy-downloader-staging.guodongbuding66.workers.dev
```

This is a normal Worker deployment, but it is isolated from the production Worker name `galaxy-downloader`. The workflow explicitly refuses to deploy if the staging name is changed to the production name.

Because all media-sensitive PRs share this staging Worker, the workflow uses a repository-wide concurrency group. A newer candidate cancels an older in-progress staging run instead of allowing two PRs to overwrite the same staging target concurrently.

## 2. Required repository secrets

The staging deployment requires these GitHub Actions repository secrets:

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
```

The API token should use the minimum Cloudflare permissions required to deploy the isolated staging Worker in this account.

The workflow exposes the credentials only to the credential-validation and deploy steps. It refuses to use Cloudflare credentials for pull requests coming from external forks.

If either secret is missing, the staging gate fails explicitly. It must not silently skip the deployment or media test.

## 3. What the PR media gate verifies

`scripts/local-parser-production-smoke.py` is shared by staging and production checks. A platform passes only when:

1. the parser returns HTTP 200 and `success=true`;
2. the normalized platform matches the expected fixture;
3. the response contains a downloadable media URL;
4. HLS playlists are followed through child playlists;
5. a real non-text media segment / media body can be read.

The smoke output reports parse time, media time, and HLS depth so control-plane timeout and CDN/media failures can be distinguished.

Current permanent first-party fixtures include:

- Vimeo
- Dailymotion
- Apple Podcasts

A parser-only success is not enough. For example, `Dailymotion metadata -> HLS CDN 403` must remain a failed smoke.

## 4. Main branch rules

Configure a GitHub repository Ruleset or Branch Protection for `main` with at least:

- require a pull request before merging;
- require status checks to pass;
- block force pushes;
- block branch deletion;
- require branch to be up to date before merge when practical.

Minimum required checks for media-sensitive PRs:

```text
CI / validate
CI / CodeQL (javascript-typescript)
CI / CodeQL (python)
Security Audit / JavaScript dependency audit
Security Audit / Python dependency audit (local-engine/requirements.txt)
Security Audit / Python dependency audit (container-backend/requirements.txt)
Security Audit / Python dependency audit (container-backend/requirements-dev.txt)
First-party PR Media Gate / Staging real-media smoke
```

Add existing Windows / container / release checks as required when their changed paths are involved.

Do not mark a media-sensitive PR mergeable while the Staging real-media smoke is missing, skipped, or failed.

## 5. Production verification

`.github/workflows/local-parser-production-smoke.yml` remains the post-deploy protection layer. It runs against:

```text
https://galaxy-downloader.guodongbuding66.workers.dev
```

Production Smoke is the second line of defense. It must not replace the pre-merge staging gate.

## 6. Rollback contract

Before enabling automatic rollback, production deployment must expose an immutable previous-good deployment identifier. The rollback controller must:

1. record the deployment identifier that passed the previous Production Smoke;
2. deploy the new `main` revision;
3. run Production Smoke;
4. if it fails, restore only the recorded previous-good deployment;
5. run Production Smoke again against the restored deployment;
6. surface an alert containing the failed commit SHA and smoke diagnostics.

Do not implement rollback as a blind `git revert` after production failure. Source rollback and Cloudflare deployment rollback are separate operations and can diverge.

## 7. Release-version consistency

`tests/local-engine-version-sync.test.ts` prevents the Local Engine release version from drifting between:

- `local-engine/VERSION`;
- `src/lib/local-engine.ts`;
- the official download route;
- `README.md`.

A release should not merge while this test is red.
