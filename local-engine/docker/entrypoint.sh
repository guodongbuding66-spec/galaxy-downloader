#!/bin/sh
set -eu

umask 077

host="${GALAXY_HEADLESS_HOST:-0.0.0.0}"
port="${GALAXY_HEADLESS_PORT:-17837}"
download_dir="${GALAXY_DOWNLOAD_DIR:-/data/downloads}"
token="${GALAXY_HEADLESS_TOKEN:-}"

case "$port" in
  ''|*[!0-9]*)
    echo "GALAXY_HEADLESS_PORT must be an integer" >&2
    exit 64
    ;;
esac

if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
  echo "GALAXY_HEADLESS_PORT must be between 1 and 65535" >&2
  exit 64
fi

case "$host" in
  127.0.0.1|localhost|::1)
    ;;
  *)
    if [ "${#token}" -lt 24 ]; then
      echo "GALAXY_HEADLESS_TOKEN must contain at least 24 characters for non-loopback container binding" >&2
      exit 64
    fi
    ;;
esac

mkdir -p /data/state /data/cache /data/tools "$download_dir"

for path in /data /data/state /data/cache /data/tools "$download_dir"; do
  if [ -L "$path" ]; then
    echo "refusing symbolic-link runtime path: $path" >&2
    exit 64
  fi
done

exec python /app/headless_api.py \
  --host "$host" \
  --port "$port" \
  --download-dir "$download_dir"
