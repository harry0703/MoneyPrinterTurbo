#!/usr/bin/env pwsh

# Script to build Docker image for MoneyPrinterTurboCN
# Usage: .\build-docker.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "MoneyPrinterTurboCN Docker Build Script" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Docker is installed
Write-Host "[INFO] Checking Docker installation..." -ForegroundColor Cyan
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Docker is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Docker Desktop and try again." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[INFO] Docker is installed" -ForegroundColor Green
Write-Host ""

# Check if Docker daemon is running
Write-Host "[INFO] Checking Docker daemon status..." -ForegroundColor Cyan
try {
    docker info | Out-Null
} catch {
    Write-Host "[ERROR] Docker daemon is not responding" -ForegroundColor Red
    Write-Host ""
    Write-Host "Possible reasons:" -ForegroundColor Yellow
    Write-Host "1. Docker Desktop is not running" -ForegroundColor White
    Write-Host "2. Docker Desktop is still starting up" -ForegroundColor White
    Write-Host "3. Docker client and server API version mismatch" -ForegroundColor White
    Write-Host ""
    Write-Host "Troubleshooting steps:" -ForegroundColor Yellow
    Write-Host "1. Check if Docker Desktop is running in system tray" -ForegroundColor White
    Write-Host "2. If running, try restarting Docker Desktop:" -ForegroundColor White
    Write-Host "   - Right-click Docker icon in system tray" -ForegroundColor Gray
    Write-Host "   - Select 'Quit Docker Desktop'" -ForegroundColor Gray
    Write-Host "   - Wait 10 seconds, then restart Docker Desktop" -ForegroundColor Gray
    Write-Host "   - Wait 30-60 seconds for it to fully start" -ForegroundColor Gray
    Write-Host "3. Check Docker Desktop logs for errors" -ForegroundColor White
    Write-Host "4. Try running 'docker version' to see detailed error" -ForegroundColor White
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[INFO] Docker daemon is running" -ForegroundColor Green
Write-Host ""

# Pre-download base image
Write-Host "[INFO] Pre-downloading base image..." -ForegroundColor Cyan
Write-Host "[INFO] This may take several minutes depending on your network speed" -ForegroundColor Gray
Write-Host "[INFO] Base image: python:3.11-slim-bullseye (Original base image)" -ForegroundColor Gray
Write-Host ""
Write-Host "[TIP] If download is slow, consider configuring Docker mirror accelerators:" -ForegroundColor Yellow
Write-Host "[TIP] 1. Open Docker Desktop Settings" -ForegroundColor Gray
Write-Host "[TIP] 2. Go to Docker Engine" -ForegroundColor Gray
Write-Host "[TIP] 3. Add registry-mirrors configuration" -ForegroundColor Gray
Write-Host ""

try {
    docker pull python:3.11-slim-bullseye
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to download base image"
    }
} catch {
    Write-Host ""
    Write-Host "[ERROR] Failed to download base image" -ForegroundColor Red
    Write-Host "Please check your network connection or configure Docker mirror accelerators" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "[INFO] Base image downloaded successfully" -ForegroundColor Green
Write-Host ""

# Build the Docker image
Write-Host "[INFO] Building Docker image..." -ForegroundColor Cyan
Write-Host "[INFO] Starting build process..." -ForegroundColor Gray
Write-Host ""

try {
    docker build --progress=plain -t moneyprinterturbocn .
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "[SUCCESS] Docker image built successfully!" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host ""
        
        # Show image details
        Write-Host "=== Image Details ===" -ForegroundColor Cyan
        docker images moneyprinterturbocn
        
        # Show run instructions
        Write-Host ""
        Write-Host "=== How to Run ===" -ForegroundColor Cyan
        Write-Host "To start the containers, run:" -ForegroundColor White
        Write-Host ""
        Write-Host "  .\start-docker.bat" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Then open your browser and navigate to:" -ForegroundColor White
        Write-Host "  http://localhost:8501" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "[ERROR] Docker build failed" -ForegroundColor Red
        Write-Host "Please check the error messages above." -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }
} catch {
    Write-Host ""
    Write-Host "[ERROR] Error during build: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "=== Build Complete ===" -ForegroundColor Cyan
Read-Host "Press Enter to exit"
