# Use an official Python runtime as a parent image
FROM python:3.10-slim-bullseye AS base

# Set the working directory in the container 
WORKDIR /MoneyPrinterTurbo

# Copy only the requirements.txt first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Use a multi-stage build for a smaller final image
FROM python:3.10-slim-bullseye 

WORKDIR /MoneyPrinterTurbo

COPY --from=base /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages

# Copy the rest of the codebase
COPY . .

ENV PYTHONPATH="/MoneyPrinterTurbo"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    imagemagick \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Fix security policy for ImageMagick
RUN sed -i '/<policy domain="path" rights="none" pattern="@\*"/d' /etc/ImageMagick-6/policy.xml

# Expose the port the app runs on
EXPOSE 8501

# Run the application
CMD ["python3", "-m", "streamlit", "run", "./webui/Main.py", "--browser.serverAddress=0.0.0.0", "--server.enableCORS=True", "--browser.gatherUsageStats=False"]