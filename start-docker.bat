@echo off
echo === MoneyPrinterTurboCN Docker Start Script ===

docker --version >nul 2>&1
if errorlevel 1 (
    echo Error: Docker is not installed or not in PATH
    echo Please install Docker Desktop and try again.
    pause
    exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
    echo Error: Docker daemon is not running
    echo Please start Docker Desktop and try again.
    pause
    exit /b 1
)

echo === Checking Docker Volumes ===
echo Creating dedicated volumes for configuration and storage...
echo.
docker volume create moneyprinter-config 2>nul
docker volume create moneyprinter-storage 2>nul
echo.

echo === Starting Docker Containers ===
echo Starting MoneyPrinterTurboCN containers...
echo.

:: Stop any existing containers with the same name
docker stop moneyprinterturbocn-webui 2>nul
docker rm moneyprinterturbocn-webui 2>nul
docker stop moneyprinterturbocn-api 2>nul
docker rm moneyprinterturbocn-api 2>nul
echo.

:: Start the containers using docker-compose
echo [INFO] Starting containers...
docker-compose up -d

:: Give containers time to start
timeout /t 2 /nobreak >nul

:: Check if containers are running by checking specific container names
docker ps --filter name=moneyprinterturbocn-webui >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo Success: MoneyPrinterTurboCN containers started successfully!
    echo.
    echo === Container Information ===
    docker ps --filter name=moneyprinterturbocn
    echo.
    echo === Access Information ===
    echo WebUI: http://localhost:8501
    echo API: http://localhost:8080
    echo API Documentation: http://localhost:8080/docs
    echo.
    echo === Volume Information ===
    echo Configuration volume: moneyprinter-config
    echo Storage volume: moneyprinter-storage
    echo Model volume: ./models (mounted from host)
    echo.
    echo === GPU Support ===
    echo Note: GPU support is handled by the application
    echo The application will automatically use GPU if available
    echo or fall back to CPU mode if GPU is not available
    echo.
    echo These volumes are independent from your development environment.
) else (
    echo.
    echo Error: Failed to start containers
    echo [INFO] Please check Docker Desktop for more details
    pause
    exit /b 1
)

echo.
echo === Start Complete ===
pause
