@echo off
chcp 65001 >nul
echo ========================================
echo MoneyPrinterTurboCN Docker Build Script
echo ========================================
echo.

echo [INFO] Checking Docker installation...
docker --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not installed or not in PATH
    echo Please install Docker Desktop and try again.
    pause
    exit /b 1
)
echo [INFO] Docker is installed
echo.

echo [INFO] Checking Docker daemon status...
:: Check if Docker daemon is running by testing multiple commands
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker daemon is not responding
    echo.
    echo Possible reasons:
    echo 1. Docker Desktop is not running
    echo 2. Docker Desktop is still starting up
    echo 3. Docker client and server API version mismatch
    echo.
    echo Troubleshooting steps:
    echo 1. Check if Docker Desktop is running in system tray
    echo 2. If running, try restarting Docker Desktop:
    echo    - Right-click Docker icon in system tray
    echo    - Select "Quit Docker Desktop"
    echo    - Wait 10 seconds, then restart Docker Desktop
    echo    - Wait 30-60 seconds for it to fully start
    echo 3. Check Docker Desktop logs for errors
    echo 4. Try running "docker version" to see detailed error
    echo.
    pause
    exit /b 1
)
echo [INFO] Docker daemon is running
echo.

echo [INFO] Pre-downloading base image...
echo [INFO] This may take several minutes depending on your network speed
echo [INFO] Base image: python:3.11-slim-bullseye (Original base image)
echo.
echo [TIP] If download is slow, consider configuring Docker mirror accelerators:
echo [TIP] 1. Open Docker Desktop Settings
echo [TIP] 2. Go to Docker Engine
echo [TIP] 3. Add registry-mirrors configuration
echo.

:: Pre-download base image to show progress
docker pull python:3.11-slim-bullseye

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to download base image
    echo Please check your network connection or configure Docker mirror accelerators
    pause
    exit /b 1
)

echo.
echo [INFO] Base image downloaded successfully
echo [INFO] Building Docker image...
echo [INFO] Starting build process...
echo.

:: Build with progress output
docker build --progress=plain -t moneyprinterturbocn .

if errorlevel 1 (
    echo.
    echo [ERROR] Docker build failed
    echo Please check error messages above.
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
echo === How to Run ===
echo To start containers, run:
echo.
echo   start-docker.bat
echo.
echo Then open your browser and navigate to:
echo   http://localhost:8501
echo.
echo === Build Complete ===
pause
