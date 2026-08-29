# XHS Resolver Deployment

This directory contains an **optional, separately deployed Xiaohongshu resolver** for Galaxy Downloader.

Galaxy does not copy or embed the resolver source code. The Compose stack builds the upstream `komens/XHS-Downloader-web` project at the pinned commit below and communicates with it only over HTTP:

- upstream repository: `komens/XHS-Downloader-web`
- pinned commit: `7a9ff055ac66623ac4f51c56ad2c2996f9e0cc3f`
- upstream license: GPL-3.0
- resolver API: `POST /xhs/detail`
- internal port: `5556`

Keeping the resolver as an independent network service avoids coupling GPL code, browser/login state, and Xiaohongshu-specific behavior to the generic yt-dlp Container.

## Architecture

```text
Galaxy Worker
    |
    | HTTPS + Authorization: Bearer <token>
    v
Caddy gateway
    |
    | private Docker network
    v
XHS-Downloader-web :5556
    |
    v
Xiaohongshu / xhscdn.com
```

Only Caddy publishes ports `80/443`. The Python resolver is not directly exposed on the host.

## Requirements

- Linux server or NAS with Docker Engine + Docker Compose v2
- a DNS record such as `xhs-resolver.example.com` pointing to the server
- inbound TCP 80/443 and UDP 443 allowed for Caddy/ACME
- outbound HTTPS access to Xiaohongshu/CDN hosts

For production, use a server/egress region that can reliably access Xiaohongshu. If the resolver needs logged-in state, configure it inside its persistent `/app/Volume` data volume. Do not commit cookies or session data to Galaxy.

## Deploy

```bash
cd deploy/xhs-resolver
cp .env.example .env
```

Edit `.env` and set at least:

```dotenv
XHS_RESOLVER_DOMAIN=xhs-resolver.example.com
XHS_RESOLVER_TOKEN=<long-random-token>
ACME_EMAIL=admin@example.com
```

Generate a token, for example:

```bash
openssl rand -hex 32
```

Then build and start:

```bash
docker compose build --pull
docker compose up -d
```

Check the public gateway:

```bash
curl --fail https://xhs-resolver.example.com/healthz
```

Expected body:

```text
ok
```

Unauthenticated resolver requests must fail:

```bash
curl -i -X POST https://xhs-resolver.example.com/xhs/detail \
  -H 'Content-Type: application/json' \
  --data '{"url":"https://www.xiaohongshu.com/explore/example","download":false}'
```

Expected status: `401`.

Authenticated request:

```bash
curl --fail-with-body -X POST https://xhs-resolver.example.com/xhs/detail \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  --data '{"url":"YOUR_REAL_XHS_TEST_URL","download":false}'
```

The resolver should return JSON containing `data` and at least one downloadable media URL.

## Configure Galaxy Worker

From `container-backend/` set the sensitive values as Cloudflare secrets:

```bash
npx wrangler secret put XHS_RESOLVER_URL
# value: https://xhs-resolver.example.com

npx wrangler secret put XHS_RESOLVER_TOKEN
# value: the same token from deploy/xhs-resolver/.env
```

Recommended initial mode:

```text
XHS_RESOLVER_MODE=fallback
```

`fallback` preserves the normal yt-dlp route and only invokes the specialized resolver after XHS extraction fails. After enough production data shows the resolver is more reliable, `prefer` can be enabled without changing frontend code.

Other optional Worker variables:

```text
XHS_RESOLVER_TIMEOUT_MS=20000
XHS_MEDIA_HOST_SUFFIXES=xhscdn.com,xiaohongshu.com
XHS_MAX_STREAM_BYTES=6442450944
XHS_RESOLVER_FAILURE_THRESHOLD=3
XHS_RESOLVER_COOLDOWN_MS=30000
```

Do not widen `XHS_MEDIA_HOST_SUFFIXES` unless a verified resolver response demonstrates a legitimate new Xiaohongshu CDN hostname.

## Persistent resolver settings

The upstream application persists configuration and account state below `/app/Volume`, backed by the Compose volume `xhs_resolver_volume`.

Inspect it with:

```bash
docker compose exec xhs-resolver sh -lc 'ls -la /app/Volume && find /app/Volume -maxdepth 2 -type f -print'
```

If a Xiaohongshu cookie/session is required for higher-quality or protected works, configure it in the upstream application's settings. Keep that state only in the resolver volume or another secret store.

## Update upstream safely

Do **not** switch the Compose build context to an unpinned `main` branch in production.

To upgrade:

1. inspect the new upstream release/commit and API compatibility;
2. change the commit after `#` in `compose.yaml`;
3. run Galaxy's XHS resolver contract tests;
4. run the dedicated live smoke workflow with a real test URL;
5. only then replace the running resolver image.

```bash
docker compose build --pull --no-cache xhs-resolver
docker compose up -d --no-deps xhs-resolver
```

## Operations

View status and logs:

```bash
docker compose ps
docker compose logs --tail=200 xhs-resolver
docker compose logs --tail=200 gateway
```

Restart only the resolver:

```bash
docker compose restart xhs-resolver
```

Back up the persistent volume before upgrades that change resolver data formats.

## Security notes

- Keep `XHS_RESOLVER_TOKEN` out of Git.
- Do not publish port `5556` directly.
- The public `/healthz` endpoint only returns `ok`; resolver APIs require the Bearer token.
- Galaxy independently validates returned media hosts and redirect targets, so the resolver cannot turn `/api/download` into an arbitrary URL proxy.
- Place an additional firewall, Cloudflare Access, or IP allowlist in front of the resolver when the deployment topology permits it.
