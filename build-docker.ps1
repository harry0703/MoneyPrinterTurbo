#!/usr/bin/env pwsh

# Script to build Docker image for MoneyPrinterTurboCN
# Usage: .\build-docker.ps1

Write-Host "=== MoneyPrinterTurboCN Docker Build Script ===" -ForegroundColor Green

# Check if Docker is installed
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Docker is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Docker Desktop and try again." -ForegroundColor Yellow
    exit 1
}

# Check if Docker is running
try {
    docker info | Out-Null
} catch {
    Write-Host "Error: Docker daemon is not running" -ForegroundColor Red
    Write-Host "Please start Docker Desktop and try again." -ForegroundColor Yellow
    exit 1
}

# Build the Docker image
Write-Host "Building Docker image..." -ForegroundColor Cyan

try {
    docker build -t moneyprinterturbocn .
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "\n✅ Docker image built successfully!" -ForegroundColor Green
        
        # Show image details
        Write-Host "\n=== Image Details ===" -ForegroundColor Cyan
        docker images moneyprinterturbocn
        
        # Show run instructions
        Write-Host "\n=== How to Run ===" -ForegroundColor Cyan
        Write-Host "Run the container with:
"
        Write-Host "docker run -v ${PWD}\config.toml:/MoneyPrinterTurboCN/config.toml -v ${PWD}\storage:/MoneyPrinterTurboCN/storage -p 8501:8501 moneyprinterturbocn"
        
        Write-Host "\nThen open your browser and navigate to: http://localhost:8501" -ForegroundColor Green
    } else {
        Write-Host "❌ Docker build failed" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "❌ Error during build: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "\n=== Build Complete ===" -ForegroundColor Green
