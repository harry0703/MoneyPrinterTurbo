FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Create a non-root user
RUN groupadd -r appuser -g 1001 && \
    useradd -r -g appuser -u 1001 -d /app appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

ENTRYPOINT ["python", "main.py"]
