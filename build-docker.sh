#!/bin/bash

# Script to build Docker image for Coiner
# Usage: ./build-docker.sh

echo "========================================"
echo "Coiner Docker Build Script"
echo "========================================"
echo ""

# Check if Docker is installed
echo "[INFO] Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    echo "[ERROR] Docker is not installed or not in PATH"
    echo "Please install Docker Desktop and try again."
    read -p "Press Enter to exit"
    exit 1
fi
echo "[INFO] Docker is installed"
echo ""

# Check if Docker daemon is running
echo "[INFO] Checking Docker daemon status..."
if ! docker info &> /dev/null; then
    echo "[ERROR] Docker daemon is not responding"
    echo ""
    echo "Possible reasons:"
    echo "1. Docker Desktop is not running"
    echo "2. Docker Desktop is still starting up"
    echo "3. Docker client and server API version mismatch"
    echo ""
    echo "Troubleshooting steps:"
    echo "1. Check if Docker Desktop is running in system tray"
    echo "2. If running, try restarting Docker Desktop:"
    echo "   - Right-click Docker icon in system tray"
    echo "   - Select 'Quit Docker Desktop'"
    echo "   - Wait 10 seconds, then restart Docker Desktop"
    echo "   - Wait 30-60 seconds for it to fully start"
    echo "3. Check Docker Desktop logs for errors"
    echo "4. Try running 'docker version' to see detailed error"
    echo ""
    read -p "Press Enter to exit"
    exit 1
fi
echo "[INFO] Docker daemon is running"
echo ""

# Pre-download base image
echo "[INFO] Pre-downloading base image..."
echo "[INFO] This may take several minutes depending on your network speed"
echo "[INFO] Base image: python:3.11-slim-bullseye (Original base image)"
echo ""
echo "[TIP] If download is slow, consider configuring Docker mirror accelerators:"
echo "[TIP] 1. Open Docker Desktop Settings"
echo "[TIP] 2. Go to Docker Engine"
echo "[TIP] 3. Add registry-mirrors configuration"
echo ""

if ! docker pull python:3.11-slim-bullseye; then
    echo ""
    echo "[ERROR] Failed to download base image"
    echo "Please check your network connection or configure Docker mirror accelerators"
    read -p "Press Enter to exit"
    exit 1
fi

echo ""
echo "[INFO] Base image downloaded successfully"
echo ""

# Remove existing coiner images if exists
echo "[INFO] Removing existing coiner images if exists..."

# Step 1: Remove all containers using coiner images
echo "[INFO] Step 1: Removing containers using coiner images..."
docker ps -a --format "{{.Names}}" | grep "coiner" | while read -r container; do
    echo "[INFO] Stopping container: $container"
    docker stop "$container" 2>/dev/null
    echo "[INFO] Removing container: $container"
    docker rm "$container" 2>/dev/null
done

# Step 2: Remove all coiner images
echo "[INFO] Step 2: Removing coiner images..."
# Get all unique repositories containing coiner
docker images --format "{{.Repository}}" | grep "coiner" | sort -u | while read -r repo; do
    echo "[INFO] Removing image: $repo"
    docker rmi -f "$repo" 2>/dev/null
done

# Build the Docker image
echo "[INFO] Building Docker image..."
echo "[INFO] Starting build process..."
echo ""

set -e

if docker build --progress=plain -t coiner .; then
    echo ""
    echo "========================================"
    echo "[SUCCESS] Docker image built successfully!"
    echo "========================================"
    echo ""
    
    # Show image details
    echo "=== Image Details ==="
    docker images coiner
    
    # Show run instructions
    echo ""
    echo "=== How to Run ==="
    echo "To start the containers, run:"
    echo ""
    echo "  ./start-docker.sh"
    echo ""
    echo "Then open your browser and navigate to:"
    echo "  http://localhost:8080"
else
    echo ""
    echo "[ERROR] Docker build failed"
    echo "Please check the error messages above."
    read -p "Press Enter to exit"
    exit 1
fi

echo ""
echo "=== Build Complete ==="
read -p "Press Enter to exit"
