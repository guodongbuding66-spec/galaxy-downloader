#!/bin/sh
set -eu

POT_LOG="/tmp/bgutil-provider.log"

node /opt/bgutil-provider/build/main.js --port 4416 >"$POT_LOG" 2>&1 &
POT_PID=$!

# The provider starts quickly, but do not expose the API until the process is alive.
sleep 1
if ! kill -0 "$POT_PID" 2>/dev/null; then
  echo "bgutil PO token provider failed to start" >&2
  cat "$POT_LOG" >&2 || true
  exit 1
fi

exec python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8080 \
  --proxy-headers \
  --forwarded-allow-ips '*'
