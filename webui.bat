@echo off
setlocal

echo ***** Current directory: %CD% *****
echo Starting MoneyPrinterCN with Vue frontend...

set PYTHONPATH=%CD%

rem Check if npm is available
where npm >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo npm not found in PATH, trying to find Node.js...
    if exist "C:\Program Files\nodejs" set "PATH=C:\Program Files\nodejs;%PATH%"
    if exist "C:\Program Files (x86)\nodejs" set "PATH=C:\Program Files (x86)\nodejs;%PATH%"
    if exist "%LOCALAPPDATA%\Programs\node" set "PATH=%LOCALAPPDATA%\Programs\node;%PATH%"
    if exist "%USERPROFILE%\.trae-cn\sdks\versions\node\current" set "PATH=%USERPROFILE%\.trae-cn\sdks\versions\node\current;%PATH%"
)

rem Activate conda environment
call conda activate condaenv-moneyprinter
if %ERRORLEVEL% NEQ 0 (
    echo Failed to activate conda environment
    pause
    exit /b 1
)

rem Variables
set VUE_DIST=%CD%\vue-frontend\dist

rem Always delete dist directory to force rebuild
echo Cleaning dist directory...
if exist "%VUE_DIST%" (
    rmdir /s /q "%VUE_DIST%"
)

rem Rebuild frontend
echo Rebuilding production build...
cd /d "%CD%\vue-frontend"
call npm run build
if %ERRORLEVEL% NEQ 0 (
    echo Build failed, starting development server instead...
    set BUILD_FAILED=true
)
cd /d "%CD%"

rem Start backend
echo Starting backend API...
start "Backend API" cmd /c "cd /d %CD% && python main.py"

rem Wait for backend to start
echo Waiting for backend to start...
ping localhost -n 5 > nul

rem Start frontend
echo Starting Vue frontend...
if exist "%VUE_DIST%" if not defined BUILD_FAILED (
    echo Starting production server with serve...
    start "Vue Frontend" cmd /c "cd /d %CURRENT_DIR% && npx serve vue-frontend/dist -l 3000 --single"
) else (
    echo Starting development server...
    start "Vue Frontend" cmd /c "cd /d %CURRENT_DIR%\vue-frontend && npm run dev"
)

rem Wait for frontend server to start
echo Waiting for frontend server to start...
ping localhost -n 10 > nul

rem Open browser using PowerShell to avoid PATH issues
echo Opening browser...
powershell -NoProfile -Command "Start-Process 'http://localhost:3000'"

if %ERRORLEVEL% NEQ 0 (
    echo Failed to open browser, trying alternative method...
    start http://localhost:3000
)

echo.
echo MoneyPrinterCN is running!
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000
echo.
echo Press Enter to stop...
pause > nul

echo Stopping...
taskkill /F /FI "WINDOWTITLE eq Backend API*" > nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Vue Frontend*" > nul 2>&1
taskkill /F /IM python.exe /FI "COMMANDLINE like %%main.py%%" > nul 2>&1
taskkill /F /IM python.exe /FI "COMMANDLINE like %%http.server%%" > nul 2>&1
taskkill /F /IM node.exe /FI "COMMANDLINE like %%vite%%" > nul 2>&1

call conda deactivate
echo Done.

endlocal