# ─────────────────────────────────────────────────────────────
# Clipp Engine — Production Dockerfile
# Target: Railway container deployment
#
# This Dockerfile is placed in the root of the
# MoneyPrinterTurbo repository (your fork).
# Railway builds this when the engine service deploys.
# ─────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# ── System dependencies ──────────────────────────────────────
# FFmpeg:       video clip assembly and encoding
# ImageMagick:  subtitle rendering and frame manipulation
# fonts-*:      text rendering for subtitles
# curl:         health checks and API calls
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    imagemagick \
    libmagickwand-dev \
    libmagickcore-dev \
    libmagickcore-6.q16-6 \
    fonts-dejavu-core \
    fonts-liberation \
    fontconfig \
    curl \
    wget \
    git \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Fix ImageMagick security policy ─────────────────────────
# Default Debian policy blocks operations MPT needs.
# This unlocks PDF, PS, EPS, video-related patterns.
RUN if [ -f /etc/ImageMagick-6/policy.xml ]; then \
      sed -i \
        -e 's/rights="none" pattern="PDF"/rights="read|write" pattern="PDF"/' \
        -e 's/rights="none" pattern="PS"/rights="read|write" pattern="PS"/' \
        -e 's/rights="none" pattern="PS2"/rights="read|write" pattern="PS2"/' \
        -e 's/rights="none" pattern="PS3"/rights="read|write" pattern="PS3"/' \
        -e 's/rights="none" pattern="EPS"/rights="read|write" pattern="EPS"/' \
        -e 's/rights="none" pattern="LABEL"/rights="read|write" pattern="LABEL"/' \
        /etc/ImageMagick-6/policy.xml; \
    fi

# Update font cache
RUN fc-cache -fv

WORKDIR /app

# ── Python dependencies ──────────────────────────────────────
# Copy requirements first for Docker layer caching.
# Unchanged requirements = no pip re-install on code changes.
COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Application code ─────────────────────────────────────────
COPY . .

# ── Runtime directories ───────────────────────────────────────
RUN mkdir -p \
    storage/tasks \
    resource/songs \
    resource/fonts \
    resource/backgrounds \
    logs

# ── Copy Railway-specific files ───────────────────────────────
COPY railway/start.sh ./start.sh
COPY railway/generate-config.sh ./generate-config.sh

RUN chmod +x start.sh generate-config.sh

# ── Health check ─────────────────────────────────────────────
# Railway uses this to verify the container is healthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/api/v1/health || exit 1

# ── Default port (overridden by Railway's $PORT) ─────────────
EXPOSE 8080

CMD ["./start.sh"]
