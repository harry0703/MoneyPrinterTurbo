# Build stage 1: Vue frontend
FROM node:20-alpine AS vue-builder
WORKDIR /app/vue-frontend
COPY vue-frontend/package.json vue-frontend/package-lock.json ./
RUN npm ci
COPY vue-frontend/ ./
RUN npm run build

# Build stage 2: Python dependencies
FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04 AS python-builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libjpeg-dev \
        zlib1g-dev \
        python3 \
        python3-pip \
        python3-dev && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip3 install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    --retries 3 \
    --timeout 60 \
    -r requirements.txt || \
    pip3 install --no-cache-dir \
    -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/ \
    --trusted-host mirrors.tuna.tsinghua.edu.cn \
    --retries 3 \
    --timeout 60 \
    -r requirements.txt || \
    pip3 install --no-cache-dir \
    --retries 3 \
    --timeout 60 \
    -r requirements.txt

# Runtime stage
FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

WORKDIR /Coiner
RUN chmod 777 /Coiner

ENV PYTHONPATH="/Coiner"
# Align LD_LIBRARY_PATH with the CUDA 11.8 base image
ENV LD_LIBRARY_PATH="/usr/local/nvidia/lib:/usr/local/nvidia/lib64:/usr/local/cuda-11.8/targets/x86_64-linux/lib"
ENV IMAGEIO_FFMPEG_EXE="/usr/bin/ffmpeg"
# Match the docker-compose port mapping (8000:8000)
ENV LISTEN_HOST="0.0.0.0"
ENV LISTEN_PORT="8000"

# Install runtime dependencies
RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        git \
        imagemagick \
        ffmpeg \
        libjpeg8 \
        zlib1g \
        python3 \
        python3-pip \
        tzdata && \
    # Install CUDA libraries for Whisper (match CUDA 11.8)
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libcublas-11-8 \
        libcudnn8 && \
    # Set timezone to Asia/Shanghai
    echo "Asia/Shanghai" > /etc/timezone && \
    DEBIAN_FRONTEND=noninteractive dpkg-reconfigure -f noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

# Fix ImageMagick security policy (allow read/write instead of deleting the line)
RUN sed -i 's/rights="none" pattern="@\*"/rights="read|write" pattern="@*"/g' /etc/ImageMagick-6/policy.xml || true

# Copy Python dependencies from builder stage
COPY --from=python-builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=python-builder /usr/local/bin /usr/local/bin

# Copy built Vue frontend to the public directory so FastAPI serves it
COPY --from=vue-builder /app/vue-frontend/dist /Coiner/resource/public

# Copy application code
COPY . .

# Expose the port the FastAPI app listens on
EXPOSE 8080

# Run the FastAPI application (uvicorn via main.py)
CMD ["python3", "main.py"]

# Build the Docker image:
#   docker build -t coiner .
#
# Run with GPU:
#   docker run --gpus all -p 8080:8080 coiner
#
# Run without GPU:
#   docker run -p 8080:8080 coiner
