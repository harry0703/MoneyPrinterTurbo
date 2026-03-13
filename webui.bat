@echo off
set CURRENT_DIR=%CD%
echo ***** Current directory: %CURRENT_DIR% *****

rem Check if Docker is running
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Docker is not running. Please start Docker first.
    pause
    exit /b 1
)

rem Check if the required Docker containers are running
set CONTAINER_NAME=moneyprinterturbo-webui
docker ps -q -f name=%CONTAINER_NAME% >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Docker container %CONTAINER_NAME% is not running.
    echo Please launch the Docker containers first using:
    echo   docker-compose up -d
    pause
    exit /b 1
)

echo Docker container is running properly.

set PYTHONPATH=%CURRENT_DIR%

rem Activate conda environment
call conda activate condaenv-moneyprinter

rem Check if activation was successful
if %ERRORLEVEL% NEQ 0 (
    echo Failed to activate conda environment, please ensure the environment is created
    pause
    exit /b 1
)

rem Run Streamlit app (browser will open automatically by default)
streamlit run .\webui\Main.py --browser.gatherUsageStats=False --server.enableCORS=True

rem Return to original environment
call conda deactivate
