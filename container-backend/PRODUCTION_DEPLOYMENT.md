# Container backend production deployment

The first-party media backend is a separate Cloudflare Worker named `galaxy-downloader-backend`. It is not deployed by the frontend `galaxy-downloader` Workers Build.

## Deployment safety model

Production deployment is intentionally opt-in.

The repository workflow `.github/workflows/container-backend-deploy.yml` can run in two ways:

1. **Manual deployment** — run `Container Backend Deploy` from the `main` branch.
2. **Automatic deployment** — after `Container Backend CI` succeeds on `main`, but only when repository variable `CONTAINER_BACKEND_AUTO_DEPLOY` is exactly `true`.

The deployment concurrency group uses `cancel-in-progress: false`. A Container deploy can publish Worker code before the image build/rollout has fully completed, so an in-progress production rollout must not be cancelled just because another commit arrived.

## Required GitHub repository secrets

Add these in GitHub repository settings before the first deployment:

- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`

The API token should be scoped to the Cloudflare account that owns the Worker and should have only the permissions required to deploy Workers/Containers. Never commit either value.

If either secret is missing, a manually requested deployment fails immediately with a clear credential error. Automatic deployment remains disabled unless the repository variable below is enabled.

## Recommended GitHub repository variables

### `CONTAINER_BACKEND_AUTO_DEPLOY`

Default: unset / disabled.

Set to:

```text
true
```

only after the first production deployment has been verified.

### `CONTAINER_BACKEND_HEALTH_URL`

Set this to the deployed backend origin, without `/health`, for example:

```text
https://galaxy-downloader-backend.<your-workers-subdomain>.workers.dev
```

When configured, the deployment workflow waits for:

```text
GET <CONTAINER_BACKEND_HEALTH_URL>/health
```

to succeed after `wrangler deploy`. The workflow retries for up to roughly five minutes because first-time Container provisioning and later rollouts can take time.

## First deployment procedure

1. Confirm the Cloudflare account has access to Workers Containers and that the expected paid-plan/cost implications are acceptable.
2. Add `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` as GitHub repository secrets.
3. Keep `CONTAINER_BACKEND_AUTO_DEPLOY` disabled.
4. From GitHub Actions, manually run `Container Backend Deploy` on `main`.
5. Confirm Wrangler creates/updates Worker `galaxy-downloader-backend` and completes the Container image rollout.
6. Open the backend `/health` endpoint and confirm `ok: true`, yt-dlp, FFmpeg and Node runtime availability.
7. Set `CONTAINER_BACKEND_HEALTH_URL` to the verified backend origin.
8. Run the deployment workflow once more and confirm its post-deploy health check succeeds.
9. Only then set `CONTAINER_BACKEND_AUTO_DEPLOY=true` if automatic production deployment is desired.

## Backend runtime secrets

The Worker deploy and the media runtime secrets are separate concerns. Provision sensitive runtime values through Cloudflare secrets, not `wrangler.jsonc`.

Common optional secrets/settings include:

- `YTDLP_COOKIES_B64`
- `YTDLP_PROXY`
- `YTDLP_YOUTUBE_PROXY`
- `YTDLP_XHS_PROXY`
- `YTDLP_RUMBLE_PROXY`
- `YTDLP_USER_AGENT`
- `XHS_RESOLVER_URL`
- `XHS_RESOLVER_TOKEN`

Non-sensitive defaults such as XHS circuit-breaker policy, media stream ceiling, API rate limits, parse/download concurrency, and queue wait limits are committed in `wrangler.jsonc` and validated in CI.

## Frontend connection

Deploying this Worker does not automatically switch browser traffic to it.

After the backend origin is verified, configure the frontend build variable:

```text
NEXT_PUBLIC_CONTAINER_API_BASE_URL=https://galaxy-downloader-backend.<your-workers-subdomain>.workers.dev
```

The current frontend treats the Container backend as an additional media candidate. Do not replace `NEXT_PUBLIC_API_BASE_URL` merely to switch media parsing: the existing primary API also serves non-media endpoints such as feedback and statistics.

After changing a `NEXT_PUBLIC_*` variable, rebuild/redeploy the frontend because it is embedded at build time.

## Rollout notes

`wrangler deploy` for a Worker with Containers can update Worker code before the associated Container image rollout has fully finished. New Worker code may briefly communicate with older Container instances during a rollout. Keep Worker/Container protocol changes backward-compatible across at least one rollout boundary.

The production deploy workflow therefore:

- runs only after backend CI for automatic deployments;
- never auto-cancels an in-progress production deploy;
- revalidates Wrangler configuration and TypeScript before deployment;
- verifies Docker availability before asking Wrangler to build/publish the image;
- optionally performs post-deploy `/health` verification.
