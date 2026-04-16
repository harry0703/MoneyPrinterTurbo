@echo off
set CURRENT_DIR=%CD%
echo ***** Current directory: %CURRENT_DIR% *****

echo Starting MoneyPrinterCN with Vue frontend...

set PYTHONPATH=%CURRENT_DIR%

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

rem Check if source files are newer than dist directory
if exist "%VUE_DIST_DIR%" (
    rem Get last modified time of dist directory
    for /f "delims= " %%a in ('dir /t:w "%VUE_DIST_DIR%" ^| findstr "<DIR>"') do set "DIST_TIME=%%a"
    
    rem Get last modified time of source files
    set "SRC_NEWER=false"
    for /r "%VUE_SRC_DIR%" %%f in (*.vue *.ts *.js) do (
        for /f "delims= " %%a in ('dir /t:w "%%f" ^| findstr "%%~nxf"') do (
            if "%%a" gtr "%DIST_TIME%" set "SRC_NEWER=true"
        )
    )
    
    rem Rebuild if source files are newer
    if "%SRC_NEWER%" equ "true" (
        echo Source files are newer, rebuilding production build...
        cd /d "%CURRENT_DIR%\vue-frontend"
        npm run build
        if %ERRORLEVEL% NEQ 0 (
            echo Build failed, starting development server instead...
            set "BUILD_FAILED=true"
        )
        cd /d "%CURRENT_DIR%"
    )
) else (
    echo Production build not found, building now...
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
