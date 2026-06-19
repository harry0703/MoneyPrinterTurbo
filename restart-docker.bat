@echo off
setlocal EnableDelayedExpansion

echo ============================================
echo  Clearing Python cache and restarting Docker
echo ============================================
echo.

REM Check if Docker is running
echo [1/4] Checking Docker status...
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Docker is not running. Please start Docker first.
    pause
    exit /b 1
)
echo  Docker is running

REM Show current containers
echo.
echo [2/4] Current Docker containers:
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

REM Clear Python cache in containers
echo.
echo [3/4] Clearing Python cache in Docker containers...

set "containers=coiner-api"

for %%c in (%containers%) do (
    echo  Processing container: %%c
    
    REM Check if container is running
    docker ps --filter "name=%%c" --format "{{.Names}}" >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        REM Clear __pycache__ directories
        docker exec %%c find /Coiner -type d -name "__pycache__" -exec rm -rf {} + >nul 2>&1
        if %ERRORLEVEL% EQU 0 (
            echo    Cleared __pycache__ directories
        ) else (
            echo    No __pycache__ directories found (or already clean)
        )
        
        REM Clear .pyc files
        docker exec %%c find /Coiner -name "*.pyc" -delete >nul 2>&1
        if %ERRORLEVEL% EQU 0 (
            echo    Cleared *.pyc files
        ) else (
            echo    No *.pyc files found (or already clean)
        )
        
        REM Clear .pyo files (optimized bytecode)
        docker exec %%c find /Coiner -name "*.pyo" -delete >nul 2>&1
        if %ERRORLEVEL% EQU 0 (
            echo    Cleared *.pyo files
        )
    ) else (
        echo    Container not running, skipping
    )
)

REM Also clear local Python cache if exists
echo.
echo [4/4] Clearing local Python cache...

REM Clear __pycache__ directories
for /d /r "%CD%" %%d in (__pycache__) do (
    if exist "%%d" (
        rd /s /q "%%d"
        set "cleared_cache=1"
    )
)
if defined cleared_cache (
    echo  Cleared local __pycache__ directories
) else (
    echo  No local __pycache__ directories found
)

REM Clear .pyc files
set "cleared_pyc=0"
for /r "%CD%" %%f in (*.pyc) do (
    if exist "%%f" (
        del /f "%%f"
        set "cleared_pyc=1"
    )
)
if %cleared_pyc% EQU 1 (
    echo  Cleared local *.pyc files
) else (
    echo  No local *.pyc files found
)

REM Restart containers
echo.
echo [5/5] Restarting Docker containers...
docker-compose restart

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [WARNING] Failed to restart containers. Trying to start them...
    docker-compose up -d
)

REM Show final status
echo.
echo ============================================
echo  Done! Docker containers have been restarted
echo ============================================
echo.
echo You can now access:
echo  - Application:     http://localhost:8080
echo  - API:             http://localhost:8080
echo.
echo Note: Application runs on port 8080
echo.

REM Show running containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo.
pause
