# Production Release Gate

This document defines the release path for changes that can affect first-party parsing or media delivery.

## Target flow

```text
PR candidate revision
  -> CI / security / build
  -> upload isolated Cloudflare Worker Preview Version
  -> First-party PR Media Gate / Preview real-media smoke
  -> required checks green
  -> merge main
  -> production deployment
  -> First-party Production Smoke
  -> alert / rollback policy on failure
```

The production Worker must never be used as the pre-merge target. A smoke run against production before merge only proves the old production revision, not the PR revision.

## 1. PR Preview deployment

`.github/workflows/first-party-pr-media-gate.yml` builds the current PR revision and uploads that exact candidate as a Cloudflare Worker Preview Version.

The preview alias is scoped to the PR:

```text
pr-<pull-request-number>
```

The workflow then parses the HTTPS `workers.dev` Preview URL returned by Wrangler and runs the real-media smoke against that URL. It explicitly rejects the production URL.

This removes the stale-staging problem: a fixed staging address can accidentally contain an older revision, while a PR Preview Version is tied to the candidate currently being reviewed.

### Required repository secrets

The Preview deployment requires these GitHub Actions repository secrets:

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
```

The API token should use the minimum Cloudflare permissions required to upload Worker versions for this Worker/account. Do not expose these credentials as global job environment variables.

The workflow exposes them only to the credential-validation and Preview-upload steps. It also refuses to use Cloudflare credentials for pull requests coming from external forks.

If either secret is missing, the Preview gate fails explicitly. It must not silently skip the media test.

## 2. What the PR media gate verifies

`scripts/local-parser-production-smoke.py` is shared by Preview and production checks. A platform passes only when:

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

## 3. Main branch rules

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
First-party PR Media Gate / Preview real-media smoke
```

Add existing Windows / container / release checks as required when their changed paths are involved.

Do not mark a media-sensitive PR mergeable while the Preview real-media smoke is missing, skipped, or failed.

## 4. Production verification

`.github/workflows/local-parser-production-smoke.yml` remains the post-deploy protection layer. It runs against:

```text
https://galaxy-downloader.guodongbuding66.workers.dev
```

Production Smoke is the second line of defense. It must not replace the pre-merge Preview gate.

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
