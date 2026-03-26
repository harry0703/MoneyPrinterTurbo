#!/bin/bash

# Script to build Docker image for MoneyPrinterTurboCN
# Usage: ./build-docker.sh

echo "=== MoneyPrinterTurboCN Docker Build Script ==="

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed or not in PATH"
    echo "Please install Docker and try again."
    exit 1
fi

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo "Error: Docker daemon is not running"
    echo "Please start Docker and try again."
    exit 1
fi

# Build the Docker image
echo "Building Docker image..."

set -e

docker build -t moneyprinterturbocn .

if [ $? -eq 0 ]; then
    echo "\n✅ Docker image built successfully!"
    
    # Show image details
    echo "\n=== Image Details ==="
    docker images moneyprinterturbocn
    
    # Show run instructions
    echo "\n=== How to Run ==="
    echo "Run the container with:"
    echo ""
    echo "docker run -v $(pwd)/config.toml:/MoneyPrinterTurboCN/config.toml -v $(pwd)/storage:/MoneyPrinterTurboCN/storage -p 8501:8501 moneyprinterturbocn"
    
    echo "\nThen open your browser and navigate to: http://localhost:8501"
else
    echo "❌ Docker build failed"
    exit 1
fi

echo "\n=== Build Complete ==="
