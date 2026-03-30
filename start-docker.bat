@echo off
echo =========================================
echo MoneyPrinterTurboCN Docker Start Script
echo =========================================
echo.

:: Check Docker installation
echo [INFO] Checking Docker...
docker version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running
    exit /b 1
) else (
    echo [INFO] Docker is running
)
echo.

:: Start containers based on argument
echo [INFO] Starting containers...
if "%1" == "--cpu" (
    echo [INFO] Using CPU configuration
    docker-compose -f docker-compose.cpu.yml up -d
) else if "%1" == "--gpu" (
    echo [INFO] Using GPU configuration
    docker-compose up -d
) else (
    echo [INFO] Using default GPU configuration
    docker-compose up -d
)

if errorlevel 1 (
    echo [ERROR] Failed to start containers
    exit /b 1
)
echo.

:: Check container status
echo [INFO] Checking container status...
docker ps --filter name=moneyprinterturbocn-webui --filter name=moneyprinterturbocn-api --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo.

echo [INFO] Containers started successfully!
echo [INFO] WebUI: http://localhost:8501
echo [INFO] API: http://localhost:8080
echo [INFO] API Docs: http://localhost:8080/docs
echo.
echo === Start Complete ===
