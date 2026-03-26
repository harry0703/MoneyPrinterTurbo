@echo off
echo === MoneyPrinterTurboCN Docker Build Script ===

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

echo Building Docker image...
docker build -t moneyprinterturbocn .

if errorlevel 0 (
    echo.
    echo Success: Docker image built successfully!
    echo.
    echo === Image Details ===
    docker images moneyprinterturbocn
    echo.
    echo === How to Run ===
    echo Run the container with:
    echo.
    echo docker run -v %CD%\config.toml:/MoneyPrinterTurboCN/config.toml -v %CD%\storage:/MoneyPrinterTurboCN/storage -p 8501:8501 moneyprinterturbocn
    echo.
    echo Then open your browser and navigate to: http://localhost:8501
) else (
    echo Error: Docker build failed
    pause
    exit /b 1
)

echo.
echo === Build Complete ===
pause