# ./base/Dockerfile
# Base image with shared dependencies
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    imagemagick \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Fix security policy for ImageMagick
RUN sed -i '/<policy domain="path" rights="none" pattern="@\*"/d' /etc/ImageMagick-6/policy.xml

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# At runtime, mount the config.toml file from the host into the container
# docker build -f .\Dockerfile -t moneyprinterturbo-base .
