# Build stage
FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04 AS builder

# Set working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libjpeg-dev \
        zlib1g-dev \
        python3 \
        python3-pip \
        python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements.txt
COPY requirements.txt .

# Install Python dependencies with CUDA support
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

# Set working directory in container
WORKDIR /MoneyPrinterTurboCN

# Set /MoneyPrinterTurboCN directory permissions to 777
RUN chmod 777 /MoneyPrinterTurboCN

ENV PYTHONPATH="/MoneyPrinterTurboCN"
ENV LD_LIBRARY_PATH="/usr/local/nvidia/lib:/usr/local/nvidia/lib64:/usr/local/cuda-12.0/targets/x86_64-linux/lib"

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
    # Install CUDA 12.x libraries for Whisper
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libcublas-12-0 \
        libcudnn8 && \
    # Set timezone to Asia/Shanghai
    echo "Asia/Shanghai" > /etc/timezone && \
    DEBIAN_FRONTEND=noninteractive dpkg-reconfigure -f noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

# Fix security policy for ImageMagick
RUN sed -i '/<policy domain="path" rights="none" pattern="@\*"/d' /etc/ImageMagick-6/policy.xml

# Copy Python dependencies from builder stage
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Expose port that app runs on
EXPOSE 8501 8080

# Command to run the application
CMD ["python3", "-m", "streamlit", "run", "./webui/Main.py","--browser.serverAddress=localhost","--server.enableCORS=True","--browser.gatherUsageStats=False"]

# 1. Build the Docker image using the following command
# docker build -t moneyprinterturbocn .

# 2. Run the Docker container using the following command
## For Linux or MacOS with GPU:
# docker run --gpus all -v $(pwd)/config.toml:/MoneyPrinterTurboCN/config.toml -v $(pwd)/storage:/MoneyPrinterTurboCN/storage -v $(pwd)/models:/MoneyPrinterTurboCN/models -p 8501:8501 moneyprinterturbocn
## For Windows with GPU:
# docker run --gpus all -v ${PWD}/config.toml:/MoneyPrinterTurboCN/config.toml -v ${PWD}/storage:/MoneyPrinterTurboCN/storage -v ${PWD}/models:/MoneyPrinterTurboCN/models -p 8501:8501 moneyprinterturbocn
## Without GPU:
# docker run -v ${PWD}/config.toml:/MoneyPrinterTurboCN/config.toml -v ${PWD}/storage:/MoneyPrinterTurboCN/storage -v ${PWD}/models:/MoneyPrinterTurboCN/models -p 8501:8501 moneyprinterturbocn
