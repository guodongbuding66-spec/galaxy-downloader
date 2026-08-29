# Galaxy Downloader Container Backend

First-party media backend for Galaxy Downloader. It runs `yt-dlp`, FFmpeg, a current Node.js runtime and `curl_cffi` inside a Cloudflare Container so parsing and downloading happen from the same server/network path.

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
- `bgutil-ytdlp-pot-provider==1.3.2`
- an in-container bgutil HTTP PO-token provider on `127.0.0.1:4416`
- YouTube `mweb` client configured to consume generated PO tokens
- FFmpeg / ffprobe
- FastAPI + Uvicorn

The production image is based on the matching bgutil provider image so its Node/native dependencies remain ABI-compatible. `entrypoint.sh` starts the PO-token provider and then the FastAPI service.

## Platform policy layer

All FastAPI yt-dlp calls pass through `app.yt_dlp_wrapper` before reaching the real `/opt/venv/bin/yt-dlp` binary. This keeps platform-specific behavior out of the API handlers.

Current policies:

- YouTube: PO-token provider + `mweb` first; configured cookies are only retried when authentication/bot-gate errors require them.
- Xiaohongshu / RedNote: anonymous first; `No video formats found` may trigger a cookie retry because anonymous pages can omit media metadata.
- Twitch: cookies are removed by default because some yt-dlp Twitch paths regress when cookies are supplied. Set `YTDLP_TWITCH_ALLOW_COOKIES=1` only when explicitly required.
- Rumble: stays on normal browser impersonation by default, but can be routed through a dedicated anti-bot/mitm proxy using `YTDLP_RUMBLE_PROXY` without proxying every other platform.

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

## Optional runtime configuration

The Worker forwards these values to the Container:

- `YTDLP_COOKIES_B64` — base64 encoded Netscape cookies file. Do not commit cookies to Git.
- `YTDLP_COOKIE_POLICY` — `when_needed` (default), `always`, or `never`.
- `YTDLP_TWITCH_ALLOW_COOKIES` — set to `1` only when a Twitch request explicitly needs cookies.
- `YTDLP_PROXY` — optional global yt-dlp proxy URL.
- `YTDLP_RUMBLE_PROXY` — optional Rumble-only proxy/mitm route for Cloudflare-challenged traffic.
- `YTDLP_USER_AGENT` — optional override.
- `YTDLP_IMPERSONATE` — browser impersonation target; defaults to `chrome` in the Python service.
- `ALLOWED_ORIGINS` — comma-separated frontend origins.

For Cloudflare secrets, set values from the `container-backend` directory, for example:

```bash
npx wrangler secret put YTDLP_COOKIES_B64
npx wrangler secret put YTDLP_PROXY
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

Real platform tests are maintained separately because public fixture URLs and anti-bot policies can change independently of the code.
