# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /MoneyPrinterTurbo

ENV PYTHONPATH="/MoneyPrinterTurbo:$PYTHONPATH"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    imagemagick \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Fix security policy for ImageMagick
RUN sed -i '/<policy domain="path" rights="none" pattern="@\*"/d' /etc/ImageMagick-6/policy.xml

# Copy the current directory contents into the container at /MoneyPrinterTurbo
COPY ./app ./app
COPY ./webui ./webui
COPY ./resource ./resource
COPY ./requirements.txt ./requirements.txt
COPY ./main.py ./main.py

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port the app runs on
EXPOSE 8501

# Command to run the application
CMD ["streamlit", "run", "./webui/Main.py","--browser.serverAddress=0.0.0.0","--server.enableCORS=True","--browser.gatherUsageStats=False"]

# At runtime, mount the config.toml file from the host into the container
# using Docker volumes. Example usage:
# docker run -v ./config.toml:/MoneyPrinterTurbo/config.toml -v ./storage:/MoneyPrinterTurbo/storage -p 8501:8501 moneyprinterturbo