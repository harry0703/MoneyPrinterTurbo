#!/usr/bin/env pwsh
#Requires -Version 5.1

<#
.SYNOPSIS
    Clear Python cache and restart Docker containers for Coiner
.DESCRIPTION
    This script clears Python cache files (__pycache__, *.pyc) from Docker containers
    and restarts them to ensure code changes take effect.
.EXAMPLE
    .\restart-docker.ps1
#>

$ErrorActionPreference = "Continue"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Clearing Python cache and restarting Docker" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check if Docker is running
Write-Host "[1/5] Checking Docker status..." -ForegroundColor Yellow
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Docker is not running"
    }
    Write-Host "  Docker is running" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Docker is not running. Please start Docker first." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Show current containers
Write-Host ""
Write-Host "[2/5] Current Docker containers:" -ForegroundColor Yellow
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Clear Python cache in containers
Write-Host ""
Write-Host "[3/5] Clearing Python cache in Docker containers..." -ForegroundColor Yellow

$containers = @("coiner-api")

foreach ($container in $containers) {
    Write-Host "  Processing container: $container" -ForegroundColor DarkGray
    
    # Check if container is running
    $containerRunning = docker ps --filter "name=$container" --format "{{.Names}}" 2>$null
    
    if ($containerRunning) {
        # Clear __pycache__ directories
        $result = docker exec $container find /Coiner -type d -name "__pycache__" -exec rm -rf {} + 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "    Cleared __pycache__ directories" -ForegroundColor Green
        } else {
            Write-Host "    No __pycache__ directories found (or already clean)" -ForegroundColor DarkGray
        }
        
        # Clear .pyc files
        $result = docker exec $container find /Coiner -name "*.pyc" -delete 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "    Cleared *.pyc files" -ForegroundColor Green
        } else {
            Write-Host "    No *.pyc files found (or already clean)" -ForegroundColor DarkGray
        }
        
        # Clear .pyo files (optimized bytecode)
        $result = docker exec $container find /Coiner -name "*.pyo" -delete 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "    Cleared *.pyo files" -ForegroundColor Green
        }
    } else {
        Write-Host "    Container not running, skipping" -ForegroundColor DarkYellow
    }
}

# Also clear local Python cache if exists
Write-Host ""
Write-Host "[4/5] Clearing local Python cache..." -ForegroundColor Yellow
$localCacheDirs = Get-ChildItem -Path "." -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue
if ($localCacheDirs) {
    $localCacheDirs | Remove-Item -Recurse -Force
    Write-Host "  Cleared local __pycache__ directories: $($localCacheDirs.Count)" -ForegroundColor Green
} else {
    Write-Host "  No local __pycache__ directories found" -ForegroundColor DarkGray
}

$localPycFiles = Get-ChildItem -Path "." -Recurse -File -Filter "*.pyc" -ErrorAction SilentlyContinue
if ($localPycFiles) {
    $localPycFiles | Remove-Item -Force
    Write-Host "  Cleared local *.pyc files: $($localPycFiles.Count)" -ForegroundColor Green
}

# Restart containers
Write-Host ""
Write-Host "[5/5] Restarting Docker containers..." -ForegroundColor Yellow
docker-compose restart

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[WARNING] Failed to restart containers. Trying to start them..." -ForegroundColor DarkYellow
    docker-compose up -d
}

# Show final status
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Done! Docker containers have been restarted" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "You can now access:" -ForegroundColor White
Write-Host "  - Application:     http://localhost:8080" -ForegroundColor Green
Write-Host "  - API:             http://localhost:8080" -ForegroundColor Green
Write-Host ""
Write-Host "Note: Application runs on port 8080" -ForegroundColor DarkGray
Write-Host ""

# Show running containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

Write-Host ""
Read-Host "Press Enter to exit"
