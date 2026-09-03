FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    GALAXY_PORTABLE=0 \
    GALAXY_HOME=/data \
    GALAXY_DOWNLOAD_DIR=/data/downloads \
    GALAXY_HEADLESS_HOST=0.0.0.0 \
    GALAXY_HEADLESS_PORT=17837

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 galaxy \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/galaxy --shell /usr/sbin/nologin galaxy \
    && mkdir -p /app /data/downloads /data/state /data/cache /data/tools \
    && chown -R galaxy:galaxy /app /data /home/galaxy

WORKDIR /app

COPY docker/requirements-headless.txt /tmp/requirements-headless.txt
RUN python -m pip install --requirement /tmp/requirements-headless.txt \
    && rm -f /tmp/requirements-headless.txt

COPY --chown=galaxy:galaxy . /app/

RUN chmod 0555 /app/docker/entrypoint.sh

USER 10001:10001

EXPOSE 17837
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import json,os,urllib.request; r=urllib.request.Request('http://127.0.0.1:17837/v1/status',headers={'Authorization':'Bearer '+os.environ.get('GALAXY_HEADLESS_TOKEN','')}); d=json.load(urllib.request.urlopen(r,timeout=3)); raise SystemExit(0 if d.get('ok') else 1)"

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
