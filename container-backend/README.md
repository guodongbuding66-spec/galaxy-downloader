# Galaxy Downloader Container Backend

First-party media backend for Galaxy Downloader. It runs `yt-dlp`, FFmpeg, Node.js 22 and `curl_cffi` inside a Cloudflare Container so parsing and downloading happen from the same server/network path.

## Why this backend exists

The public/shared parser can successfully parse many platforms but some temporary CDN URLs are bound to the parser IP, some providers intermittently fail, and several sites require browser TLS impersonation, cookies, a proxy, or a current JavaScript runtime. This backend keeps extraction and download on the same machine and exposes the frontend-compatible endpoints:

- `GET /health`
- `GET /api/parse?url=<source>`
- `GET /api/download?url=<source>&type=video|audio&quality=best&formatId=<optional>`

## Runtime

- Node.js 22
- Python 3.11+
- yt-dlp 2026.08.19 with default optional dependencies
- `curl_cffi` browser impersonation support
- `yt-dlp-ejs`
- FFmpeg / ffprobe
- FastAPI + Uvicorn

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

- `YTDLP_COOKIES_B64` — base64 encoded Netscape cookies file. Useful for platforms/content that require authentication. Do not commit cookies to Git.
- `YTDLP_PROXY` — optional yt-dlp proxy URL.
- `YTDLP_USER_AGENT` — optional override.
- `YTDLP_IMPERSONATE` — browser impersonation target; defaults to `chrome` in the Python service.
- `ALLOWED_ORIGINS` — comma-separated frontend origins.

For Cloudflare secrets, set values from the `container-backend` directory, for example:

```bash
npx wrangler secret put YTDLP_COOKIES_B64
npx wrangler secret put YTDLP_PROXY
```

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

1. Python API unit tests.
2. Worker TypeScript compilation.
3. Docker image build.
4. Container boot and `/health` response.
5. Node.js, FFmpeg, yt-dlp and `curl_cffi` availability inside the production image.

Real platform tests are maintained separately because public fixture URLs and anti-bot policies can change independently of the code.
