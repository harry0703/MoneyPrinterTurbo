@echo off
setlocal EnableDelayedExpansion

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

rem Check if frontend process is running
echo Checking for running frontend processes...
netstat -ano | findstr :3000 >nul
if %ERRORLEVEL% EQU 0 (
    echo ERROR: Frontend service is already running on port 3000
    set "PID="
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3000') do (
        if %%a NEQ 0 set "PID=%%a"
    )
    echo The process ID using port 3000 is: %PID%
    echo What would you like to do?
    echo 1. Kill this process and rebuild frontend
    echo 2. Reuse the existing process
    echo 3. Cancel operation
    set "choice=1"
    set /p "choice=Enter 1, 2, or 3 [default 1]: "
    if "!choice!" equ "" set "choice=1"
    echo You entered: "!choice!"
    if "!choice!" equ "1" (
        if defined PID if not "%PID%" == "" (
            echo Killing process %PID%...
            taskkill /PID %PID% /F
            if %ERRORLEVEL% NEQ 0 (
                echo Failed to kill process
                pause
                exit /b 1
            )
        ) else (
            echo No process ID found, but continuing to kill...
            taskkill /F /IM node.exe > nul 2>&1
            taskkill /F /IM python.exe /FI "COMMANDLINE like %%http.server%%" > nul 2>&1
        )
    ) else if "!choice!" equ "2" (
        echo Reusing existing process...
        set "SKIP_FRONTEND_REBUILD=true"
    ) else if "!choice!" equ "3" (
        echo Operation cancelled
        exit /b 1
    ) else (
        echo Invalid choice, exiting...
        pause
        exit /b 1
    )
)

rem Always delete dist directory to force rebuild
if not defined SKIP_FRONTEND_REBUILD (
    echo Cleaning dist directory...
    if exist "%VUE_DIST%" (
        echo Attempting to delete dist directory...
        rmdir /s /q "%VUE_DIST%"
        if %ERRORLEVEL% NEQ 0 (
            echo ERROR: Failed to delete dist directory. It may be in use by another process.
            echo Killing potential node processes...
            taskkill /F /IM node.exe > nul 2>&1
            taskkill /F /IM python.exe /FI "COMMANDLINE like %%http.server%%" > nul 2>&1
            echo Waiting for processes to terminate...
            ping localhost -n 3 > nul
            echo Attempting to delete dist directory again...
            rmdir /s /q "%VUE_DIST%"
            if %ERRORLEVEL% NEQ 0 (
                echo ERROR: Still failed to delete dist directory
                echo Continuing with build anyway...
            ) else (
                echo dist directory deleted successfully
            )
        )
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
) else (
    echo Skipping frontend rebuild as requested...
)

rem Check if backend port is available
netstat -ano | findstr :8000 >nul
if %ERRORLEVEL% EQU 0 (
    echo ERROR: Port 8000 is already in use by another process
    set "PID="
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
        if %%a NEQ 0 set "PID=%%a"
    )
    echo The process ID using port 8000 is: %PID%
    echo What would you like to do?
    echo 1. Kill this process and start a new backend service
    echo 2. Reuse the existing process
    echo 3. Cancel operation
    set "choice=1"
    set /p "choice=Enter 1, 2, or 3 [default 1]: "
    if "!choice!" equ "" set "choice=1"
    echo You entered: "!choice!"
    if "!choice!" equ "1" (
        if defined PID if not "%PID%" == "" (
            echo Killing process %PID%...
            taskkill /PID %PID% /F
            if %ERRORLEVEL% EQU 0 (
                echo Process killed successfully
            ) else (
                echo Failed to kill process
                echo Skipping backend start...
                set "SKIP_BACKEND=true"
            )
        ) else (
            echo No process ID found, but continuing to kill...
            taskkill /F /IM python.exe /FI "COMMANDLINE like %%main.py%%" > nul 2>&1
        )
    ) else if "!choice!" equ "2" (
        echo Reusing existing process...
        set "SKIP_BACKEND=true"
    ) else if "!choice!" equ "3" (
        echo Operation cancelled
        exit /b 1
    ) else (
        echo Invalid choice, skipping backend start...
        set "SKIP_BACKEND=true"
    )
)

rem Start backend
if not defined SKIP_BACKEND (
    echo Starting backend API...
    start "Backend API" cmd /c "cd /d %CD% && python main.py"

    rem Wait for backend to start
    echo Waiting for backend to start...
    ping localhost -n 10 > nul
) else (
    echo Skipping backend start as requested...
)

rem Check if frontend port is available
if not defined SKIP_FRONTEND_REBUILD (
    netstat -ano | findstr :3000 >nul
    if %ERRORLEVEL% EQU 0 (
        echo ERROR: Port 3000 is already in use by another process
        set "PID="
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3000') do (
            if %%a NEQ 0 set "PID=%%a"
        )
        echo The process ID using port 3000 is: %PID%
        echo What would you like to do?
        echo 1. Kill this process and start a new frontend service
        echo 2. Reuse the existing process
        echo 3. Cancel operation
        set "choice=1"
        set /p "choice=Enter 1, 2, or 3 [default 1]: "
        if "%choice%" equ "" set "choice=1"
        echo You entered: "%choice%"
        if "%choice%" equ "1" (
            if defined PID if not "%PID%" == "" (
                echo Killing process %PID%...
                taskkill /PID %PID% /F
                if %ERRORLEVEL% NEQ 0 (
                    echo Failed to kill process
                    pause
                    exit /b 1
                )
            ) else (
                echo No process ID found, but continuing to kill...
                taskkill /F /IM node.exe > nul 2>&1
                taskkill /F /IM python.exe /FI "COMMANDLINE like %%http.server%%" > nul 2>&1
            )
        ) else if "!choice!" equ "2" (
            echo Reusing existing process...
            set "SKIP_FRONTEND=true"
        ) else if "!choice!" equ "3" (
            echo Operation cancelled
            exit /b 1
        ) else (
            echo Invalid choice, exiting...
            pause
            exit /b 1
        )
    )
) else (
    echo Skipping frontend port check as existing process is being reused...
    set "SKIP_FRONTEND=true"
)

rem Start frontend
if not defined SKIP_FRONTEND (
    echo Starting Vue frontend...
    if exist "%VUE_DIST%" if not defined BUILD_FAILED (
        echo Starting production server with serve...
        start "Vue Frontend" cmd /c "cd /d %CD% && npx serve vue-frontend/dist -l 3000 --single"
    ) else (
        echo Starting development server...
        start "Vue Frontend" cmd /c "cd /d %CD%\vue-frontend && npm run dev"
    )
) else (
    echo Skipping frontend start as requested...
)

rem Wait for frontend server to start
if not defined SKIP_FRONTEND (
    echo Waiting for frontend server to start...
    ping localhost -n 10 > nul
) else (
    echo Skipping frontend wait as requested...
)

rem Open browser using PowerShell to avoid PATH issues
if not defined SKIP_FRONTEND (
    echo Opening browser...
    powershell -NoProfile -Command "Start-Process 'http://localhost:3000'"

    if %ERRORLEVEL% NEQ 0 (
        echo Failed to open browser, trying alternative method...
        start "" "http://localhost:3000"
    )
) else (
    echo Skipping browser opening as frontend start was skipped...
)

echo.
echo MoneyPrinterCN is running!
if not defined SKIP_BACKEND (
    echo Backend: http://localhost:8000
) else (
    echo Backend: Skipped (reusing existing process)
)
if not defined SKIP_FRONTEND (
    echo Frontend: http://localhost:3000
) else (
    echo Frontend: Skipped (reusing existing process)
)
echo.
echo Press Enter to stop...
pause > nul

echo Stopping...
rem Stop backend processes
echo Stopping backend processes...
taskkill /F /FI "WINDOWTITLE eq Backend API*" > nul 2>&1
taskkill /F /IM python.exe /FI "COMMANDLINE like %%main.py%%" > nul 2>&1

rem Stop frontend processes
echo Stopping frontend processes...
taskkill /F /FI "WINDOWTITLE eq Vue Frontend*" > nul 2>&1
taskkill /F /IM python.exe /FI "COMMANDLINE like %%http.server%%" > nul 2>&1
taskkill /F /IM node.exe /FI "COMMANDLINE like %%vite%%" > nul 2>&1

rem Additional cleanup for any remaining processes on ports 8000 and 3000
echo Checking for processes on ports 8000 and 3000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
    if %%a NEQ 0 (
        echo Killing process %%a on port 8000...
        taskkill /PID %%a /F > nul 2>&1
    )
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3000') do (
    if %%a NEQ 0 (
        echo Killing process %%a on port 3000...
        taskkill /PID %%a /F > nul 2>&1
    )
)

call conda deactivate
echo Done.

endlocal