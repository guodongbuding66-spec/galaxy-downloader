#!/bin/sh
set -eu

POT_LOG="/tmp/bgutil-provider.log"
POT_HOST="127.0.0.1"
POT_PORT="4416"

node /opt/bgutil-provider/build/main.js --port "$POT_PORT" >"$POT_LOG" 2>&1 &
POT_PID=$!

# A running process is not enough: wait until the provider actually accepts TCP
# connections so yt-dlp cannot race it during the first request after a cold start.
POT_READY=0
for attempt in $(seq 1 40); do
  if ! kill -0 "$POT_PID" 2>/dev/null; then
    echo "bgutil PO token provider exited before becoming ready" >&2
    cat "$POT_LOG" >&2 || true
    exit 1
  fi

  if python - "$POT_HOST" "$POT_PORT" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
try:
    with socket.create_connection((host, port), timeout=0.25):
        pass
except OSError:
    raise SystemExit(1)
PY
  then
    POT_READY=1
    break
  fi
  sleep 0.25
done

if [ "$POT_READY" -ne 1 ]; then
  echo "bgutil PO token provider did not become ready on ${POT_HOST}:${POT_PORT}" >&2
  cat "$POT_LOG" >&2 || true
  exit 1
fi

exec python -m uvicorn app.server:app \
  --host 0.0.0.0 \
  --port 8080 \
  --proxy-headers \
  --forwarded-allow-ips '*'
