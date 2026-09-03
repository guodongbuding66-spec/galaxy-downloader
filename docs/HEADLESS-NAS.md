# Galaxy Local Engine · Headless / NAS

Galaxy Headless is the non-GUI execution surface for servers, NAS devices and automation. It uses the same public-URL validation and exact-format identity rules as the Local Engine, but does not require Tk.

## Security defaults

- The API defaults to `127.0.0.1:17837`.
- Binding to a non-loopback host requires `GALAXY_HEADLESS_TOKEN` with at least 24 characters.
- Remote CLI endpoints must use HTTPS. Put a reverse proxy with TLS in front of the container when exposing it outside the machine/LAN.
- The container runs as an unprivileged user, drops Linux capabilities, uses `no-new-privileges`, and mounts the application filesystem read-only.
- The download volume is the only persistent writable location.

## Docker / NAS

Create an environment file outside source control:

```env
GALAXY_HEADLESS_TOKEN=replace-with-a-random-32-plus-character-secret
GALAXY_DATA_DIR=/volume1/docker/galaxy
# Keep loopback for a reverse proxy on the same host. Use 0.0.0.0 only for a trusted LAN.
GALAXY_HEADLESS_BIND=127.0.0.1
```

Start the service:

```bash
docker compose --env-file .env -f docker-compose.headless.yml up -d --build
```

Health check:

```bash
curl http://127.0.0.1:17837/health
```

## CLI

The canonical CLI is `local-engine/galaxy_cli.py`.

```bash
python local-engine/galaxy_cli.py status
python local-engine/galaxy_cli.py parse "https://example.com/video"
python local-engine/galaxy_cli.py download "https://example.com/video" --wait
```

For a token-protected endpoint:

```bash
export GALAXY_HEADLESS_TOKEN='your-secret'
python local-engine/galaxy_cli.py --endpoint http://127.0.0.1:17837 status
```

For remote access, terminate TLS at Caddy/Nginx/Traefik and use an `https://` endpoint. Plain HTTP to a non-loopback host is rejected by the CLI.

## API

Unauthenticated health endpoint:

- `GET /health`

Authenticated endpoints when a token is configured:

- `GET /v1/status`
- `POST /v1/parse`
- `POST /v1/download`
- `GET /v1/jobs/<job-id>`

Example download request:

```json
{
  "sourceUrl": "https://example.com/video",
  "includeAudio": true,
  "includeSubtitle": false,
  "includeCover": false,
  "collectionMode": "single",
  "concurrentFragments": 4,
  "rateLimitMbps": 0
}
```

Exact `videoFormatId` / `audioFormatId` values may be supplied from a preceding parse response. Selector expressions such as `137+251` are rejected as IDs; the service constructs the exact yt-dlp selector itself.

## Storage

The default Docker path is `/data/downloads`. Mount `/data` on persistent NAS storage. Do not mount Docker socket, SSH keys, browser profiles or other host secrets into the container.
