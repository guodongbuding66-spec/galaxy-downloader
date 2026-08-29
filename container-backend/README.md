# Galaxy Downloader Container Backend

First-party media backend for Galaxy Downloader. It runs `yt-dlp`, FFmpeg, a current Node.js runtime and `curl_cffi` inside a Cloudflare Container so parsing and downloading happen from the same server/network path.

The Worker in front of the Container also owns lightweight platform-provider routing. This keeps specialized resolvers and streaming transports out of the generic FastAPI/yt-dlp process.

## Why this backend exists

The public/shared parser can successfully parse many platforms but some temporary CDN URLs are bound to the parser IP, some providers intermittently fail, and several sites require browser TLS impersonation, cookies, a proxy, a current JavaScript runtime, or platform-specific anti-bot handling. This backend keeps extraction and download on the same machine and exposes the frontend-compatible endpoints:

- `GET /health`
- `GET /api/parse?url=<source>`
- `GET /api/download?url=<source>&type=video|audio&quality=best&formatId=<optional>`

## Runtime

- Python 3.11+
- yt-dlp 2026.08.19 with default optional dependencies
- `curl_cffi==0.15.0`, pinned to a release supported by yt-dlp browser impersonation
- `yt-dlp-ejs`
- Node.js >= 22 explicitly enabled through `--js-runtimes node`
- `bgutil-ytdlp-pot-provider==1.3.2`
- an in-container bgutil HTTP PO-token provider on `127.0.0.1:4416`
- YouTube `mweb` client configured to consume generated PO tokens
- FFmpeg / ffprobe
- FastAPI + Uvicorn
- Cloudflare Worker provider router and streaming tunnel for optional specialized platform resolvers

The production image is based on the matching bgutil provider image so its Node/native dependencies remain ABI-compatible. `entrypoint.sh` starts the PO-token provider, waits until port `4416` is actually ready, and only then starts the FastAPI service.

## Platform policy layer

All FastAPI yt-dlp calls pass through `app.yt_dlp_wrapper` before reaching the real `/opt/venv/bin/yt-dlp` binary. This keeps platform-specific command behavior out of the API handlers.

Current policies:

- YouTube: PO-token provider + `mweb` + Node EJS runtime; configured cookies are only retried when authentication/bot-gate errors require them. An optional clean egress can be isolated with `YTDLP_YOUTUBE_PROXY`.
- Xiaohongshu / RedNote: yt-dlp remains the generic path. Anonymous extraction may retry with cookies when `No video formats found` is returned. A regional yt-dlp route can be isolated with `YTDLP_XHS_PROXY`. In addition, the Worker can use an optional XHS-specific resolver as a fallback or preferred provider.
- Twitch: cookies are removed by default because some yt-dlp Twitch paths regress when cookies are supplied. Set `YTDLP_TWITCH_ALLOW_COOKIES=1` only when explicitly required.
- Rumble: stays on normal browser impersonation by default, but can be routed through a dedicated anti-bot/mitm proxy using `YTDLP_RUMBLE_PROXY` without proxying every other platform.

## XHS specialized resolver

Galaxy supports an optional XHS-specific HTTP resolver without embedding Chromium or a second parser stack into the primary media Container. The integration depends only on a small `POST /xhs/detail` HTTP contract:

```json
{
  "url": "https://www.xiaohongshu.com/explore/...",
  "download": false
}
```

The Worker automatically recognizes both resolver response families currently used by the supported service implementations:

1. structured media schema (`媒体[]`, `地址`, `扩展名`, `预览地址`);
2. legacy/server schema (`下载地址[]`, `动图地址[]`, `作者昵称`).

The frontend never needs to understand either resolver schema. Galaxy normalizes both into the same first-party result model.

The default mode is `fallback`:

1. Try the first-party Container/yt-dlp path.
2. If XHS parsing fails, call the specialized resolver.
3. If the resolver also fails, preserve the original yt-dlp failure rather than changing behavior for existing installations.

Set `XHS_RESOLVER_MODE=prefer` to invert steps 1 and 2 when the resolver is known to be more reliable for the deployment region.

Video downloads do not expose the resolver's CDN URL as the primary download URL. The Worker re-resolves the work, verifies that the returned media host is allowlisted, follows only allowlisted redirects, forwards `Range`, and streams the media to the client. This avoids Container temp-disk usage while preventing `/api/download` from becoming an arbitrary open proxy.

The tunnel enforces `XHS_MAX_STREAM_BYTES` twice: first against `Content-Length` when the CDN supplies it, and again while bytes are actually flowing. Chunked or unknown-length responses therefore cannot bypass the limit.

Image notes keep the existing Galaxy image-download path and image proxy behavior.

### Resolver circuit breaker

The Worker keeps a lightweight per-isolate circuit breaker around the external resolver so an outage cannot add the full resolver timeout to every XHS request indefinitely.

Default behavior:

- consecutive network, `5xx`, or `429` failures count as resolver infrastructure failures;
- after 3 consecutive infrastructure failures, the circuit opens for 30 seconds;
- after the cooldown, one half-open probe is allowed;
- a successful probe closes the circuit and resets the failure count;
- ordinary content/client failures such as `400`, `401`, `403`, or `404` do not open the circuit.

This state is intentionally isolate-local. It is only a latency/failure-containment optimization and is not used as durable global health state.

### XHS resolver variables

Sensitive Worker secrets:

- `XHS_RESOLVER_URL` — resolver base URL or full `/xhs/detail` URL. If unset, the specialized provider is disabled and existing yt-dlp behavior is unchanged.
- `XHS_RESOLVER_TOKEN` — optional Bearer token for a protected resolver. The production deployment template requires one.

Non-sensitive Worker vars:

- `XHS_RESOLVER_MODE` — `fallback` (default) or `prefer`.
- `XHS_RESOLVER_TIMEOUT_MS` — resolver request timeout; default `20000`.
- `XHS_RESOLVER_FAILURE_THRESHOLD` — consecutive infrastructure failures before opening the circuit; default `3`.
- `XHS_RESOLVER_COOLDOWN_MS` — circuit-open cooldown; default `30000`.
- `XHS_MEDIA_HOST_SUFFIXES` — comma-separated CDN host suffix allowlist. Defaults to `xhscdn.com,xiaohongshu.com`.
- `XHS_MAX_STREAM_BYTES` — maximum bytes returned by one XHS tunnel request; default `6442450944` (6 GiB).

These non-sensitive defaults are committed in `wrangler.jsonc`, so a normal deploy receives the safe baseline automatically. Override them only when production evidence requires it.

The XHS resolver should manage its own Xiaohongshu login/browser state. Do not reuse a YouTube cookie file as the resolver's account state.

`GET /health` reports `xhsResolverConfigured` and `xhsResolverMode` but never returns the resolver URL or token.

### Resolver deployment template

A production-oriented standalone Docker stack is available at:

```text
deploy/xhs-resolver/
```

It:

- builds a pinned upstream resolver commit rather than an unpinned `main` branch;
- persists resolver state in its own Docker volume;
- exposes the resolver only through Caddy;
- terminates HTTPS automatically;
- requires `Authorization: Bearer <token>` for resolver API requests;
- exposes only a minimal unauthenticated `/healthz` endpoint.

See `deploy/xhs-resolver/README.md` for server/NAS deployment and upgrade instructions.

## Local Docker test

```bash
docker build -t galaxy-downloader-backend .
docker run --rm -p 8080:8080 galaxy-downloader-backend
curl http://127.0.0.1:8080/health
```

Parse a public media URL:

```bash
curl --get 'http://127.0.0.1:8080/api/parse' \
  --data-urlencode 'url=https://example.com/media'
```

The local Docker command above exercises the generic Container service. The XHS resolver routing layer is in the Cloudflare Worker (`src/index.ts`) and is exercised when running/deploying the Worker.

## Optional runtime configuration

The Worker forwards these values to the Container:

- `YTDLP_COOKIES_B64` — base64 encoded Netscape cookies file. Do not commit cookies to Git.
- `YTDLP_COOKIE_POLICY` — `when_needed` (default), `always`, or `never`.
- `YTDLP_TWITCH_ALLOW_COOKIES` — set to `1` only when a Twitch request explicitly needs cookies.
- `YTDLP_PROXY` — optional global yt-dlp proxy URL.
- `YTDLP_YOUTUBE_PROXY` — optional YouTube-only clean/residential egress.
- `YTDLP_XHS_PROXY` — optional Xiaohongshu-only regional egress for the yt-dlp path.
- `YTDLP_RUMBLE_PROXY` — optional Rumble-only proxy/mitm route for Cloudflare-challenged traffic.
- `YTDLP_USER_AGENT` — optional override.
- `YTDLP_IMPERSONATE` — browser impersonation target; defaults to `chrome` in the Python service.
- `ALLOWED_ORIGINS` — comma-separated frontend origins.

The `XHS_RESOLVER_*` variables are consumed by the Worker provider layer and are intentionally not forwarded into the generic Container.

For Cloudflare secrets, set sensitive values from the `container-backend` directory, for example:

```bash
npx wrangler secret put YTDLP_COOKIES_B64
npx wrangler secret put YTDLP_YOUTUBE_PROXY
npx wrangler secret put YTDLP_XHS_PROXY
npx wrangler secret put YTDLP_RUMBLE_PROXY
npx wrangler secret put XHS_RESOLVER_URL
npx wrangler secret put XHS_RESOLVER_TOKEN
```

Do not commit resolver URLs containing credentials, tokens, cookies, or authenticated proxy strings.

## Real XHS resolver smoke test

The repository contains a dedicated workflow:

```text
.github/workflows/xhs-resolver-live-smoke.yml
```

It uses `scripts/xhs-resolver-live-smoke.py` and can validate a real deployed resolver without adding resolver code or account state to CI.

Configure these GitHub Actions secrets to enable the live test:

- `XHS_RESOLVER_URL` — deployed HTTPS resolver base URL;
- `XHS_RESOLVER_TOKEN` — matching Bearer token;
- `XHS_SMOKE_URL` — a stable Xiaohongshu test work URL that the resolver can access.

When all three are available, the workflow:

1. calls `/xhs/detail` with `download=false`;
2. verifies a recognized resolver schema;
3. verifies at least one downloadable media item;
4. checks every returned media hostname against `xhscdn.com,xiaohongshu.com`;
5. performs a small `Range: bytes=0-1023` media probe rather than downloading the full file;
6. uploads a JSON smoke report without storing the token or returned media URLs.

If `XHS_RESOLVER_URL` or `XHS_SMOKE_URL` has not been provisioned, the workflow emits an explicit `status: skipped` report and exits successfully. This keeps unconfigured forks green without pretending the real resolver was tested.

The same probe can be run locally:

```bash
XHS_RESOLVER_URL='https://xhs-resolver.example.com' \
XHS_RESOLVER_TOKEN='...' \
XHS_SMOKE_URL='https://www.xiaohongshu.com/explore/...' \
XHS_SMOKE_FETCH_MEDIA=1 \
python scripts/xhs-resolver-live-smoke.py
```

## Rumble / Cloudflare challenge note

Rumble has active upstream yt-dlp reports where normal requests and even browser impersonation can still receive Cloudflare 403 responses. A practical self-hosted pattern used by other yt-dlp frontends is to keep FlareSolverr plus a yt-dlp-aware mitm proxy as a separate service and route only affected traffic through it. This backend deliberately does not bundle a full browser into the main media image; set `YTDLP_RUMBLE_PROXY` when such a route is available. This keeps normal downloads smaller, faster and cheaper.

## Cloudflare deployment

The backend is intentionally independent from the existing frontend Worker. Deploying it requires Cloudflare Containers/Workers Paid to be enabled on the account.

```bash
npm install
npm run typecheck
npm run deploy
```

`wrangler deploy` builds `Dockerfile`, pushes the image to Cloudflare's managed Container registry, deploys `galaxy-downloader-backend`, and creates the Durable Object-backed Container pool defined in `wrangler.jsonc`.

The current pool uses three `standard-1` instances at most. Idle instances sleep automatically.

## Validation policy

`.github/workflows/container-backend-ci.yml` must pass before this backend is treated as deployable. It validates:

1. Python API and platform-policy unit tests.
2. Worker TypeScript compilation.
3. Docker image build.
4. Container boot and `/health` response.
5. Node.js, FFmpeg, yt-dlp, `curl_cffi` and PO-token plugin availability inside the production image.

The root Vitest suite also contains XHS provider contract tests for URL recognition, both resolver response schemas, CDN allowlisting, redirect isolation, byte-level streaming limits, HTTP contract behavior, and circuit-breaker failure handling.

`Container Live Smoke` additionally proves that yt-dlp loaded `/etc/yt-dlp.conf`, sees the bgutil PO-token provider, enables the `mweb` client, and reports a supported Node runtime rather than `JS runtimes: none` before running live platform probes.

Real platform tests are maintained separately because public fixture URLs and anti-bot policies can change independently of the code. A real XHS resolver is not assumed in the generic Container smoke suite; the dedicated XHS Resolver Live Smoke workflow is the production readiness signal once resolver secrets are provisioned.
