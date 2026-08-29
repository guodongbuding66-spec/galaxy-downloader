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

Galaxy supports an optional XHS-specific HTTP resolver without embedding Chromium or a second parser stack into the primary media Container. The integration depends only on a small resolver contract compatible with `xhs-downloader`'s `POST /xhs/detail` endpoint:

```json
{
  "url": "https://www.xiaohongshu.com/explore/...",
  "download": false
}
```

The resolver returns work metadata and media URLs. Galaxy converts that payload into its own frontend result shape; the frontend never needs to understand the resolver's schema.

The default mode is `fallback`:

1. Try the first-party Container/yt-dlp path.
2. If XHS parsing fails, call the specialized resolver.
3. If the resolver also fails, preserve the original yt-dlp failure rather than changing behavior for existing installations.

Set `XHS_RESOLVER_MODE=prefer` to invert steps 1 and 2 when the resolver is known to be more reliable for the deployment region.

Video downloads do not expose the resolver's CDN URL as the primary download URL. The Worker re-resolves the work, verifies that the returned media host is allowlisted, follows only allowlisted redirects, forwards `Range`, and streams the media to the client. This avoids Container temp-disk usage while preventing `/api/download` from becoming an arbitrary open proxy.

The tunnel enforces `XHS_MAX_STREAM_BYTES` twice: first against `Content-Length` when the CDN supplies it, and again while bytes are actually flowing. Chunked or unknown-length responses therefore cannot bypass the limit.

Image notes keep the existing Galaxy image-download path and image proxy behavior.

### XHS resolver variables

- `XHS_RESOLVER_URL` — resolver base URL or full `/xhs/detail` URL. If unset, the specialized provider is disabled and existing yt-dlp behavior is unchanged.
- `XHS_RESOLVER_MODE` — `fallback` (default) or `prefer`.
- `XHS_RESOLVER_TOKEN` — optional Bearer token for a protected resolver. Store as a Cloudflare secret.
- `XHS_RESOLVER_TIMEOUT_MS` — resolver request timeout; default `20000`.
- `XHS_MEDIA_HOST_SUFFIXES` — comma-separated CDN host suffix allowlist. Defaults to `xhscdn.com,xiaohongshu.com`.
- `XHS_MAX_STREAM_BYTES` — maximum bytes returned by one XHS tunnel request; default `6442450944` (6 GiB).

The XHS resolver should manage its own Xiaohongshu login/browser state. Do not reuse a YouTube cookie file as the resolver's account state.

`GET /health` reports `xhsResolverConfigured` and `xhsResolverMode` but never returns the resolver URL or token.

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

Non-sensitive settings such as `XHS_RESOLVER_MODE`, timeouts and host suffixes may be stored as Worker vars instead of secrets.

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

The root Vitest suite also contains XHS provider contract tests for URL recognition, upstream response normalization, CDN allowlisting and byte-level streaming limits.

`Container Live Smoke` additionally proves that yt-dlp loaded `/etc/yt-dlp.conf`, sees the bgutil PO-token provider, enables the `mweb` client, and reports a supported Node runtime rather than `JS runtimes: none` before running live platform probes.

Real platform tests are maintained separately because public fixture URLs and anti-bot policies can change independently of the code. A real XHS resolver is not assumed in CI unless `XHS_RESOLVER_URL` is explicitly provisioned; therefore the live probe continues to expose upstream yt-dlp XHS failures rather than falsely treating the optional adapter as configured.
