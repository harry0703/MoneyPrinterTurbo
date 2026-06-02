FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    imagemagick \
    libmagickwand-dev \
    libmagickcore-dev \
    fonts-dejavu-core \
    fonts-liberation \
    fontconfig \
    curl \
    wget \
    git \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN if [ -f /etc/ImageMagick-6/policy.xml ]; then \
      sed -i \
        -e 's/rights="none" pattern="PDF"/rights="read|write" pattern="PDF"/' \
        -e 's/rights="none" pattern="PS"/rights="read|write" pattern="PS"/' \
        -e 's/rights="none" pattern="EPS"/rights="read|write" pattern="EPS"/' \
        /etc/ImageMagick-6/policy.xml; \
    fi

RUN fc-cache -fv

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p \
    storage/tasks \
    resource/songs \
    resource/fonts \
    resource/backgrounds \
    logs

COPY railway/start.sh ./start.sh
COPY railway/generate-config.sh ./generate-config.sh
RUN chmod +x start.sh generate-config.sh

# Remove any pre-baked config.toml so MPT cannot read stale config at startup.
# Our generate-config.sh writes the correct config before uvicorn launches.
RUN rm -f config.toml config.example.toml

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/api/v1/health || exit 1

EXPOSE 8080

CMD ["./start.sh"]
