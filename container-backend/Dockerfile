FROM brainicism/bgutil-ytdlp-pot-provider:1.3.2

USER root
WORKDIR /

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:$PATH

# Preserve the provider exactly as shipped so its Node/native dependencies stay ABI-compatible.
RUN mv /app /opt/bgutil-provider \
    && mkdir -p /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY yt-dlp.conf /etc/yt-dlp.conf
COPY entrypoint.sh ./entrypoint.sh

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin galaxy \
    && chmod 0755 /app/entrypoint.sh \
    && chown -R galaxy:galaxy /app /home/galaxy

USER galaxy

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()" || exit 1

# Clear the provider image's inherited ENTRYPOINT; entrypoint.sh starts both services.
ENTRYPOINT []
CMD ["/app/entrypoint.sh"]
