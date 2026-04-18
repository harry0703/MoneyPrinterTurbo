@echo off
set CURRENT_DIR=%CD%
echo ***** Current directory: %CURRENT_DIR% *****

echo Starting MoneyPrinterCN with Vue frontend...

set PYTHONPATH=%CURRENT_DIR%

rem Check if npm is already in PATH
where npm >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    rem npm not found in PATH, try to find Node.js installation
    set "NODE_PATH="
    
    rem Check common Node.js installation locations
    if exist "%ProgramFiles%\nodejs" set "NODE_PATH=%ProgramFiles%\nodejs"
    if exist "%ProgramFiles(x86)%\nodejs" set "NODE_PATH=%ProgramFiles(x86)%\nodejs"
    if exist "%LOCALAPPDATA%\Programs\node" set "NODE_PATH=%LOCALAPPDATA%\Programs\node"
    
    rem Try to find npm in various locations
    if defined NODE_PATH (
        set "PATH=%NODE_PATH%;%PATH%"
    ) else (
        rem Try USERPROFILE\.trae-cn as fallback
        if exist "%USERPROFILE%\.trae-cn\sdks\versions\node\current" (
            set "NODE_PATH=%USERPROFILE%\.trae-cn\sdks\versions\node\current"
            set "PATH=%NODE_PATH%;%PATH%"
        )
    )
)

rem Verify npm is now available
where npm >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo WARNING: npm not found. Vue frontend cannot be built.
    echo Please install Node.js from https://nodejs.org/
)

rem Activate conda environment
call conda activate condaenv-moneyprinter

rem Check if activation was successful
if %ERRORLEVEL% NEQ 0 (
    echo Failed to activate conda environment, please ensure the environment is created
    pause
    exit /b 1
)

rem Check if Vue frontend needs to be rebuilt
set "VUE_SRC_DIR=%CURRENT_DIR%\vue-frontend\src"
set "VUE_DIST_DIR=%CURRENT_DIR%\vue-frontend\dist"
set "CONFIG_FILE=%CURRENT_DIR%\config.toml"

rem Get last modified time of dist directory
set "DIST_TIME="
if exist "%VUE_DIST_DIR%" (
    for /f "delims= " %%a in ('dir /t:w "%VUE_DIST_DIR%" ^| findstr "<DIR>"') do set "DIST_TIME=%%a"
)

rem Get last modified time of config file
set "CONFIG_TIME="
if exist "%CONFIG_FILE%" (
    for /f "delims= " %%a in ('dir /t:w "%CONFIG_FILE%" ^| findstr "config.toml"') do set "CONFIG_TIME=%%a"
)

rem Determine if rebuild is needed
set "NEED_REBUILD=false"

rem Check if config.toml is newer than dist directory
if defined DIST_TIME if defined CONFIG_TIME (
    if "%CONFIG_TIME%" gtr "%DIST_TIME%" set "NEED_REBUILD=true"
)

rem Check if source files are newer than dist directory
if exist "%VUE_DIST_DIR%" (
    set "SRC_NEWER=false"
    for /r "%VUE_SRC_DIR%" %%f in (*.vue *.ts *.js) do (
        for /f "delims= " %%a in ('dir /t:w "%%f" ^| findstr "%%~nxf"') do (
            if "%%a" gtr "%DIST_TIME%" set "SRC_NEWER=true"
        )
    )
    
    if "%SRC_NEWER%" equ "true" set "NEED_REBUILD=true"
) else (
    set "NEED_REBUILD=true"
)

rem Rebuild if needed
if "%NEED_REBUILD%" equ "true" (
    echo Config or source files changed, rebuilding production build...
    cd /d "%CURRENT_DIR%\vue-frontend"
    npm run build
    if %ERRORLEVEL% NEQ 0 (
        echo Build failed, starting development server instead...
        set "BUILD_FAILED=true"
    )
    cd /d "%CURRENT_DIR%"
)

rem Start backend API in a new window
start "Backend API" cmd /c "cd /d %CURRENT_DIR% && python main.py"

rem Wait for backend to start
ping localhost -n 5 > nul

echo Backend API started. Starting Vue frontend...

rem Check if Vue frontend is built and build didn't fail
if exist "%VUE_DIST_DIR%" if not defined BUILD_FAILED (
    echo Serving production build...
    rem Use Python's built-in server for production build
    start "Vue Frontend" cmd /c "cd /d %VUE_DIST_DIR% && python -m http.server 3000"
) else (
    echo Starting development server...
    rem Start Vue development server
    start "Vue Frontend" cmd /c "cd /d %CURRENT_DIR%\vue-frontend && npm run dev"
)

echo Frontend started. Opening browser...

rem Open browser to Vue frontend
start http://localhost:3000

echo MoneyPrinterCN is running!
echo Backend API: http://localhost:8000
echo Frontend: http://localhost:3000
echo.
echo Press any key to stop the application...
pause

echo Stopping application...

rem Kill the backend and frontend processes
for /f "tokens=2" %%i in ('tasklist ^| findstr "python.exe" ^| findstr "main.py"') do taskkill /F /PID %%i
for /f "tokens=2" %%i in ('tasklist ^| findstr "node.exe" ^| findstr "vite"') do taskkill /F /PID %%i
for /f "tokens=2" %%i in ('tasklist ^| findstr "python.exe" ^| findstr "http.server"') do taskkill /F /PID %%i

rem Return to original environment
call conda deactivate

echo Application stopped.
