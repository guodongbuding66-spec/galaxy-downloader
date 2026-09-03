# Galaxy Local Engine Headless Docker / NAS

This package runs the stable Galaxy headless API without the desktop UI. It exposes the same job, Media Library, Transcript, Subscription V2, and CLI-facing API contracts on port `17837`.

## Quick start

1. Create a persistent data directory. On Linux/NAS, make it writable by container UID/GID `10001:10001`:

   ```sh
   mkdir -p galaxy-data
   sudo chown -R 10001:10001 galaxy-data
   ```

2. Set a bearer token of at least 24 characters:

   ```sh
   export GALAXY_HEADLESS_TOKEN='replace-with-a-long-random-token'
   ```

3. Start the service:

   ```sh
   docker compose -f docker-compose.headless.yml up -d --build
   ```

The default Compose mapping is loopback-only: `127.0.0.1:17837`. This is intentional. The process inside the container listens on `0.0.0.0`, but the host does not expose it to the LAN unless you opt in.

## NAS / LAN access

To expose the service on the NAS network interface, set `GALAXY_BIND_ADDRESS` to the desired host address before starting Compose, for example:

```sh
export GALAXY_BIND_ADDRESS='192.168.1.20'
docker compose -f docker-compose.headless.yml up -d
```

Keep the bearer token enabled. For access beyond a trusted local network, put the service behind an HTTPS reverse proxy or VPN; do not expose the plain HTTP port directly to the public internet.

## Persistent data

The container uses `/data` as the durable root:

- `/data/downloads` — downloaded media
- `/data/state` — queues, Media Library, Transcript/Subscription databases and durable state
- `/data/cache` — runtime cache
- `/data/tools` — managed runtime tools where applicable

Override the host directory with `GALAXY_DATA_DIR`:

```sh
export GALAXY_DATA_DIR='/volume1/docker/galaxy-local-engine'
```

For Synology/QNAP/TrueNAS-style bind mounts, ensure UID/GID `10001:10001` has read/write access to that directory.

## Security defaults

The image and Compose profile intentionally use:

- non-root runtime user `10001:10001`
- required 24+ character bearer token for non-loopback binding
- loopback-only host port mapping by default
- read-only container root filesystem in Compose
- writable `/data` volume plus temporary `/tmp` tmpfs only
- all Linux capabilities dropped
- `no-new-privileges`
- `tini` as PID 1
- symbolic-link rejection for durable runtime paths
- no credential-bearing CLI argument; the CLI reads `GALAXY_HEADLESS_TOKEN` from the environment

## Health check

The image health check calls authenticated `GET /v1/status` on the container loopback interface. View status with:

```sh
docker compose -f docker-compose.headless.yml ps
```

or with the CLI from the host:

```sh
export GALAXY_HEADLESS_URL='http://127.0.0.1:17837'
export GALAXY_HEADLESS_TOKEN='replace-with-a-long-random-token'
python local-engine/galaxy_cli.py status
```

## Updating

Rebuild the image from the current repository revision and restart:

```sh
docker compose -f docker-compose.headless.yml build --pull
docker compose -f docker-compose.headless.yml up -d
```

The `/data` volume is not replaced by image rebuilds.
