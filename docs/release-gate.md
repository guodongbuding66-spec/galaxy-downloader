# Production Release Gate

This document defines the release path for changes that can affect first-party parsing or media delivery.

## Target flow

```text
PR
  -> CI / security / build
  -> isolated Preview or Staging deployment
  -> First-party PR Media Gate / Staging real-media smoke
  -> required checks green
  -> merge main
  -> production deployment
  -> First-party Production Smoke
  -> alert / rollback policy on failure
```

The production Worker must never be used as the pre-merge staging target. A smoke run against production before merge only proves the old production revision, not the PR revision.

## 1. Staging target

Create an isolated Cloudflare Worker / Preview deployment for candidate revisions and expose its HTTPS base URL as the repository variable:

```text
GALAXY_STAGING_BASE_URL
```

Example shape only:

```text
https://<isolated-staging-worker>.workers.dev
```

Do not set this variable to:

```text
https://galaxy-downloader.guodongbuding66.workers.dev
```

`.github/workflows/first-party-pr-media-gate.yml` deliberately fails if the variable is missing, non-HTTPS, or points at the production Worker.

## 2. What the PR media gate verifies

`scripts/local-parser-production-smoke.py` is shared by staging and production checks. A platform passes only when:

1. the parser returns HTTP 200 and `success=true`;
2. the normalized platform matches the expected fixture;
3. the response contains a downloadable media URL;
4. HLS playlists are followed through child playlists;
5. a real non-text media segment / media body can be read.

The smoke output also reports parse time, media time, and HLS depth so control-plane timeout and CDN/media failures can be distinguished.

Current permanent first-party fixtures include:

- Vimeo
- Dailymotion
- Apple Podcasts

## 3. Main branch rules

Configure a GitHub repository Ruleset for `main` with at least:

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
First-party PR Media Gate / Staging real-media smoke
```

Add other existing Windows / container / release checks as required if they are relevant to the changed paths.

## 4. Production verification

`.github/workflows/local-parser-production-smoke.yml` remains a post-deploy protection layer. It runs against:

```text
https://galaxy-downloader.guodongbuding66.workers.dev
```

This workflow must not replace the pre-merge staging gate.

## 5. Rollback contract

Before enabling automatic rollback, production deployment must expose an immutable previous-good deployment identifier. The rollback controller must:

1. record the deployment identifier that passed the previous Production Smoke;
2. deploy the new `main` revision;
3. run Production Smoke;
4. if it fails, restore only the recorded previous-good deployment;
5. run Production Smoke again against the restored deployment;
6. surface an alert containing the failed commit SHA and smoke diagnostics.

Do not implement rollback as a blind `git revert` after production failure. Source rollback and Cloudflare deployment rollback are separate operations and can diverge.

## 6. Release-version consistency

`tests/local-engine-version-sync.test.ts` prevents the Local Engine release version from drifting between:

- `local-engine/VERSION`;
- `src/lib/local-engine.ts`;
- the official download route;
- `README.md`.

A release should not merge while this test is red.
