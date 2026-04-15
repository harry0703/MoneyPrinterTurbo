@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
echo ========================================
echo MoneyPrinterTurboCN Docker Build Script
echo ========================================
echo.

echo [INFO] Checking Docker installation and daemon...
echo [INFO] This may take a few seconds...

:: Check Docker installation and daemon in one command
docker version >nul 2>&1
echo [DEBUG] Errorlevel: %errorlevel%
if %errorlevel% equ 0 (
    echo [INFO] Docker is installed and daemon is running
    echo.
    echo [INFO] Pre-downloading base image...
    echo [INFO] This may take several minutes depending on your network speed
    echo [INFO] Base image: nvidia/cuda:11.8.0-runtime-ubuntu22.04 (CUDA 11.8 support)
    echo.
    echo [TIP] If download is slow, consider configuring Docker mirror accelerators:
    echo [TIP] 1. Open Docker Desktop Settings
    echo [TIP] 2. Go to Docker Engine
    echo [TIP] 3. Add registry-mirrors configuration
    echo.

    :: Pre-download base image to show progress
    docker pull nvidia/cuda:11.8.0-runtime-ubuntu22.04

    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to download base image
        echo Please check your network connection or configure Docker mirror accelerators
        echo.
        echo To configure mirror accelerators:
        echo 1. Open Docker Desktop
        echo 2. Go to Settings ^> Docker Engine
        echo 3. Add to following to JSON configuration:
        echo    "registry-mirrors": [
        echo      "https://docker.mirrors.ustc.edu.cn",
        echo      "https://hub-mirror.c.163.com"
        echo    ]
        echo 4. Click "Apply ^& Restart"
        echo.
        pause
        exit /b 1
    )

    echo.
    echo [INFO] Base image downloaded successfully
    echo [INFO] Removing existing moneyprinterturbocn images if exists...
    :: First, remove all containers using moneyprinterturbocn images
    echo [INFO] Step 1: Removing containers using moneyprinterturbocn images...
    for /f "tokens=1" %%i in ('docker ps -a --format "{{.Names}}" ^| findstr "moneyprinterturbocn"') do (
        echo [INFO] Stopping container: %%i
        docker stop %%i 2>nul
        echo [INFO] Removing container: %%i
        docker rm %%i 2>nul
    )
    :: Then remove all images with moneyprinterturbocn in their name
    echo [INFO] Step 2: Removing moneyprinterturbocn images...
    :: Remove images by repository name
    for /f "tokens=*" %%i in ('docker images --format "{{.Repository}}" ^| findstr "moneyprinterturbocn"') do (
        echo [INFO] Removing image: %%i
        docker rmi -f %%i 2>nul
    )
    :: Remove images by tag
    for /f "tokens=1,2" %%i in ('docker images ^| findstr "moneyprinterturbocn"') do (
        echo [INFO] Removing image: %%i:%%j
        docker rmi -f %%i:%%j 2>nul
    )
    :: Remove images by ID
    for /f "tokens=3" %%i in ('docker images ^| findstr "moneyprinterturbocn"') do (
        echo [INFO] Removing image by ID: %%i
        docker rmi -f %%i 2>nul
    )
    echo [INFO] Building Docker image...
    echo [INFO] Starting build process...
    echo.

    :: Build with progress output
    docker build --progress=plain -t moneyprinterturbocn .

    if errorlevel 1 (
        echo.
        echo [ERROR] Docker build failed
        echo Please check error messages above.
        echo.
        echo Common issues:
        echo 1. Network connectivity problems
        echo 2. Insufficient disk space
        echo 3. Outdated Docker version
        echo 4. Docker daemon not responding
        echo.
        pause
        exit /b 1
    )

    echo.
    echo ========================================
    echo [SUCCESS] Docker image built successfully!
    echo ========================================
    echo.
    echo === Image Details ===
    docker images moneyprinterturbocn
    echo.
    echo === GPU Support ===
    echo This image includes CUDA 11.8 runtime for GPU acceleration
    echo GPU detection and access is handled by application
    echo.
    echo === How to Run ===
    echo To start containers, run:
    echo.
    echo   start-docker.bat
    echo.
    echo Then open your browser and navigate to:
    echo   http://localhost:8501
    echo.
    echo === Build Complete ===
    exit /b 0
) else (
    echo.
    echo [ERROR] Docker is not installed or daemon is not running
    echo [DEBUG] Errorlevel: %errorlevel%
    echo.
    echo Possible reasons:
    echo 1. Docker is not installed
    echo 2. Docker Desktop is not running
    echo 3. Docker Desktop is still starting up
    echo 4. Docker Desktop encountered an error
    echo 5. Docker client and server API version mismatch
    echo.
    echo Steps to resolve:
    echo 1. Check if Docker Desktop is installed
    echo 2. Open Docker Desktop application
    echo 3. Wait for it to fully start (check system tray icon)
    echo 4. If already running, try restarting Docker Desktop:
    echo    - Right-click Docker icon in system tray
    echo    - Select "Quit Docker Desktop"
    echo    - Wait 10 seconds, then restart Docker Desktop
    echo    - Wait 30-60 seconds for it to fully initialize
    echo 5. If still failing, check Docker Desktop logs:
    echo    - Open Docker Desktop
    echo    - Click on bug icon in top-right corner
    echo    - Select "Logs" to view detailed error messages
    echo.
    pause
    exit /b 1
)
