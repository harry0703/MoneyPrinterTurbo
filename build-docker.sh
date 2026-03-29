#!/bin/bash

# Script to build Docker image for MoneyPrinterTurboCN
# Usage: ./build-docker.sh

echo "========================================"
echo "MoneyPrinterTurboCN Docker Build Script"
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

# Build the Docker image
echo "[INFO] Building Docker image..."
echo "[INFO] Starting build process..."
echo ""

set -e

if docker build --progress=plain -t moneyprinterturbocn .; then
    echo ""
    echo "========================================"
    echo "[SUCCESS] Docker image built successfully!"
    echo "========================================"
    echo ""
    
    # Show image details
    echo "=== Image Details ==="
    docker images moneyprinterturbocn
    
    # Show run instructions
    echo ""
    echo "=== How to Run ==="
    echo "To start the containers, run:"
    echo ""
    echo "  ./start-docker.sh"
    echo ""
    echo "Then open your browser and navigate to:"
    echo "  http://localhost:8501"
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
