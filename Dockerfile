# Build stage
FROM python:3.11-slim-bullseye AS builder

# Set working directory
WORKDIR /app

# Install build dependencies with domestic mirrors
RUN echo "deb http://mirrors.aliyun.com/debian bullseye main" > /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian-security bullseye-security main" >> /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libjpeg-dev \
        zlib1g-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements.txt
COPY requirements.txt .

# Install Python dependencies with domestic mirrors
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    --retries 3 \
    --timeout 60 \
    -r requirements.txt || \
    pip install --no-cache-dir \
    -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/ \
    --trusted-host mirrors.tuna.tsinghua.edu.cn \
    --retries 3 \
    --timeout 60 \
    -r requirements.txt || \
    pip install --no-cache-dir \
    --retries 3 \
    --timeout 60 \
    -r requirements.txt

# Runtime stage
FROM python:3.11-slim-bullseye

# Set working directory in container
WORKDIR /MoneyPrinterTurboCN

# Set /MoneyPrinterTurboCN directory permissions to 777
RUN chmod 777 /MoneyPrinterTurboCN

ENV PYTHONPATH="/MoneyPrinterTurboCN"

# Install runtime dependencies with domestic mirrors
RUN echo "deb http://mirrors.aliyun.com/debian bullseye main" > /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian-security bullseye-security main" >> /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends \
        git \
        imagemagick \
        ffmpeg \
        libjpeg62-turbo \
        zlib1g && \
    rm -rf /var/lib/apt/lists/*

# Fix security policy for ImageMagick
RUN sed -i '/<policy domain="path" rights="none" pattern="@\*"/d' /etc/ImageMagick-6/policy.xml

# Copy Python dependencies from builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Expose port that app runs on
EXPOSE 8501 8080

# Command to run the application
CMD ["streamlit", "run", "./webui/Main.py","--browser.serverAddress=127.0.0.1","--server.enableCORS=True","--browser.gatherUsageStats=False"]

# 1. Build the Docker image using the following command
# docker build -t moneyprinterturbocn .

# 2. Run the Docker container using the following command
## For Linux or MacOS:
# docker run -v $(pwd)/config.toml:/MoneyPrinterTurboCN/config.toml -v $(pwd)/storage:/MoneyPrinterTurboCN/storage -v $(pwd)/models:/MoneyPrinterTurboCN/models -p 8501:8501 moneyprinterturbocn
## For Windows:
# docker run -v ${PWD}/config.toml:/MoneyPrinterTurboCN/config.toml -v ${PWD}/storage:/MoneyPrinterTurboCN/storage -v ${PWD}/models:/MoneyPrinterTurboCN/models -p 8501:8501 moneyprinterturbocn
